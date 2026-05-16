#!/usr/bin/env bash
set -euo pipefail

RUNTIME_DIR="${GITHUB_ACTION_PATH}/tools/ci-watcher"
REPORT_SCRIPT="${RUNTIME_DIR}/generate_report.py"

if [ ! -f "$REPORT_SCRIPT" ]; then
  echo "[cicd-stats-watcher] ERROR: report runtime not found at $REPORT_SCRIPT" >&2
  exit 1
fi

STATE_PATH="${RESOLVED_STATS_DIR}/watcher-runtime-state.json"
META_PATH="${RESOLVED_STATS_DIR}/meta.json"
REPORT_PATH="${RESOLVED_STATS_DIR}/report.html"
RUN_ID_VALUE="${GITHUB_RUN_ID:-unknown-run}"
SHA_VALUE="${GITHUB_SHA:-unknown-sha}"
REPOSITORY_VALUE="${GITHUB_REPOSITORY:-}"
RUN_URL_VALUE="https://github.com/${REPOSITORY_VALUE}/actions/runs/${RUN_ID_VALUE}"
RUN_KEY="${GITHUB_RUN_ID:-unknown-run}"
STAGE_FILE=""
WATCHER_PID_FILE=""
SERVER_PID_FILE=""
FINALIZE_DELAY_SECONDS=12
GENERATED_REPORT="false"

if [ ! -d "$RESOLVED_STATS_DIR" ]; then
  echo "[cicd-stats-watcher] finalize skipped: stats directory not found at $RESOLVED_STATS_DIR"
  echo "finalized=false" >> "$GITHUB_OUTPUT"
  exit 0
fi

if [ ! -f "$META_PATH" ] && [ ! -f "$STATE_PATH" ]; then
  echo "[cicd-stats-watcher] finalize skipped: no runtime state found in $RESOLVED_STATS_DIR"
  echo "finalized=false" >> "$GITHUB_OUTPUT"
  exit 0
fi

load_runtime_state() {
  if [ ! -f "$STATE_PATH" ]; then
    return 0
  fi

  local loaded
  loaded=$(python3 - "$STATE_PATH" <<'PY'
import json
import sys
from pathlib import Path

state_path = Path(sys.argv[1])
try:
    payload = json.loads(state_path.read_text(encoding="utf-8"))
except Exception:
    payload = {}

print(payload.get("run_key", ""))
print(payload.get("stage_file", ""))
print(payload.get("watcher_pid_file", ""))
print(payload.get("server_pid_file", ""))
print(payload.get("sha", ""))
PY
)

  local loaded_run_key
  loaded_run_key=$(printf '%s\n' "$loaded" | sed -n '1p')
  local loaded_stage_file
  loaded_stage_file=$(printf '%s\n' "$loaded" | sed -n '2p')
  local loaded_watcher_pid_file
  loaded_watcher_pid_file=$(printf '%s\n' "$loaded" | sed -n '3p')
  local loaded_server_pid_file
  loaded_server_pid_file=$(printf '%s\n' "$loaded" | sed -n '4p')
  local loaded_sha
  loaded_sha=$(printf '%s\n' "$loaded" | sed -n '5p')

  if [ -n "$loaded_run_key" ]; then
    RUN_KEY="$loaded_run_key"
  fi
  if [ -n "$loaded_stage_file" ]; then
    STAGE_FILE="$loaded_stage_file"
  fi
  if [ -n "$loaded_watcher_pid_file" ]; then
    WATCHER_PID_FILE="$loaded_watcher_pid_file"
  fi
  if [ -n "$loaded_server_pid_file" ]; then
    SERVER_PID_FILE="$loaded_server_pid_file"
  fi
  if [ -n "$loaded_sha" ]; then
    SHA_VALUE="$loaded_sha"
  fi
}

load_meta_pr() {
  if [ ! -f "$META_PATH" ]; then
    printf '%s\n' "$RUN_KEY"
    return 0
  fi

  python3 - "$META_PATH" "$RUN_KEY" <<'PY'
import json
import sys
from pathlib import Path

meta_path = Path(sys.argv[1])
fallback = sys.argv[2]

try:
    payload = json.loads(meta_path.read_text(encoding="utf-8"))
except Exception:
    print(fallback)
    raise SystemExit(0)

value = payload.get("pr")
if value in (None, ""):
    print(fallback)
else:
    print(str(value))
PY
}

stop_pid_file() {
  local pid_file="$1"
  if [ -z "$pid_file" ] || [ ! -f "$pid_file" ]; then
    return 0
  fi

  local pid
  pid=$(cat "$pid_file" 2>/dev/null || true)
  if [ -n "$pid" ]; then
    kill "$pid" 2>/dev/null || true
  fi
  rm -f "$pid_file"
}

load_runtime_state
PR_VALUE="$(load_meta_pr)"

if [ -n "$STAGE_FILE" ]; then
  mkdir -p "$(dirname "$STAGE_FILE")"
  printf '%s\n' "pipeline complete" > "$STAGE_FILE" || true
fi

echo "[cicd-stats-watcher] finalize started"
echo "[cicd-stats-watcher] stats_dir=$RESOLVED_STATS_DIR"

sleep "$FINALIZE_DELAY_SECONDS"

set +e
python3 "$REPORT_SCRIPT" "$RESOLVED_STATS_DIR" "$PR_VALUE" "$SHA_VALUE" "$RUN_ID_VALUE" "$RUN_URL_VALUE"
REPORT_EXIT_CODE=$?
set -e

if [ "$REPORT_EXIT_CODE" -eq 0 ]; then
  GENERATED_REPORT="true"
else
  echo "[cicd-stats-watcher] report generation failed with exit code $REPORT_EXIT_CODE" >&2
fi

stop_pid_file "$WATCHER_PID_FILE"
stop_pid_file "$SERVER_PID_FILE"

if [ -n "$STAGE_FILE" ]; then
  rm -f "$STAGE_FILE" || true
fi

{
  echo "finalized=true"
  echo "generated-report=$GENERATED_REPORT"
} >> "$GITHUB_OUTPUT"

if [ "$REPORT_EXIT_CODE" -ne 0 ]; then
  exit "$REPORT_EXIT_CODE"
fi
