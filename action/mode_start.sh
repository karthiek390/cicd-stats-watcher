#!/usr/bin/env bash
set -euo pipefail

RUNTIME_DIR="${GITHUB_ACTION_PATH}/tools/ci-watcher"
WATCHER_SCRIPT="${RUNTIME_DIR}/watcher.sh"
SERVER_SCRIPT="${RUNTIME_DIR}/serve.py"

if [ ! -f "$WATCHER_SCRIPT" ]; then
  echo "[ci-stats-watcher] ERROR: watcher runtime not found at $WATCHER_SCRIPT" >&2
  exit 1
fi

JOB_NAME_RAW="${GITHUB_JOB:-unknown-job}"
JOB_NAME_SAFE=$(printf '%s' "$JOB_NAME_RAW" | tr ' /:' '_' | tr -cd '[:alnum:]_.-')
RUN_ID_VALUE="${GITHUB_RUN_ID:-unknown-run}"
RUN_ATTEMPT_VALUE="${GITHUB_RUN_ATTEMPT:-1}"
RUN_NUMBER_VALUE="${GITHUB_RUN_NUMBER:-}"
REPOSITORY_VALUE="${GITHUB_REPOSITORY:-}"
WORKFLOW_VALUE="${GITHUB_WORKFLOW:-}"
ACTOR_VALUE="${GITHUB_ACTOR:-}"
EVENT_NAME_VALUE="${GITHUB_EVENT_NAME:-}"
REF_VALUE="${GITHUB_REF:-}"
SHA_VALUE="${GITHUB_SHA:-unknown-sha}"
HEAD_SHA_VALUE="${GITHUB_SHA:-unknown-sha}"
WORKSPACE_VALUE="${GITHUB_WORKSPACE:-}"
STARTED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

STATE_DIR="/tmp/ci-stats-watcher/state/run-${RUN_ID_VALUE}/job-${JOB_NAME_SAFE}"
mkdir -p "$STATE_DIR" "$RESOLVED_STATS_DIR"

META_PATH="${RESOLVED_STATS_DIR}/meta.json"
STATE_PATH="${RESOLVED_STATS_DIR}/watcher-runtime-state.json"
STAGE_FILE="${STATE_DIR}/stage.txt"
WATCHER_PID_FILE="${STATE_DIR}/watcher.pid"
SERVER_PID_FILE="${STATE_DIR}/serve.pid"
WATCHER_LOG="${RESOLVED_STATS_DIR}/debug_watcher.log"
SERVER_LOG="${RESOLVED_STATS_DIR}/debug_serve.log"

extract_pr_number() {
  local event_path="${GITHUB_EVENT_PATH:-}"
  if [ -z "$event_path" ] || [ ! -f "$event_path" ]; then
    printf '\n'
    return 0
  fi

  python3 - "$event_path" <<'PY'
import json
import sys
from pathlib import Path

event_path = Path(sys.argv[1])
try:
    payload = json.loads(event_path.read_text(encoding="utf-8"))
except Exception:
    print("")
    raise SystemExit(0)

pr_number = ""
pull_request = payload.get("pull_request")
if isinstance(pull_request, dict):
    value = pull_request.get("number")
    if value is not None:
        pr_number = str(value)

if not pr_number:
    issue = payload.get("issue")
    if isinstance(issue, dict):
        value = issue.get("number")
        if value is not None:
            pr_number = str(value)

print(pr_number)
PY
}

PR_NUMBER="$(extract_pr_number)"
RUN_KEY="${PR_NUMBER:-$RUN_ID_VALUE}"

export JOB_NAME_RAW
export RUN_ID_VALUE
export RUN_ATTEMPT_VALUE
export RUN_NUMBER_VALUE
export REPOSITORY_VALUE
export WORKFLOW_VALUE
export ACTOR_VALUE
export EVENT_NAME_VALUE
export REF_VALUE
export SHA_VALUE
export HEAD_SHA_VALUE
export STARTED_AT
export PR_NUMBER
export RUN_KEY
export META_PATH
export STATE_PATH
export STAGE_FILE
export WATCHER_PID_FILE
export SERVER_PID_FILE
export WATCHER_LOG
export SERVER_LOG

printf '%s\n' "initializing" > "$STAGE_FILE"

write_meta_json() {
  python3 - "$META_PATH" <<'PY'
import json
import os
import sys
from pathlib import Path

meta_path = Path(sys.argv[1])
payload = {
    "pr": os.environ.get("PR_NUMBER", ""),
    "sha": os.environ.get("SHA_VALUE", ""),
    "run_id": os.environ.get("RUN_ID_VALUE", ""),
    "run_attempt": os.environ.get("RUN_ATTEMPT_VALUE", ""),
    "run_number": os.environ.get("RUN_NUMBER_VALUE", ""),
    "repository": os.environ.get("REPOSITORY_VALUE", ""),
    "workflow": os.environ.get("WORKFLOW_VALUE", ""),
    "job": os.environ.get("JOB_NAME_RAW", ""),
    "actor": os.environ.get("ACTOR_VALUE", ""),
    "event_name": os.environ.get("EVENT_NAME_VALUE", ""),
    "ref": os.environ.get("REF_VALUE", ""),
    "started": os.environ.get("STARTED_AT", ""),
    "stats_dir": os.environ.get("RESOLVED_STATS_DIR", ""),
}
meta_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
PY
}

write_state_json() {
  python3 - "$STATE_PATH" <<'PY'
import json
import os
import sys
from pathlib import Path

state_path = Path(sys.argv[1])
payload = {
    "mode": "start",
    "run_key": os.environ.get("RUN_KEY", ""),
    "pr_number": os.environ.get("PR_NUMBER", ""),
    "sha": os.environ.get("SHA_VALUE", ""),
    "head_sha": os.environ.get("HEAD_SHA_VALUE", ""),
    "repository": os.environ.get("REPOSITORY_VALUE", ""),
    "job": os.environ.get("JOB_NAME_RAW", ""),
    "run_id": os.environ.get("RUN_ID_VALUE", ""),
    "stats_dir": os.environ.get("RESOLVED_STATS_DIR", ""),
    "meta_path": os.environ.get("META_PATH", ""),
    "stage_file": os.environ.get("STAGE_FILE", ""),
    "watcher_pid_file": os.environ.get("WATCHER_PID_FILE", ""),
    "server_pid_file": os.environ.get("SERVER_PID_FILE", ""),
    "watcher_log": os.environ.get("WATCHER_LOG", ""),
    "server_log": os.environ.get("SERVER_LOG", ""),
    "run_server": os.environ.get("RUN_SERVER_VALUE", "false"),
    "started": os.environ.get("STARTED_AT", ""),
}
state_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
PY
}

stop_existing_pid() {
  local pid_file="$1"
  if [ ! -f "$pid_file" ]; then
    return 0
  fi

  local pid
  pid=$(cat "$pid_file" 2>/dev/null || true)
  if [ -n "$pid" ]; then
    kill "$pid" 2>/dev/null || true
  fi
  rm -f "$pid_file"
}

start_watcher() {
  stop_existing_pid "$WATCHER_PID_FILE"
  RUNNER_TRACKING_ID="" CI_STATS_STAGE_FILE="$STAGE_FILE" nohup bash "$WATCHER_SCRIPT" "$RUN_KEY" "$SHA_VALUE" "$RESOLVED_STATS_DIR" "$HEAD_SHA_VALUE" \
    >> "$WATCHER_LOG" 2>&1 &
  local pid=$!
  printf '%s\n' "$pid" > "$WATCHER_PID_FILE"
  printf '%s\n' "$pid"
}

start_server() {
  stop_existing_pid "$SERVER_PID_FILE"
  RUNNER_TRACKING_ID="" PYTHONUNBUFFERED=1 nohup python3 "$SERVER_SCRIPT" --port 5999 --pr "$RUN_KEY" --stats-dir "$RESOLVED_STATS_DIR" \
    >> "$SERVER_LOG" 2>&1 &
  local pid=$!
  printf '%s\n' "$pid" > "$SERVER_PID_FILE"
  printf '%s\n' "$pid"
}

write_meta_json
WATCHER_PID="$(start_watcher)"
SERVER_PID=""

case "${RUN_SERVER_VALUE,,}" in
  true|1|yes)
    SERVER_PID="$(start_server)"
    ;;
esac

write_state_json

{
  echo "meta-path=$META_PATH"
  echo "state-path=$STATE_PATH"
  echo "stage-file=$STAGE_FILE"
  echo "watcher-pid=$WATCHER_PID"
  echo "server-pid=$SERVER_PID"
} >> "$GITHUB_OUTPUT"

echo "[ci-stats-watcher] start mode initialized"
echo "[ci-stats-watcher] run_key=$RUN_KEY"
echo "[ci-stats-watcher] watcher_pid=$WATCHER_PID"
if [ -n "$SERVER_PID" ]; then
  echo "[ci-stats-watcher] server_pid=$SERVER_PID"
fi
