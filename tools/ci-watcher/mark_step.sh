#!/usr/bin/env bash
# mark_step.sh — per-step before/after snapshot recorder for CI Stats Phase 1
#
# Usage:
#   mark_step.sh begin <step_name> <job_name> <stats_dir> <pr>
#   mark_step.sh end   <step_name> <job_name> <stats_dir> <pr> [exit_code]
#
# On 'begin': captures a filesystem + docker snapshot into /tmp/step-before-<safe_name>-<pr>.json
# On 'end':   captures end snapshot, computes deltas, appends a record to <stats_dir>/step-summaries.json
#
# All failures are non-fatal (|| true) so a broken metric never kills the pipeline.

set -euo pipefail

ACTION="${1:?action required: begin|end}"
STEP_RAW="${2:?step_name required}"
JOB="${3:?job_name required}"
STATS_DIR="${4:?stats_dir required}"
PR="${5:?pr required}"
EXIT_CODE="${6:-0}"

# Sanitize step name for use in filenames
STEP_SAFE=$(echo "$STEP_RAW" | tr ' :/' '_' | tr -cd '[:alnum:]_-' | cut -c1-64)
BEFORE_FILE="/tmp/step-before-${STEP_SAFE}-${PR}.json"
SUMMARY_FILE="${STATS_DIR}/step-summaries.json"
EVENT_FILE="${STATS_DIR}/step-events.ndjson"
TS_FILE="/tmp/step-ts-${STEP_SAFE}-${PR}"
SUPPORTED_METRICS_JSON='{"storage": true, "docker": true, "cpu": false, "memory": false, "inode": false}'

log() { echo "[mark_step] $*" >&2; }

json_escape() {
  local value="${1:-}"
  value="${value//\\/\\\\}"
  value="${value//\"/\\\"}"
  value="${value//$'\n'/ }"
  value="${value//$'\r'/ }"
  printf '%s' "$value"
}

append_event() {
  local event_type="$1"
  local ts="$2"
  local status="$3"
  local exit_code="$4"
  local duration="$5"
  local command_executed="${STEP_COMMAND_DISPLAY:-}"
  local event_record
  event_record=$(printf '{"event":"%s","ts":"%s","job_name":"%s","step_name":"%s","status":"%s","exit_code":%s,"duration_seconds":%s,"pr":"%s","command_executed":"%s"}' \
    "$event_type" \
    "$ts" \
    "$(json_escape "$JOB")" \
    "$(json_escape "$STEP_RAW")" \
    "$status" \
    "$exit_code" \
    "$duration" \
    "$(json_escape "$PR")" \
    "$(json_escape "$command_executed")")

  local lock_file="/tmp/step-events-lock-${PR}"
  (
    flock -x 200
    printf '%s\n' "$event_record" >> "$EVENT_FILE"
  ) 200>"$lock_file"
}

metric_enabled() {
  local metric_name="$1"
  python3 - "$metric_name" <<'PY'
import json
import os
import sys

metric_name = sys.argv[1]
raw = os.environ.get("CI_STATS_STEP_METRICS_JSON") or os.environ.get("SUPPORTED_METRICS_JSON", "")
if not raw:
    raw = '{"storage": true, "docker": true, "cpu": false, "memory": false, "inode": false}'

try:
    payload = json.loads(raw)
except Exception:
    payload = {"storage": True, "docker": True, "cpu": False, "memory": False, "inode": False}

print("true" if bool(payload.get(metric_name, False)) else "false")
PY
}

# ── Snapshot helpers ──────────────────────────────────────────────────────────

snapshot_fs() {
  if [ "$(metric_enabled storage)" != "true" ]; then
    echo "[]"
    return 0
  fi
  local result="["
  local first=1
  for mount in "/" "/var" "/opt/sca"; do
    local out
    if out=$(df -P "$mount" 2>/dev/null); then
      local pct used avail
      pct=$(echo "$out" | awk 'NR==2 {gsub(/%/,""); print $5}')
      used=$(echo "$out" | awk 'NR==2 {print $3}')
      avail=$(echo "$out" | awk 'NR==2 {print $4}')
      [ "$first" -eq 1 ] || result+=","
      result+="{\"mount\":\"${mount}\",\"pct\":${pct},\"used_kb\":${used},\"avail_kb\":${avail}}"
      first=0
    fi
  done
  result+="]"
  echo "$result"
}

snapshot_docker_df() {
  if [ "$(metric_enabled docker)" != "true" ]; then
    echo '{}'
    return 0
  fi
  local out
  out=$(docker system df 2>/dev/null || echo "")
  if [ -z "$out" ]; then
    echo '{"images_total":"0","images_reclaimable":"0B","containers_total":"0","containers_reclaimable":"0B","volumes_total":"0","volumes_reclaimable":"0B","build_cache_total":"0","build_cache_reclaimable":"0B"}'
    return
  fi
  echo "$out" | awk '
    BEGIN { printf "{" }
    /^Images/ {
      gsub(/[[:space:]]+/, " "); split($0,a," ")
      printf "\"images_total\":\"%s\",\"images_reclaimable\":\"%s\"", a[3], a[5]
    }
    /^Containers/ {
      gsub(/[[:space:]]+/, " "); split($0,a," ")
      printf ",\"containers_total\":\"%s\",\"containers_reclaimable\":\"%s\"", a[3], a[5]
    }
    /^Local Volumes/ {
      gsub(/[[:space:]]+/, " "); split($0,a," ")
      printf ",\"volumes_total\":\"%s\",\"volumes_reclaimable\":\"%s\"", a[4], a[6]
    }
    /^Build Cache/ {
      gsub(/[[:space:]]+/, " "); split($0,a," ")
      printf ",\"build_cache_total\":\"%s\",\"build_cache_reclaimable\":\"%s\"", a[4], a[6]
    }
    END { printf "}" }
  '
}

count_containers() {
  if [ "$(metric_enabled docker)" != "true" ]; then
    echo 0
    return 0
  fi
  docker ps -q 2>/dev/null | wc -l | tr -d ' '
}

count_images() {
  if [ "$(metric_enabled docker)" != "true" ]; then
    echo 0
    return 0
  fi
  docker images -q 2>/dev/null | wc -l | tr -d ' '
}

count_volumes() {
  if [ "$(metric_enabled docker)" != "true" ]; then
    echo 0
    return 0
  fi
  docker volume ls -q 2>/dev/null | wc -l | tr -d ' '
}

snapshot_inode() {
  if [ "$(metric_enabled inode)" != "true" ]; then
    echo "[]"
    return 0
  fi
  local result="["
  local first=1
  for mount in "/" "/var" "/opt/sca"; do
    local out
    if out=$(df -Pi "$mount" 2>/dev/null); then
      local total used free pct
      total=$(echo "$out" | awk 'NR==2 {print $2}')
      used=$(echo "$out" | awk 'NR==2 {print $3}')
      free=$(echo "$out" | awk 'NR==2 {print $4}')
      pct=$(echo "$out" | awk 'NR==2 {gsub(/%/,""); print $5}')
      [ "$first" -eq 1 ] || result+=","
      result+="{\"mount\":\"${mount}\",\"inode_total\":${total:-0},\"inode_used\":${used:-0},\"inode_free\":${free:-0},\"inode_pct\":${pct:-0}}"
      first=0
    fi
  done
  result+="]"
  echo "$result"
}

snapshot_host_stats() {
  local include_cpu include_memory
  include_cpu=$(metric_enabled cpu)
  include_memory=$(metric_enabled memory)
  if [ "$include_cpu" != "true" ] && [ "$include_memory" != "true" ]; then
    echo '{}'
    return 0
  fi

  local cpu_cores=0
  local load_1="0"
  local load_5="0"
  local load_15="0"
  local mem_total=0
  local mem_available=0
  local memory_used=0
  local swap_total=0
  local swap_free=0
  local swap_used=0

  if [ "$include_cpu" = "true" ]; then
    cpu_cores=$(grep -c '^processor' /proc/cpuinfo 2>/dev/null || echo 0)
    load_1=$(awk '{print $1; exit}' /proc/loadavg 2>/dev/null || echo 0)
    load_5=$(awk '{print $2; exit}' /proc/loadavg 2>/dev/null || echo 0)
    load_15=$(awk '{print $3; exit}' /proc/loadavg 2>/dev/null || echo 0)
  fi

  if [ "$include_memory" = "true" ]; then
    mem_total=$(awk '/^MemTotal:/ {print $2; exit}' /proc/meminfo 2>/dev/null || echo 0)
    mem_available=$(awk '/^MemAvailable:/ {print $2; exit}' /proc/meminfo 2>/dev/null || echo 0)
    swap_total=$(awk '/^SwapTotal:/ {print $2; exit}' /proc/meminfo 2>/dev/null || echo 0)
    swap_free=$(awk '/^SwapFree:/ {print $2; exit}' /proc/meminfo 2>/dev/null || echo 0)
    if [ "${mem_total:-0}" -ge "${mem_available:-0}" ] 2>/dev/null; then
      memory_used=$((mem_total - mem_available))
    fi
    if [ "${swap_total:-0}" -ge "${swap_free:-0}" ] 2>/dev/null; then
      swap_used=$((swap_total - swap_free))
    fi
  fi

  printf '{"cpu_cores":%s,"load_average":{"1m":%s,"5m":%s,"15m":%s},"memory_total":%s,"memory_used":%s,"memory_available":%s,"swap_used":%s}' \
    "${cpu_cores:-0}" "${load_1:-0}" "${load_5:-0}" "${load_15:-0}" \
    "${mem_total:-0}" "${memory_used:-0}" "${mem_available:-0}" "${swap_used:-0}"
}

take_snapshot() {
  local ts
  ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  local fs docker_df containers images volumes inode host_stats
  fs=$(snapshot_fs)
  docker_df=$(snapshot_docker_df)
  containers=$(count_containers)
  images=$(count_images)
  volumes=$(count_volumes)
  inode=$(snapshot_inode)
  host_stats=$(snapshot_host_stats)
  printf '{"ts":"%s","fs":%s,"docker_df":%s,"container_count":%s,"image_count":%s,"volume_count":%s,"inode":%s,"host_stats":%s}' \
    "$ts" "$fs" "$docker_df" "$containers" "$images" "$volumes" "$inode" "$host_stats"
}

# ── delta helpers ─────────────────────────────────────────────────────────────

# Extract pct for a mount from a snapshot JSON (simple grep/awk approach, no jq needed)
get_pct() {
  local snap="$1" mount="$2"
  echo "$snap" | grep -o "\"mount\":\"${mount}\"[^}]*" | grep -o '"pct":[0-9]*' | cut -d: -f2 || true
}

get_field() {
  local snap="$1" field="$2"
  echo "$snap" | grep -o "\"${field}\":[0-9]*" | head -1 | cut -d: -f2 || true
}

json_section_or_default() {
  local snap="$1"
  local key="$2"
  local default_value="$3"
  python3 - "$snap" "$key" "$default_value" <<'PY'
import json
import sys

snap = sys.argv[1]
key = sys.argv[2]
default_raw = sys.argv[3]

try:
    payload = json.loads(snap)
except Exception:
    print(default_raw)
    raise SystemExit(0)

if key not in payload:
    print(default_raw)
    raise SystemExit(0)

print(json.dumps(payload[key], separators=(",", ":")))
PY
}

# ── begin ─────────────────────────────────────────────────────────────────────

if [ "$ACTION" = "begin" ]; then
  log "BEGIN step='${STEP_RAW}' job='${JOB}'"
  mkdir -p "$STATS_DIR"

  SNAP=$(take_snapshot)
  START_TS=$(echo "$SNAP" | grep -o '"ts":"[^"]*"' | head -1 | cut -d'"' -f4)
  echo "$SNAP" > "$BEFORE_FILE"
  date +%s > "$TS_FILE"
  append_event "begin" "$START_TS" "running" 0 0

  log "Snapshot saved to $BEFORE_FILE"
  exit 0
fi

# ── end ───────────────────────────────────────────────────────────────────────

if [ "$ACTION" = "end" ]; then
  log "END step='${STEP_RAW}' job='${JOB}' exit_code=${EXIT_CODE}"
  mkdir -p "$STATS_DIR"

  END_SNAP=$(take_snapshot)
  END_TS=$(echo "$END_SNAP" | grep -o '"ts":"[^"]*"' | head -1 | cut -d'"' -f4)

  # Load before snapshot (fall back to empty if begin wasn't called)
  if [ -f "$BEFORE_FILE" ]; then
    BEF_SNAP=$(cat "$BEFORE_FILE")
    START_TS=$(echo "$BEF_SNAP" | grep -o '"ts":"[^"]*"' | head -1 | cut -d'"' -f4)
    rm -f "$BEFORE_FILE"
  else
    log "WARNING: no before snapshot found, using end snapshot for both"
    BEF_SNAP="$END_SNAP"
    START_TS="$END_TS"
  fi

  # Duration
  if [ -f "$TS_FILE" ]; then
    START_EPOCH=$(cat "$TS_FILE")
    rm -f "$TS_FILE"
    END_EPOCH=$(date +%s)
    DURATION=$((END_EPOCH - START_EPOCH))
  else
    DURATION=0
  fi

  # Compute fs deltas (pct change for each mount)
  ROOT_BEFORE=$(get_pct "$BEF_SNAP" "/")
  ROOT_AFTER=$(get_pct "$END_SNAP" "/")
  VAR_BEFORE=$(get_pct "$BEF_SNAP" "/var")
  VAR_AFTER=$(get_pct "$END_SNAP" "/var")
  OPT_BEFORE=$(get_pct "$BEF_SNAP" "/opt/sca")
  OPT_AFTER=$(get_pct "$END_SNAP" "/opt/sca")

  ROOT_DELTA=$(( ${ROOT_AFTER:-0} - ${ROOT_BEFORE:-0} ))
  VAR_DELTA=$(( ${VAR_AFTER:-0} - ${VAR_BEFORE:-0} ))
  OPT_DELTA=$(( ${OPT_AFTER:-0} - ${OPT_BEFORE:-0} ))

  # Docker object count deltas
  C_BEFORE=$(get_field "$BEF_SNAP" "container_count")
  C_AFTER=$(get_field "$END_SNAP" "container_count")
  I_BEFORE=$(get_field "$BEF_SNAP" "image_count")
  I_AFTER=$(get_field "$END_SNAP" "image_count")
  V_BEFORE=$(get_field "$BEF_SNAP" "volume_count")
  V_AFTER=$(get_field "$END_SNAP" "volume_count")

  C_DELTA=$(( ${C_AFTER:-0} - ${C_BEFORE:-0} ))
  I_DELTA=$(( ${I_AFTER:-0} - ${I_BEFORE:-0} ))
  V_DELTA=$(( ${V_AFTER:-0} - ${V_BEFORE:-0} ))

  INODE_BEFORE=$(json_section_or_default "$BEF_SNAP" "inode" "[]")
  INODE_AFTER=$(json_section_or_default "$END_SNAP" "inode" "[]")
  HOST_STATS_BEFORE=$(json_section_or_default "$BEF_SNAP" "host_stats" "{}")
  HOST_STATS_AFTER=$(json_section_or_default "$END_SNAP" "host_stats" "{}")

  STATUS_STR="success"
  [ "$EXIT_CODE" != "0" ] && STATUS_STR="failed"

  # Build JSON record
  RECORD=$(printf '{
  "step_name": "%s",
  "job_name": "%s",
  "command_executed": "%s",
  "start_time": "%s",
  "end_time": "%s",
  "duration_seconds": %d,
  "status": "%s",
  "exit_code": %s,
  "fs_before": %s,
  "fs_after": %s,
  "docker_df_before": %s,
  "docker_df_after": %s,
  "container_count_before": %s,
  "container_count_after": %s,
  "image_count_before": %s,
  "image_count_after": %s,
  "volume_count_before": %s,
  "volume_count_after": %s,
  "inode_before": %s,
  "inode_after": %s,
  "host_stats_before": %s,
  "host_stats_after": %s,
  "metrics_enabled": %s,
  "delta_summary": {
    "root_pct_delta": %d,
    "var_pct_delta": %d,
    "opt_sca_pct_delta": %d,
    "container_delta": %d,
    "image_delta": %d,
    "volume_delta": %d
  }
}' \
    "$(json_escape "$STEP_RAW")" "$(json_escape "$JOB")" "$(json_escape "${STEP_COMMAND_DISPLAY:-}")" "$START_TS" "$END_TS" "$DURATION" "$STATUS_STR" "$EXIT_CODE" \
    "$(echo "$BEF_SNAP" | grep -o '"fs":\[[^]]*\]' | sed 's/^"fs"://')" \
    "$(echo "$END_SNAP" | grep -o '"fs":\[[^]]*\]' | sed 's/^"fs"://')" \
    "$(echo "$BEF_SNAP" | grep -o '"docker_df":{[^}]*}' | sed 's/^"docker_df"://')" \
    "$(echo "$END_SNAP" | grep -o '"docker_df":{[^}]*}' | sed 's/^"docker_df"://')" \
    "${C_BEFORE:-0}" "${C_AFTER:-0}" \
    "${I_BEFORE:-0}" "${I_AFTER:-0}" \
    "${V_BEFORE:-0}" "${V_AFTER:-0}" \
    "$INODE_BEFORE" "$INODE_AFTER" \
    "$HOST_STATS_BEFORE" "$HOST_STATS_AFTER" \
    "${CI_STATS_STEP_METRICS_JSON:-$SUPPORTED_METRICS_JSON}" \
    "$ROOT_DELTA" "$VAR_DELTA" "$OPT_DELTA" \
    "$C_DELTA" "$I_DELTA" "$V_DELTA"
  )

  # Append to step-summaries.json (JSON array, safe atomic append)
  LOCK_FILE="/tmp/step-summaries-lock-${PR}"
  (
    flock -x 200
    if [ -f "$SUMMARY_FILE" ] && [ -s "$SUMMARY_FILE" ]; then
      # File exists and non-empty: replace trailing ] with ,<record>]
      TMP=$(mktemp)
      sed '$ s/]$//' "$SUMMARY_FILE" > "$TMP"
      printf ',\n%s\n]' "$RECORD" >> "$TMP"
      mv "$TMP" "$SUMMARY_FILE"
    else
      printf '[\n%s\n]' "$RECORD" > "$SUMMARY_FILE"
    fi
  ) 200>"$LOCK_FILE"
  append_event "end" "$END_TS" "$STATUS_STR" "$EXIT_CODE" "$DURATION"

  log "Appended step record to $SUMMARY_FILE (duration=${DURATION}s, /var Δ=${VAR_DELTA}%)"
  exit 0
fi

echo "[mark_step] ERROR: unknown action '$ACTION'. Use begin or end." >&2
exit 1
