#!/usr/bin/env bash
# run_tracked_step.sh - generic manifest-driven wrapper for tracked CI steps.
#
# Usage:
#   run_tracked_step.sh <job_id> <step_name> <stats_dir> <pr> [--manifest <path>] -- <command> [args...]
#
# Behavior:
# - If the manifest says the step is tracked, wrap the command with mark_step.sh begin/end.
# - If the manifest says the step is untracked, run the command directly.
# - If manifest lookup or tracking hooks fail, log and fall back without failing the command itself.

set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
DEFAULT_MANIFEST="${SCRIPT_DIR}/watcher-manifest.yaml"
MARK_STEP="${SCRIPT_DIR}/mark_step.sh"
SUPPORTED_METRICS="storage,docker,cpu,memory,inode"

JOB_ID="${1:?job_id required}"
STEP_NAME="${2:?step_name required}"
STATS_DIR="${3:?stats_dir required}"
PR="${4:?pr required}"
shift 4

MANIFEST_PATH="$DEFAULT_MANIFEST"
if [ "${1:-}" = "--manifest" ]; then
  MANIFEST_PATH="${2:?manifest path required after --manifest}"
  shift 2
fi

if [ "${1:-}" != "--" ]; then
  echo "[run_tracked_step] ERROR: expected -- before command" >&2
  exit 2
fi
shift

if [ "$#" -eq 0 ]; then
  echo "[run_tracked_step] ERROR: command required after --" >&2
  exit 2
fi

log() { echo "[run_tracked_step] $*" >&2; }
STEP_COMMAND_DISPLAY="$*"
export STEP_COMMAND_DISPLAY

metrics_json_from_csv() {
  local raw="${1:-}"
  python3 - "$raw" <<'PY'
import json
import sys

supported = {"storage", "docker", "cpu", "memory", "inode"}
raw = (sys.argv[1] or "").strip()

if not raw:
    print("")
    raise SystemExit(0)

parts = [item.strip().lower() for item in raw.split(",") if item.strip()]
unknown = [item for item in parts if item not in supported]
if unknown:
    print(json.dumps({"error": f"Unknown metric(s): {', '.join(unknown)}"}))
    raise SystemExit(0)

payload = {name: (name in parts) for name in sorted(supported)}
print(json.dumps(payload, sort_keys=True))
PY
}

PYTHON_BIN=""
for candidate in python3 python; do
  if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c "print('ok')" >/dev/null 2>&1; then
    PYTHON_BIN="$candidate"
    break
  fi
done

normalize_python_path() {
  local raw_path="$1"
  if command -v cygpath >/dev/null 2>&1; then
    cygpath -w "$raw_path"
  else
    printf '%s\n' "$raw_path"
  fi
}

is_tracked_step() {
  local manifest="$1"
  local python_manifest
  if [ -z "$PYTHON_BIN" ]; then
    return 1
  fi
  python_manifest=$(normalize_python_path "$manifest")
  "$PYTHON_BIN" - "$python_manifest" "$JOB_ID" "$STEP_NAME" <<'PY'
import sys
from pathlib import Path

try:
    import yaml
except Exception:
    print("false")
    raise SystemExit(0)

manifest_path = Path(sys.argv[1])
job_id = sys.argv[2]
step_name = sys.argv[3]

if not manifest_path.exists():
    print("false")
    raise SystemExit(0)

try:
    data = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
except Exception:
    print("false")
    raise SystemExit(0)

if not isinstance(data, dict):
    print("false")
    raise SystemExit(0)

defaults = data.get("defaults", {})
default_job_tracking = True
default_step_tracking = False
if isinstance(defaults, dict):
    default_job_tracking = bool(defaults.get("job_tracking", True))
    default_step_tracking = bool(defaults.get("step_tracking", False))

jobs = data.get("jobs", [])
if not isinstance(jobs, list):
    print("false")
    raise SystemExit(0)

for job in jobs:
    if not isinstance(job, dict):
        continue
    if job.get("job_id") != job_id:
        continue
    job_track = job.get("track", default_job_tracking)
    if not job_track:
        print("false")
        raise SystemExit(0)

    steps = job.get("steps", [])
    if not isinstance(steps, list):
        print("false")
        raise SystemExit(0)

    for step in steps:
        if not isinstance(step, dict):
            continue
        if step.get("name") == step_name:
            print("true" if bool(step.get("track", default_step_tracking)) else "false")
            raise SystemExit(0)

    print("false")
    raise SystemExit(0)

print("false")
PY
}

resolve_metrics_json() {
  local manifest="$1"
  local input_metrics_csv="${2:-}"
  local python_manifest
  if [ -n "$input_metrics_csv" ]; then
    metrics_json_from_csv "$input_metrics_csv"
    return 0
  fi

  if [ -z "$PYTHON_BIN" ]; then
    printf '%s\n' '{"storage": true, "docker": true, "cpu": false, "memory": false, "inode": false}'
    return 0
  fi

  python_manifest=$(normalize_python_path "$manifest")
  "$PYTHON_BIN" - "$python_manifest" "$JOB_ID" "$STEP_NAME" <<'PY'
import json
import sys
from pathlib import Path

supported = ["storage", "docker", "cpu", "memory", "inode"]
defaults = {name: False for name in supported}
defaults["storage"] = True
defaults["docker"] = True

try:
    import yaml
except Exception:
    print(json.dumps(defaults, sort_keys=True))
    raise SystemExit(0)

manifest_path = Path(sys.argv[1])
job_id = sys.argv[2]
step_name = sys.argv[3]

if not manifest_path.exists():
    print(json.dumps(defaults, sort_keys=True))
    raise SystemExit(0)

try:
    data = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
except Exception:
    print(json.dumps(defaults, sort_keys=True))
    raise SystemExit(0)

if not isinstance(data, dict):
    print(json.dumps(defaults, sort_keys=True))
    raise SystemExit(0)

global_metrics = defaults.copy()
manifest_defaults = data.get("defaults", {})
if isinstance(manifest_defaults, dict):
    manifest_metrics = manifest_defaults.get("metrics", {})
    if isinstance(manifest_metrics, dict):
        for name in supported:
            if name in manifest_metrics:
                global_metrics[name] = bool(manifest_metrics.get(name))

jobs = data.get("jobs", [])
if not isinstance(jobs, list):
    print(json.dumps(global_metrics, sort_keys=True))
    raise SystemExit(0)

selected = global_metrics.copy()
for job in jobs:
    if not isinstance(job, dict) or job.get("job_id") != job_id:
        continue

    job_metrics = job.get("metrics", {})
    if isinstance(job_metrics, dict):
        for name in supported:
            if name in job_metrics:
                selected[name] = bool(job_metrics.get(name))

    steps = job.get("steps", [])
    if not isinstance(steps, list):
        print(json.dumps(selected, sort_keys=True))
        raise SystemExit(0)

    for step in steps:
        if not isinstance(step, dict) or step.get("name") != step_name:
            continue
        step_metrics = step.get("metrics", {})
        if isinstance(step_metrics, dict):
            for name in supported:
                if name in step_metrics:
                    selected[name] = bool(step_metrics.get(name))
        print(json.dumps(selected, sort_keys=True))
        raise SystemExit(0)

    print(json.dumps(selected, sort_keys=True))
    raise SystemExit(0)

print(json.dumps(global_metrics, sort_keys=True))
PY
}

TRACK_STEP="false"
if [ "${CI_STATS_FORCE_TRACK:-false}" = "true" ]; then
  TRACK_STEP="true"
else
  if TRACK_STEP=$(is_tracked_step "$MANIFEST_PATH" 2>/dev/null); then
    :
  else
    TRACK_STEP="false"
  fi
fi

TRACKED_STEP_METRICS="${TRACKED_STEP_METRICS:-}"
METRICS_JSON=""
if [ "$TRACK_STEP" = "true" ]; then
  METRICS_JSON=$(resolve_metrics_json "$MANIFEST_PATH" "$TRACKED_STEP_METRICS" 2>/dev/null || printf '%s\n' '{"storage": true, "docker": true, "cpu": false, "memory": false, "inode": false}')
  export CI_STATS_STEP_METRICS_JSON="$METRICS_JSON"
fi

if [ "$TRACK_STEP" = "true" ]; then
  log "Tracking enabled for job='${JOB_ID}' step='${STEP_NAME}'"
  log "Metrics: ${METRICS_JSON}"
  bash "$MARK_STEP" begin "$STEP_NAME" "$JOB_ID" "$STATS_DIR" "$PR" || log "begin hook failed; continuing"
else
  log "Tracking disabled for job='${JOB_ID}' step='${STEP_NAME}'"
fi

set +e
"$@"
COMMAND_EXIT=$?
set -e

if [ "$TRACK_STEP" = "true" ]; then
  bash "$MARK_STEP" end "$STEP_NAME" "$JOB_ID" "$STATS_DIR" "$PR" "$COMMAND_EXIT" || log "end hook failed; continuing"
fi

exit "$COMMAND_EXIT"
