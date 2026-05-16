#!/usr/bin/env bash
# watcher.sh — CI disk & Docker stats collector
# Usage: watcher.sh <PR> <MERGE_SHA> <STATS_DIR> [HEAD_SHA]
# Runs in background during a CI pipeline. Polls every 10s. Writes timeline.ndjson.
set -euo pipefail

PR="${1:?PR number required}"
SHA="${2:?merge SHA required}"
STATS_DIR="${3:?STATS_DIR required}"
HEAD_SHA="${4:-$SHA}"
STAGE_FILE="${CI_STATS_STAGE_FILE:-/tmp/ci-stage-${PR}}"
TIMELINE="${STATS_DIR}/timeline.ndjson"
SNAPSHOT="${STATS_DIR}/snapshot.json"
DOCKER_IMAGES_FILE="${STATS_DIR}/docker-images.json"
DOCKER_CONTAINERS_FILE="${STATS_DIR}/docker-containers.json"
DOCKER_VOLUMES_FILE="${STATS_DIR}/docker-volumes.json"
DOCKER_DANGLING_SUMMARY_FILE="${STATS_DIR}/docker-dangling-summary.json"
DOCKER_BUILD_CACHE_FILE="${STATS_DIR}/docker-build-cache.json"
DIRECTORY_SIZES_FILE="${STATS_DIR}/directory-sizes.ndjson"
INODE_USAGE_FILE="${STATS_DIR}/inode-usage.ndjson"
HOST_STATS_FILE="${STATS_DIR}/host-stats.ndjson"

mkdir -p "$STATS_DIR"

log() {
  echo "[watcher] $*"
}

json_escape() {
  local value="${1:-}"
  value="${value//\\/\\\\}"
  value="${value//\"/\\\"}"
  value="${value//$'\n'/ }"
  value="${value//$'\r'/ }"
  printf '%s' "$value"
}

dir_size_kb() {
  local path="${1:-}"
  local size

  if [ -z "$path" ] || [ ! -e "$path" ]; then
    echo 0
    return 0
  fi

  size=$(
    (
      set +o pipefail
      du -sk -x -- "$path" 2>/dev/null | awk 'NR==1 {print $1; found=1; exit} END {if (!found) print 0}'
    ) || true
  )

  if [ -z "$size" ]; then
    echo 0
  else
    printf '%s\n' "$size"
  fi
}

resolve_runner_workspace_dir() {
  if [ -n "${GITHUB_WORKSPACE:-}" ]; then
    echo "$GITHUB_WORKSPACE"
    return 0
  fi

  if [ -n "${RUNNER_WORKSPACE:-}" ]; then
    echo "$RUNNER_WORKSPACE"
    return 0
  fi

  echo ""
}

resolve_preview_base_dir() {
  if [ -n "${PREVIEW_BASE_DIR:-}" ]; then
    echo "$PREVIEW_BASE_DIR"
    return 0
  fi

  if [ -n "${RUNNER_HOME:-}" ]; then
    echo "${RUNNER_HOME}/previews"
    return 0
  fi

  if [ -n "${HOME:-}" ]; then
    echo "${HOME}/previews"
    return 0
  fi

  echo ""
}

resolve_actions_runner_work_dir() {
  if [ -n "${RUNNER_WORKSPACE:-}" ]; then
    echo "$RUNNER_WORKSPACE"
    return 0
  fi

  if [ -n "${GITHUB_WORKSPACE:-}" ]; then
    dirname "$GITHUB_WORKSPACE"
    return 0
  fi

  echo ""
}

resolve_docker_root_dir() {
  local out
  out=$(docker info --format '{{.DockerRootDir}}' 2>/dev/null || true)

  if [ -n "$out" ]; then
    echo "$out"
  else
    echo "/var/lib/docker"
  fi
}

# Parse `df -P <mount>` into JSON fields safely
df_json() {
  local mount="$1"
  local out

  if ! out=$(df -P "$mount" 2>/dev/null); then
    printf '{"mount":"%s","size_kb":0,"used_kb":0,"avail_kb":0,"pct":0}' "$mount"
    return 0
  fi

  echo "$out" | awk -v m="$mount" 'NR==2 {
    pct=$5
    gsub(/%/, "", pct)
    printf "{\"mount\":\"%s\",\"size_kb\":%s,\"used_kb\":%s,\"avail_kb\":%s,\"pct\":%s}",
      m, $2, $3, $4, pct
  }'
}

# docker system df — parse summary rows
docker_sys_df_json() {
  local out
  out=$(docker system df 2>/dev/null || true)

  if [ -z "$out" ]; then
    echo '"images_total":"0","images_reclaimable":"0B","containers_total":"0","containers_reclaimable":"0B","volumes_total":"0","volumes_reclaimable":"0B","build_cache_total":"0","build_cache_reclaimable":"0B"'
    return 0
  fi

  echo "$out" | awk '
    /^Images/ {
      gsub(/[[:space:]]+/, " ")
      split($0,a," ")
      printf "\"images_total\":\"%s\",\"images_reclaimable\":\"%s\"", a[3], a[5]
    }
    /^Containers/ {
      gsub(/[[:space:]]+/, " ")
      split($0,a," ")
      printf ",\"containers_total\":\"%s\",\"containers_reclaimable\":\"%s\"", a[3], a[5]
    }
    /^Local Volumes/ {
      gsub(/[[:space:]]+/, " ")
      split($0,a," ")
      printf ",\"volumes_total\":\"%s\",\"volumes_reclaimable\":\"%s\"", a[4], a[6]
    }
    /^Build Cache/ {
      gsub(/[[:space:]]+/, " ")
      split($0,a," ")
      printf ",\"build_cache_total\":\"%s\",\"build_cache_reclaimable\":\"%s\"", a[4], a[6]
    }
  '
}

# docker images filtered to xenium images in Harbor
xenium_images_json() {
  local result="["
  local first=1
  local out

  out=$(docker images --format '{{.Repository}}|{{.Tag}}|{{.Size}}' 2>/dev/null || true)

  while IFS='|' read -r repo tag size; do
    [ -z "$repo" ] && continue
    if [[ "$repo" == */xenium/* ]]; then
      [ "$first" -eq 1 ] || result+=","
      result+="{\"repo\":\"${repo}\",\"tag\":\"${tag}\",\"size\":\"${size}\"}"
      first=0
    fi
  done <<< "$out"

  result+="]"
  echo "$result"
}

# detailed Docker image inventory for Xenium/current CI images
docker_image_inventory_json() {
  local captured_at="$1"
  local out

  out=$(docker images --digests --no-trunc --format '{{.Repository}}	{{.Tag}}	{{.ID}}	{{.Digest}}	{{.CreatedSince}}	{{.Size}}' 2>/dev/null || true)

  if [ -z "$out" ]; then
    printf '{\n  "captured_at": "%s",\n  "images": []\n}' "$captured_at"
    return 0
  fi

  printf '%s\n' "$out" | python3 -c '
import json
import re
import sys

pr = sys.argv[1]
merge_sha = sys.argv[2]
head_sha = sys.argv[3]
captured_at = sys.argv[4]
known_shas = {value for value in (merge_sha, head_sha) if value}
known_shas.update(value[:8] for value in list(known_shas) if value)

def belongs_to_current_pr(tag):
    return bool(re.search(rf"(?:^|[-_])(build|pr)-{re.escape(pr)}(?:[-_]|$)", tag or ""))

def extract_tag_sha(tag):
    match = re.match(rf"^(?:build|pr)-{re.escape(pr)}-([0-9a-fA-F]+)$", tag or "")
    return match.group(1).lower() if match else None

def belongs_to_current_sha(tag):
    tag_sha = extract_tag_sha(tag)
    if not tag_sha:
        return False
    return tag_sha.lower() in {value.lower() for value in known_shas}

images = []
seen = set()

for raw_line in sys.stdin:
    line = raw_line.rstrip("\n")
    if not line:
        continue

    parts = line.split("\t")
    if len(parts) != 6:
        continue

    repository, tag, image_id, digest, created_since, size = parts
    repository = repository.strip()
    tag = tag.strip()
    image_id = image_id.strip()
    digest = digest.strip()
    created_since = created_since.strip()
    size = size.strip()

    current_pr = belongs_to_current_pr(tag)
    current_sha = belongs_to_current_sha(tag)
    relevant_repo = "/xenium/" in repository

    if not (relevant_repo or current_pr or current_sha):
        continue

    if digest in ("", "<none>"):
        digest = None

    item = {
        "repository": repository,
        "tag": tag,
        "image_id": image_id,
        "digest": digest,
        "created_since": created_since,
        "size": size,
        "belongs_to_current_pr": current_pr,
        "belongs_to_current_sha": current_sha,
    }

    dedupe_key = (repository, tag, image_id, digest)
    if dedupe_key in seen:
        continue
    seen.add(dedupe_key)
    images.append(item)

images.sort(key=lambda item: (
    item["repository"],
    item["tag"],
    item["image_id"],
    "" if item["digest"] is None else item["digest"],
))

print(json.dumps({
    "captured_at": captured_at,
    "images": images,
}, indent=2))
' "$PR" "$SHA" "$HEAD_SHA" "$captured_at"
}

# docker stats --no-stream — one-shot CPU + memory per container
container_stats_json() {
  local result="["
  local first=1
  local out

  out=$(docker stats --no-stream --format '{{.Name}}|{{.CPUPerc}}|{{.MemUsage}}|{{.MemPerc}}' 2>/dev/null || true)

  if [ -n "$out" ]; then
    while IFS='|' read -r name cpu mu mp; do
      [ -z "$name" ] && continue

      local info img sts mu_used mu_limit
      info=$(docker ps --filter "name=^/${name}$" --format '{{.Image}}|{{.Status}}' | head -n 1 || true)
      img=$(printf '%s' "$info" | cut -d'|' -f1)
      sts=$(printf '%s' "$info" | cut -d'|' -f2)

      mu_used=$(printf '%s' "$mu" | awk '{print $1}')
      mu_limit=$(printf '%s' "$mu" | awk '{print $3}')

      [ "$first" -eq 1 ] || result+=","
      result+="{\"name\":\"${name}\",\"cpu_pct\":\"${cpu}\",\"mem_usage\":\"${mu_used}\",\"mem_limit\":\"${mu_limit}\",\"mem_pct\":\"${mp}\",\"image\":\"${img}\",\"status\":\"${sts}\"}"
      first=0
    done <<< "$out"
  fi

  result+="]"
  echo "$result"
}

docker_container_inventory_json() {
  local captured_at="$1"
  local out

  out=$(docker ps -a --size --no-trunc --format '{{.Names}}	{{.ID}}	{{.Image}}	{{.Status}}	{{.Size}}	{{.CreatedAt}}	{{.Label "com.docker.compose.project"}}' 2>/dev/null || true)

  if [ -z "$out" ]; then
    printf '{\n  "captured_at": "%s",\n  "containers": []\n}' "$captured_at"
    return 0
  fi

  printf '%s\n' "$out" | python3 -c '
import json
import re
import sys

pr = sys.argv[1]
captured_at = sys.argv[2]
known_test_services = {
    "ui",
    "api",
    "postgres",
    "init_data_dirs",
    "celery_worker",
    "watch",
    "queue",
    "mongo",
    "rhythm",
    "secure_download",
    "signet",
    "signet_db",
    "e2e",
}

def belongs_to_preview_stack(name, compose_project):
    expected_project = f"preview-pr-{pr}"
    return expected_project in (name or "") or expected_project in (compose_project or "")

def belongs_to_test_stack(name, compose_project):
    if (compose_project or "") == "bioloop":
        return True
    match = re.match(r"^bioloop-([a-z0-9_]+)-\d+$", name or "")
    return bool(match and match.group(1) in known_test_services)

containers = []

for raw_line in sys.stdin:
    line = raw_line.rstrip("\n")
    if not line:
        continue

    parts = line.split("\t")
    if len(parts) != 7:
        continue

    container_name, container_id, image, status, size, created_at, compose_project = [part.strip() for part in parts]
    containers.append({
        "container_name": container_name,
        "container_id": container_id,
        "image": image,
        "status": status,
        "size": size or "",
        "created_at": created_at,
        "belongs_to_preview_stack": belongs_to_preview_stack(container_name, compose_project),
        "belongs_to_test_stack": belongs_to_test_stack(container_name, compose_project),
    })

containers.sort(key=lambda item: (
    item["container_name"],
    item["container_id"],
))

print(json.dumps({
    "captured_at": captured_at,
    "containers": containers,
}, indent=2))
' "$PR" "$captured_at"
}

docker_volume_inventory_json() {
  local captured_at="$1"
  local out

  out=$(docker volume ls -q 2>/dev/null || true)

  if [ -z "$out" ]; then
    printf '{\n  "captured_at": "%s",\n  "volumes": []\n}' "$captured_at"
    return 0
  fi

  printf '%s\n' "$out" | python3 -c '
import json
import subprocess
import sys

pr = sys.argv[1]
captured_at = sys.argv[2]
expected_project = f"preview-pr-{pr}"
volumes = []

for raw_line in sys.stdin:
    volume_name = raw_line.strip()
    if not volume_name:
        continue

    try:
        inspected = subprocess.run(
            ["docker", "volume", "inspect", volume_name],
            capture_output=True,
            text=True,
            check=False,
        )
        if inspected.returncode != 0 or not inspected.stdout.strip():
            raise RuntimeError("inspect failed")
        payload = json.loads(inspected.stdout)
        info = payload[0] if isinstance(payload, list) and payload else {}
    except Exception:
        info = {}

    labels = info.get("Labels")
    if not isinstance(labels, dict):
        labels = {}

    compose_project = labels.get("com.docker.compose.project", "")
    belongs_to_preview_stack = (
        expected_project in volume_name or
        compose_project == expected_project
    )

    volumes.append({
        "volume_name": info.get("Name") or volume_name,
        "driver": info.get("Driver", ""),
        "mountpoint": info.get("Mountpoint", ""),
        "labels": labels,
        "belongs_to_preview_stack": belongs_to_preview_stack,
    })

volumes.sort(key=lambda item: item["volume_name"])

print(json.dumps({
    "captured_at": captured_at,
    "volumes": volumes,
}, indent=2, sort_keys=False))
' "$PR" "$captured_at"
}

docker_dangling_summary_json() {
  local captured_at="$1"

  python3 -c '
import json
import subprocess
import sys

captured_at = sys.argv[1]

def run(args):
    result = subprocess.run(args, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        return ""
    return result.stdout.strip()

def count_lines(text):
    return len([line for line in text.splitlines() if line.strip()])

def format_bytes(size):
    if size <= 0:
        return "0B"
    units = ["B", "KB", "MB", "GB", "TB"]
    value = float(size)
    unit_index = 0
    while value >= 1024 and unit_index < len(units) - 1:
        value /= 1024.0
        unit_index += 1
    if unit_index == 0:
        return f"{int(value)}{units[unit_index]}"
    return f"{value:.1f}{units[unit_index]}"

def inspect_json(args):
    output = run(args)
    if not output:
        return []
    try:
        payload = json.loads(output)
        return payload if isinstance(payload, list) else []
    except Exception:
        return []

dangling_image_ids = sorted(set(
    line.strip()
    for line in run(["docker", "images", "-f", "dangling=true", "-q", "--no-trunc"]).splitlines()
    if line.strip()
))
dangling_volumes = run(["docker", "volume", "ls", "-qf", "dangling=true"])
stopped_container_ids = sorted(set(
    line.strip()
    for line in run(["docker", "ps", "-aq", "-f", "status=exited"]).splitlines()
    if line.strip()
))

dangling_image_size_bytes = 0
if dangling_image_ids:
    for item in inspect_json(["docker", "image", "inspect", *dangling_image_ids]):
        dangling_image_size_bytes += int(item.get("Size") or 0)

stopped_container_size_bytes = 0
if stopped_container_ids:
    for item in inspect_json(["docker", "inspect", "--size", *stopped_container_ids]):
        stopped_container_size_bytes += int(item.get("SizeRw") or 0)

summary = {
    "captured_at": captured_at,
    "dangling_images_count": len(dangling_image_ids),
    "dangling_images_size": format_bytes(dangling_image_size_bytes),
    "dangling_volumes_count": count_lines(dangling_volumes),
    "stopped_containers_count": len(stopped_container_ids),
    "stopped_containers_size": format_bytes(stopped_container_size_bytes),
}

print(json.dumps(summary, indent=2))
' "$captured_at"
}

docker_build_cache_json() {
  local captured_at="$1"
  local docker_df_json
  local buildx_version
  local buildx_du

  docker_df_json="{$(docker_sys_df_json)}"
  buildx_version=$(docker buildx version 2>/dev/null || true)
  buildx_du=$(docker buildx du --verbose --format json 2>/dev/null || true)

  python3 -c '
import json
import sys

captured_at = sys.argv[1]
docker_df_raw = sys.argv[2]
buildx_version = sys.argv[3]
buildx_du_raw = sys.argv[4]

def load_json(raw, default):
    try:
        return json.loads(raw)
    except Exception:
        return default

docker_df = load_json(docker_df_raw, {})
cache_total = str(docker_df.get("build_cache_total", "0B"))
cache_reclaimable = str(docker_df.get("build_cache_reclaimable", "0B"))
if cache_total in ("", "0"):
    cache_total = "0B"
if cache_reclaimable in ("", "0"):
    cache_reclaimable = "0B"

builder_backend = "docker"
cache_entries = []

if buildx_version.strip():
    builder_backend = buildx_version.strip().splitlines()[0]

buildx_payload = load_json(buildx_du_raw, None)
raw_entries = []
if isinstance(buildx_payload, list):
    raw_entries = buildx_payload
elif isinstance(buildx_payload, dict):
    for key in ("records", "items", "entries"):
        candidate = buildx_payload.get(key)
        if isinstance(candidate, list):
            raw_entries = candidate
            break

for entry in raw_entries:
    if not isinstance(entry, dict):
        continue
    cache_entries.append({
        "id": str(entry.get("id", "")),
        "description": str(entry.get("description", "")),
        "size": str(entry.get("size", "")),
        "reclaimable": entry.get("reclaimable", False),
        "shared": entry.get("shared", False),
    })

cache_entries.sort(key=lambda item: (item["id"], item["description"], item["size"]))

print(json.dumps({
    "captured_at": captured_at,
    "cache_total": cache_total,
    "cache_reclaimable": cache_reclaimable,
    "cache_entries": cache_entries,
    "builder_backend": builder_backend,
}, indent=2))
' "$captured_at" "$docker_df_json" "$buildx_version" "$buildx_du"
}

directory_sizes_json() {
  local captured_at="$1"
  local tick="$2"
  local stage="$3"
  local runner_workspace_path
  local preview_base_dir_path
  local current_pr_preview_dir_path
  local docker_root_dir_path
  local var_lib_docker_path
  local actions_runner_work_path
  local ci_stats_dir_path

  runner_workspace_path=$(resolve_runner_workspace_dir)
  preview_base_dir_path=$(resolve_preview_base_dir)
  current_pr_preview_dir_path=""
  [ -n "$preview_base_dir_path" ] && current_pr_preview_dir_path="${preview_base_dir_path}/pr-${PR}"
  docker_root_dir_path=$(resolve_docker_root_dir)
  # NOTE: var_lib_docker_path is the default Docker root; on most runners it equals
  # docker_root_dir_path (resolved via `docker info`). du may return 0 without root.
  var_lib_docker_path="/var/lib/docker"
  actions_runner_work_path=$(resolve_actions_runner_work_dir)
  ci_stats_dir_path="$STATS_DIR"

  printf '{"timestamp":"%s","tick":%d,"stage":"%s","runner_workspace_path":"%s","runner_workspace_size":%s,"preview_base_dir_path":"%s","preview_base_dir_size":%s,"current_pr_preview_dir_path":"%s","current_pr_preview_dir_size":%s,"docker_root_dir_path":"%s","docker_root_dir_size":%s,"var_lib_docker_path":"%s","var_lib_docker_size":%s,"actions_runner_work_path":"%s","actions_runner_work_size":%s,"ci_stats_dir_path":"%s","ci_stats_dir_size":%s}' \
    "$captured_at" \
    "$tick" \
    "$(json_escape "$stage")" \
    "$(json_escape "$runner_workspace_path")" \
    "$(dir_size_kb "$runner_workspace_path")" \
    "$(json_escape "$preview_base_dir_path")" \
    "$(dir_size_kb "$preview_base_dir_path")" \
    "$(json_escape "$current_pr_preview_dir_path")" \
    "$(dir_size_kb "$current_pr_preview_dir_path")" \
    "$(json_escape "$docker_root_dir_path")" \
    "$(dir_size_kb "$docker_root_dir_path")" \
    "$(json_escape "$var_lib_docker_path")" \
    "$(dir_size_kb "$var_lib_docker_path")" \
    "$(json_escape "$actions_runner_work_path")" \
    "$(dir_size_kb "$actions_runner_work_path")" \
    "$(json_escape "$ci_stats_dir_path")" \
    "$(dir_size_kb "$ci_stats_dir_path")"
}

inode_usage_line_for_path() {
  local captured_at="$1"
  local tick="$2"
  local stage="$3"
  local path="$4"
  local out

  out=$(df -Pi "$path" 2>/dev/null | awk -v ts="$captured_at" -v tk="$tick" -v st="$stage" -v requested="$path" '
    NR==2 {
      pct=$5
      gsub(/%/, "", pct)
      gsub(/\\/,"\\\\", st)
      gsub(/"/,"\\\"", st)
      gsub(/\\/,"\\\\", requested)
      gsub(/"/,"\\\"", requested)
      gsub(/\\/,"\\\\", $1)
      gsub(/"/,"\\\"", $1)
      gsub(/\\/,"\\\\", $6)
      gsub(/"/,"\\\"", $6)
      printf "{\"timestamp\":\"%s\",\"tick\":%s,\"stage\":\"%s\",\"path\":\"%s\",\"filesystem\":\"%s\",\"mount\":\"%s\",\"inode_total\":%s,\"inode_used\":%s,\"inode_free\":%s,\"inode_pct\":%s}",
        ts, tk, st, requested, $1, $6, $2, $3, $4, pct
    }
  ' || true)

  if [ -n "$out" ]; then
    printf '%s' "$out"
  else
    printf '{"timestamp":"%s","tick":%d,"stage":"%s","path":"%s","filesystem":"","mount":"","inode_total":0,"inode_used":0,"inode_free":0,"inode_pct":0}' \
      "$captured_at" \
      "$tick" \
      "$(json_escape "$stage")" \
      "$(json_escape "$path")"
  fi
}

host_stats_json() {
  local captured_at="$1"
  local tick="$2"
  local stage="$3"
  local mem_total
  local mem_available
  local swap_total
  local swap_free
  local memory_used
  local swap_used
  local load_1
  local load_5
  local load_15
  local cpu_cores

  mem_total=$(awk '/^MemTotal:/ {print $2; exit}' /proc/meminfo 2>/dev/null || true)
  # MemAvailable = free + reclaimable; more useful than MemFree for resource pressure.
  mem_available=$(awk '/^MemAvailable:/ {print $2; exit}' /proc/meminfo 2>/dev/null || true)
  swap_total=$(awk '/^SwapTotal:/ {print $2; exit}' /proc/meminfo 2>/dev/null || true)
  swap_free=$(awk '/^SwapFree:/ {print $2; exit}' /proc/meminfo 2>/dev/null || true)

  if [ -z "$mem_total" ] || [ -z "$mem_available" ]; then
    # Fallback: `free -k` column 7 (available) was added in procps-ng 3.3.10.
    mem_total=$(free -k 2>/dev/null | awk '/^Mem:/ {print $2; exit}' || true)
    mem_available=$(free -k 2>/dev/null | awk '/^Mem:/ {print $7; exit}' || true)
  fi

  if [ -z "$swap_total" ] || [ -z "$swap_free" ]; then
    swap_total=$(free -k 2>/dev/null | awk '/^Swap:/ {print $2; exit}' || true)
    swap_free=$(free -k 2>/dev/null | awk '/^Swap:/ {print $4; exit}' || true)
  fi

  mem_total="${mem_total:-0}"
  mem_available="${mem_available:-0}"
  swap_total="${swap_total:-0}"
  swap_free="${swap_free:-0}"

  if [ "$mem_total" -ge "$mem_available" ] 2>/dev/null; then
    memory_used=$((mem_total - mem_available))
  else
    memory_used=0
  fi

  if [ "$swap_total" -ge "$swap_free" ] 2>/dev/null; then
    swap_used=$((swap_total - swap_free))
  else
    swap_used=0
  fi

  load_1=$(awk '{print $1; exit}' /proc/loadavg 2>/dev/null || true)
  load_5=$(awk '{print $2; exit}' /proc/loadavg 2>/dev/null || true)
  load_15=$(awk '{print $3; exit}' /proc/loadavg 2>/dev/null || true)

  # CPU core count makes load averages interpretable (load/cores gives utilisation ratio).
  cpu_cores=$(grep -c '^processor' /proc/cpuinfo 2>/dev/null || echo 0)

  # Field is named memory_available (not memory_free) because we report MemAvailable
  # (free + reclaimable), which is the proper measure of what processes can actually use.
  printf '{"timestamp":"%s","tick":%d,"stage":"%s","cpu_cores":%s,"memory_total":%s,"memory_used":%s,"memory_available":%s,"swap_used":%s,"load_average":{"1m":%s,"5m":%s,"15m":%s}}' \
    "$captured_at" \
    "$tick" \
    "$(json_escape "$stage")" \
    "${cpu_cores:-0}" \
    "$mem_total" \
    "$memory_used" \
    "$mem_available" \
    "$swap_used" \
    "${load_1:-0}" \
    "${load_5:-0}" \
    "${load_15:-0}"
}

current_stage() {
  if [ -f "$STAGE_FILE" ]; then
    cat "$STAGE_FILE"
  else
    echo "initializing"
  fi
}

log "Started. PR=${PR} SHA=${SHA} STATS_DIR=${STATS_DIR}"
log "Polling every 10 seconds..."

TICK=0
while true; do
  TS=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  STAGE=$(current_stage)

  FS_ROOT=$(df_json "/")
  FS_VAR=$(df_json "/var")
  FS_OPT=$(df_json "/opt/sca")
  DOCKER_DF=$(docker_sys_df_json)
  IMAGES=$(xenium_images_json)
  DOCKER_IMAGE_INVENTORY=$(docker_image_inventory_json "$TS")
  DOCKER_CONTAINER_INVENTORY=$(docker_container_inventory_json "$TS")
  DOCKER_VOLUME_INVENTORY=$(docker_volume_inventory_json "$TS")
  DOCKER_DANGLING_SUMMARY=$(docker_dangling_summary_json "$TS")
  DOCKER_BUILD_CACHE=$(docker_build_cache_json "$TS")
  DIRECTORY_SIZES=$(directory_sizes_json "$TS" "$TICK" "$STAGE")
  HOST_STATS=$(host_stats_json "$TS" "$TICK" "$STAGE")
  CONTAINERS=$(container_stats_json)

  TICK_JSON=$(printf '{"tick":%d,"ts":"%s","stage":"%s","fs":[%s,%s,%s],"docker_df":{%s},"images":%s,"containers":%s}' \
    "$TICK" "$TS" "$STAGE" "$FS_ROOT" "$FS_VAR" "$FS_OPT" "$DOCKER_DF" "$IMAGES" "$CONTAINERS")

  echo "$TICK_JSON" >> "$TIMELINE"

  printf '%s\n' "$TICK_JSON" > "${SNAPSHOT}.tmp"
  mv "${SNAPSHOT}.tmp" "$SNAPSHOT"

  printf '%s\n' "$DOCKER_IMAGE_INVENTORY" > "${DOCKER_IMAGES_FILE}.tmp"
  mv "${DOCKER_IMAGES_FILE}.tmp" "$DOCKER_IMAGES_FILE"

  printf '%s\n' "$DOCKER_CONTAINER_INVENTORY" > "${DOCKER_CONTAINERS_FILE}.tmp"
  mv "${DOCKER_CONTAINERS_FILE}.tmp" "$DOCKER_CONTAINERS_FILE"

  printf '%s\n' "$DOCKER_VOLUME_INVENTORY" > "${DOCKER_VOLUMES_FILE}.tmp"
  mv "${DOCKER_VOLUMES_FILE}.tmp" "$DOCKER_VOLUMES_FILE"

  printf '%s\n' "$DOCKER_DANGLING_SUMMARY" > "${DOCKER_DANGLING_SUMMARY_FILE}.tmp"
  mv "${DOCKER_DANGLING_SUMMARY_FILE}.tmp" "$DOCKER_DANGLING_SUMMARY_FILE"

  printf '%s\n' "$DOCKER_BUILD_CACHE" > "${DOCKER_BUILD_CACHE_FILE}.tmp"
  mv "${DOCKER_BUILD_CACHE_FILE}.tmp" "$DOCKER_BUILD_CACHE_FILE"

  printf '%s\n' "$DIRECTORY_SIZES" >> "$DIRECTORY_SIZES_FILE"
  inode_usage_line_for_path "$TS" "$TICK" "$STAGE" "/" >> "$INODE_USAGE_FILE"
  printf '\n' >> "$INODE_USAGE_FILE"
  inode_usage_line_for_path "$TS" "$TICK" "$STAGE" "/var" >> "$INODE_USAGE_FILE"
  printf '\n' >> "$INODE_USAGE_FILE"
  inode_usage_line_for_path "$TS" "$TICK" "$STAGE" "/opt/sca" >> "$INODE_USAGE_FILE"
  printf '\n' >> "$INODE_USAGE_FILE"
  printf '%s\n' "$HOST_STATS" >> "$HOST_STATS_FILE"

  log "tick=$TICK stage=$STAGE written"

  TICK=$((TICK + 1))
  sleep 10
done
