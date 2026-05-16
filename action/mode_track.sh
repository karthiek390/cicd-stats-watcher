#!/usr/bin/env bash
set -euo pipefail

RUNTIME_DIR="${GITHUB_ACTION_PATH}/tools/ci-watcher"
MARK_STEP_SCRIPT="${RUNTIME_DIR}/mark_step.sh"
TRACK_WRAPPER_SCRIPT="${RUNTIME_DIR}/run_tracked_step.sh"

if [ ! -f "$MARK_STEP_SCRIPT" ] || [ ! -f "$TRACK_WRAPPER_SCRIPT" ]; then
  echo "[cicd-stats-watcher] ERROR: tracked-step runtime not found in $RUNTIME_DIR" >&2
  exit 1
fi

STATE_PATH="${RESOLVED_STATS_DIR}/watcher-runtime-state.json"
META_PATH="${RESOLVED_STATS_DIR}/meta.json"
JOB_NAME_RAW="${GITHUB_JOB:-unknown-job}"
JOB_NAME_SAFE=$(printf '%s' "$JOB_NAME_RAW" | tr ' /:' '_' | tr -cd '[:alnum:]_.-')
RUN_ID_VALUE="${GITHUB_RUN_ID:-unknown-run}"
DEFAULT_STAGE_FILE="/tmp/ci-stats-watcher/state/run-${RUN_ID_VALUE}/job-${JOB_NAME_SAFE}/stage.txt"
STAGE_FILE="$DEFAULT_STAGE_FILE"
RUN_KEY="${GITHUB_RUN_ID:-unknown-run}"
HEAD_SHA_VALUE="${GITHUB_SHA:-unknown-sha}"
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
print(payload.get("head_sha", ""))
PY
)

  RUN_KEY=$(printf '%s\n' "$loaded" | sed -n '1p')
  local loaded_stage_file
  loaded_stage_file=$(printf '%s\n' "$loaded" | sed -n '2p')
  local loaded_head_sha
  loaded_head_sha=$(printf '%s\n' "$loaded" | sed -n '3p')

  if [ -n "$loaded_stage_file" ]; then
    STAGE_FILE="$loaded_stage_file"
  fi
  if [ -n "$loaded_head_sha" ]; then
    HEAD_SHA_VALUE="$loaded_head_sha"
  fi
  if [ -z "$RUN_KEY" ]; then
    RUN_KEY="${GITHUB_RUN_ID:-unknown-run}"
  fi
}

mkdir -p "$RESOLVED_STATS_DIR"
load_runtime_state
mkdir -p "$(dirname "$STAGE_FILE")"
printf '%s\n' "$STEP_NAME" > "$STAGE_FILE"

resolve_metrics_from_input() {
  python3 - "$NORMALIZED_METRICS" <<'PY'
import json
import sys

supported = ["storage", "docker", "cpu", "memory", "inode"]
raw = (sys.argv[1] or "").strip()
parts = [item.strip().lower() for item in raw.split(",") if item.strip()]
unknown = [item for item in parts if item not in supported]
if unknown:
    print(json.dumps({"error": f"Unknown metric(s): {', '.join(unknown)}"}))
    raise SystemExit(0)
payload = {name: (name in parts) for name in supported}
print(json.dumps(payload, sort_keys=True))
PY
}

TRACKED_STEP_METRICS="$NORMALIZED_METRICS"
METRICS_JSON="$(resolve_metrics_from_input)"
if printf '%s' "$METRICS_JSON" | grep -q '"error"'; then
  echo "[cicd-stats-watcher] ERROR: invalid metrics input: $METRICS_JSON" >&2
  exit 1
fi

CI_STATS_FORCE_TRACK="true"
export CI_STATS_FORCE_TRACK

echo "[cicd-stats-watcher] tracking step='$STEP_NAME' job='$JOB_ID'"
echo "[cicd-stats-watcher] stats_dir=$RESOLVED_STATS_DIR"
echo "[cicd-stats-watcher] metrics=$TRACKED_STEP_METRICS"

set +e
if [ -n "${INPUT_WORKING_DIRECTORY_VALUE:-}" ]; then
  (
    cd "$INPUT_WORKING_DIRECTORY_VALUE"
    TRACKED_STEP_METRICS="$TRACKED_STEP_METRICS" bash "$TRACK_WRAPPER_SCRIPT" \
      "$JOB_ID" \
      "$STEP_NAME" \
      "$RESOLVED_STATS_DIR" \
      "$RUN_KEY" \
      --manifest "$RESOLVED_MANIFEST_PATH" \
      -- \
      bash -lc "$INPUT_COMMAND_VALUE"
  )
  TRACK_EXIT_CODE=$?
else
  TRACKED_STEP_METRICS="$TRACKED_STEP_METRICS" bash "$TRACK_WRAPPER_SCRIPT" \
    "$JOB_ID" \
    "$STEP_NAME" \
    "$RESOLVED_STATS_DIR" \
    "$RUN_KEY" \
    --manifest "$RESOLVED_MANIFEST_PATH" \
    -- \
    bash -lc "$INPUT_COMMAND_VALUE"
  TRACK_EXIT_CODE=$?
fi
set -e

echo "exit-code=$TRACK_EXIT_CODE" >> "$GITHUB_OUTPUT"

if [ "$TRACK_EXIT_CODE" -ne 0 ]; then
  echo "[cicd-stats-watcher] tracked command failed with exit code $TRACK_EXIT_CODE" >&2
fi

exit "$TRACK_EXIT_CODE"
