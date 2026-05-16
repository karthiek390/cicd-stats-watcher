#!/usr/bin/env bash
# write_summary.sh — safe incremental JSON writer for CI Stats Phase 2
#
# Usage:
#   write_summary.sh <summary_file> <key> <value_json>
#
# Writes or merges key:value into a top-level JSON object file.
# Creates the file if it doesn't exist. Thread-safe via flock.
# value_json must be a valid JSON value (string, number, array, object, true/false/null).
#
# Examples:
#   write_summary.sh /path/to/cleanup-summary.json  "cleanup_start_time"  '"2026-03-12T10:00:00Z"'
#   write_summary.sh /path/to/preview-up-summary.json  "compose_pull_duration_seconds"  '18'
#   write_summary.sh /path/to/preview-up-summary.json  "services_started"  '["api","ui","postgres"]'
#
# For APPENDING to an array field, use append mode:
#   write_summary.sh <file> --append <key> <item_json>
#   e.g. write_summary.sh /path/to/file.json --append "health_waits" '{"service":"api","waited_seconds":8}'

set -euo pipefail

SUMMARY_FILE="${1:?summary_file required}"
LOCK="${SUMMARY_FILE}.lock"

# ── Append mode ───────────────────────────────────────────────────────────────
if [ "${2:-}" = "--append" ]; then
  KEY="${3:?key required for --append}"
  ITEM="${4:?item_json required for --append}"

  (
    flock -x 200
    if [ -f "$SUMMARY_FILE" ] && [ -s "$SUMMARY_FILE" ]; then
      EXISTING=$(cat "$SUMMARY_FILE")
      # Check if key already exists as an array
      if echo "$EXISTING" | python3 -c "
import sys, json
d = json.load(sys.stdin)
k = sys.argv[1]
item = json.loads(sys.argv[2])
d.setdefault(k, []).append(item)
print(json.dumps(d, indent=2))
" "$KEY" "$ITEM" > "${SUMMARY_FILE}.tmp" 2>/dev/null; then
        mv "${SUMMARY_FILE}.tmp" "$SUMMARY_FILE"
      fi
    else
      # File doesn't exist — create with single-item array
      python3 -c "
import sys, json
k = sys.argv[1]
item = json.loads(sys.argv[2])
print(json.dumps({k: [item]}, indent=2))
" "$KEY" "$ITEM" > "$SUMMARY_FILE"
    fi
  ) 200>"$LOCK"
  exit 0
fi

# ── Set mode (default) ────────────────────────────────────────────────────────
KEY="${2:?key required}"
VALUE_JSON="${3:?value_json required}"

(
  flock -x 200
  if [ -f "$SUMMARY_FILE" ] && [ -s "$SUMMARY_FILE" ]; then
    EXISTING=$(cat "$SUMMARY_FILE")
    python3 -c "
import sys, json
d = json.load(sys.stdin)
k = sys.argv[1]
v = json.loads(sys.argv[2])
d[k] = v
print(json.dumps(d, indent=2))
" "$KEY" "$VALUE_JSON" <<< "$EXISTING" > "${SUMMARY_FILE}.tmp" && mv "${SUMMARY_FILE}.tmp" "$SUMMARY_FILE"
  else
    python3 -c "
import sys, json
k = sys.argv[1]
v = json.loads(sys.argv[2])
print(json.dumps({k: v}, indent=2))
" "$KEY" "$VALUE_JSON" > "$SUMMARY_FILE"
  fi
) 200>"$LOCK"
