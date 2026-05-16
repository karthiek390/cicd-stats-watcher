#!/usr/bin/env bash
# capture_system_snapshot.sh -- emit a compact JSON snapshot of runner state
#
# Usage:
#   capture_system_snapshot.sh <stats_dir> <pr> <label>
#
# Produces a single JSON object covering filesystem usage, Docker summary,
# object counts, and a few tracked directory sizes.

set -euo pipefail

STATS_DIR="${1:?stats_dir required}"
PR="${2:?pr required}"
LABEL="${3:?label required}"

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

docker_sys_df_json() {
  local out
  out=$(docker system df 2>/dev/null || true)

  if [ -z "$out" ]; then
    echo '{"images_total":"0","images_reclaimable":"0B","containers_total":"0","containers_reclaimable":"0B","volumes_total":"0","volumes_reclaimable":"0B","build_cache_total":"0","build_cache_reclaimable":"0B"}'
    return 0
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
  docker ps -q 2>/dev/null | wc -l | tr -d ' '
}

count_images() {
  docker images -q 2>/dev/null | wc -l | tr -d ' '
}

count_volumes() {
  docker volume ls -q 2>/dev/null | wc -l | tr -d ' '
}

TS=$(date -u +%Y-%m-%dT%H:%M:%SZ)
RUNNER_WORKSPACE_PATH=$(resolve_runner_workspace_dir)
PREVIEW_BASE_DIR_PATH=$(resolve_preview_base_dir)
CURRENT_PR_PREVIEW_DIR_PATH=""
[ -n "$PREVIEW_BASE_DIR_PATH" ] && CURRENT_PR_PREVIEW_DIR_PATH="${PREVIEW_BASE_DIR_PATH}/pr-${PR}"
DOCKER_ROOT_DIR_PATH=$(resolve_docker_root_dir)
VAR_LIB_DOCKER_PATH="/var/lib/docker"
ACTIONS_RUNNER_WORK_PATH=$(resolve_actions_runner_work_dir)

printf '{
  "timestamp": "%s",
  "label": "%s",
  "fs": [%s,%s,%s],
  "docker_df": %s,
  "counts": {
    "container_count": %s,
    "image_count": %s,
    "volume_count": %s
  },
  "directory_sizes": {
    "runner_workspace_path": "%s",
    "runner_workspace_size_kb": %s,
    "preview_base_dir_path": "%s",
    "preview_base_dir_size_kb": %s,
    "current_pr_preview_dir_path": "%s",
    "current_pr_preview_dir_size_kb": %s,
    "docker_root_dir_path": "%s",
    "docker_root_dir_size_kb": %s,
    "var_lib_docker_path": "%s",
    "var_lib_docker_size_kb": %s,
    "actions_runner_work_path": "%s",
    "actions_runner_work_size_kb": %s,
    "ci_stats_dir_path": "%s",
    "ci_stats_dir_size_kb": %s
  }
}\n' \
  "$TS" \
  "$(json_escape "$LABEL")" \
  "$(df_json "/")" \
  "$(df_json "/var")" \
  "$(df_json "/opt/sca")" \
  "$(docker_sys_df_json)" \
  "$(count_containers)" \
  "$(count_images)" \
  "$(count_volumes)" \
  "$(json_escape "$RUNNER_WORKSPACE_PATH")" \
  "$(dir_size_kb "$RUNNER_WORKSPACE_PATH")" \
  "$(json_escape "$PREVIEW_BASE_DIR_PATH")" \
  "$(dir_size_kb "$PREVIEW_BASE_DIR_PATH")" \
  "$(json_escape "$CURRENT_PR_PREVIEW_DIR_PATH")" \
  "$(dir_size_kb "$CURRENT_PR_PREVIEW_DIR_PATH")" \
  "$(json_escape "$DOCKER_ROOT_DIR_PATH")" \
  "$(dir_size_kb "$DOCKER_ROOT_DIR_PATH")" \
  "$(json_escape "$VAR_LIB_DOCKER_PATH")" \
  "$(dir_size_kb "$VAR_LIB_DOCKER_PATH")" \
  "$(json_escape "$ACTIONS_RUNNER_WORK_PATH")" \
  "$(dir_size_kb "$ACTIONS_RUNNER_WORK_PATH")" \
  "$(json_escape "$STATS_DIR")" \
  "$(dir_size_kb "$STATS_DIR")"
