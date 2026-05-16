#!/usr/bin/env bash
set -euo pipefail

MODE="${INPUT_MODE:-}"
JOB_ID="${INPUT_JOB_ID:-}"
STEP_NAME="${INPUT_STEP_NAME:-}"
INPUT_STATS_DIR_VALUE="${INPUT_STATS_DIR:-}"
INPUT_METRICS_VALUE="${INPUT_METRICS:-}"
INPUT_COMMAND_VALUE="${INPUT_COMMAND:-}"
INPUT_WORKING_DIRECTORY_VALUE="${INPUT_WORKING_DIRECTORY:-}"
INPUT_MANIFEST_VALUE="${INPUT_MANIFEST_PATH:-}"
RUN_SERVER_VALUE="${INPUT_RUN_SERVER:-false}"

case "$MODE" in
  start|track|finalize)
    ;;
  *)
    echo "[ci-stats-watcher] ERROR: mode must be one of: start, track, finalize" >&2
    exit 1
    ;;
esac

if [ "$MODE" = "track" ] && [ -z "$STEP_NAME" ]; then
  echo "[ci-stats-watcher] ERROR: step-name is required when mode=track" >&2
  exit 1
fi

if [ "$MODE" = "track" ] && [ -z "$JOB_ID" ]; then
  echo "[ci-stats-watcher] ERROR: job-id is required when mode=track" >&2
  exit 1
fi

if [ "$MODE" = "track" ] && [ -z "$INPUT_COMMAND_VALUE" ]; then
  echo "[ci-stats-watcher] ERROR: command is required when mode=track" >&2
  exit 1
fi

DEFAULT_STATS_DIR="/tmp/ci-stats-watcher/run-${GITHUB_RUN_ID:-unknown}/job-${GITHUB_JOB:-unknown}"
RESOLVED_STATS_DIR="${INPUT_STATS_DIR_VALUE:-$DEFAULT_STATS_DIR}"
REPORT_PATH="${RESOLVED_STATS_DIR}/report.html"
ARTIFACT_PATH="${RESOLVED_STATS_DIR}"
NORMALIZED_METRICS="${INPUT_METRICS_VALUE:-storage,docker}"
DEFAULT_MANIFEST="${GITHUB_ACTION_PATH}/tools/ci-watcher/watcher-manifest.yaml"
RESOLVED_MANIFEST_PATH="${INPUT_MANIFEST_VALUE:-$DEFAULT_MANIFEST}"

mkdir -p "$RESOLVED_STATS_DIR"

export MODE
export RESOLVED_STATS_DIR
export REPORT_PATH
export ARTIFACT_PATH
export NORMALIZED_METRICS
export RESOLVED_MANIFEST_PATH
export RUN_SERVER_VALUE
export JOB_ID
export STEP_NAME
export INPUT_COMMAND_VALUE
export INPUT_WORKING_DIRECTORY_VALUE

case "$MODE" in
  start)
    bash "${GITHUB_ACTION_PATH}/action/mode_start.sh"
    ;;
  track)
    bash "${GITHUB_ACTION_PATH}/action/mode_track.sh"
    ;;
  finalize)
    bash "${GITHUB_ACTION_PATH}/action/mode_finalize.sh"
    ;;
esac

{
  echo "mode=$MODE"
  echo "resolved-stats-dir=$RESOLVED_STATS_DIR"
  echo "report-path=$REPORT_PATH"
  echo "artifact-path=$ARTIFACT_PATH"
  echo "metrics=$NORMALIZED_METRICS"
  echo "manifest-path=$RESOLVED_MANIFEST_PATH"
} >> "$GITHUB_OUTPUT"

echo "[ci-stats-watcher] interface ready"
echo "[ci-stats-watcher] mode=$MODE"
echo "[ci-stats-watcher] stats_dir=$RESOLVED_STATS_DIR"
echo "[ci-stats-watcher] metrics=$NORMALIZED_METRICS"
echo "[ci-stats-watcher] manifest_path=$RESOLVED_MANIFEST_PATH"
