#!/usr/bin/env bash
# run_step.sh - compatibility wrapper around run_tracked_step.sh.
#
# Usage:
#   run_step.sh <job_id> <step_name> <stats_dir> <pr> [--manifest <path>] -- <command> [args...]

set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
exec "${SCRIPT_DIR}/run_tracked_step.sh" "$@"
