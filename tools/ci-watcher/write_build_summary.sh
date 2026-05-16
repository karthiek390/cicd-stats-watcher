#!/usr/bin/env bash
# write_build_summary.sh - initialize or update build-summary.json safely.

set -euo pipefail

MODE="${1:?mode required: init|record}"
SUMMARY_FILE="${2:?summary_file required}"
LOCK="${SUMMARY_FILE}.lock"

python3_update() {
  python3 - "$@"
}

if [ "$MODE" = "init" ]; then
  (
    flock -x 200
    python3_update "$SUMMARY_FILE" <<'PY'
import json
import os
import sys

summary_file = sys.argv[1]
services = ["api", "ui", "workers"]
default_rows = [
    {
        "service": service,
        "build_start": None,
        "build_end": None,
        "build_duration_seconds": 0,
        "push_start": None,
        "push_end": None,
        "push_duration_seconds": 0,
        "final_image_size": None,
    }
    for service in services
]

existing = None
if os.path.exists(summary_file) and os.path.getsize(summary_file) > 0:
    try:
        with open(summary_file, "r", encoding="utf-8") as fh:
            payload = json.load(fh)
        if isinstance(payload, list):
            by_service = {
                row.get("service"): row for row in payload
                if isinstance(row, dict) and row.get("service") in services
            }
            existing = []
            for row in default_rows:
                merged = dict(row)
                merged.update(by_service.get(row["service"], {}))
                existing.append(merged)
    except Exception:
        existing = None

payload = existing if existing is not None else default_rows
tmp_path = summary_file + ".tmp"
with open(tmp_path, "w", encoding="utf-8") as fh:
    json.dump(payload, fh, indent=2)
    fh.write("\n")
os.replace(tmp_path, summary_file)
PY
  ) 200>"$LOCK"
  exit 0
fi

if [ "$MODE" = "record" ]; then
  SERVICE="${3:?service required}"
  BUILD_START="${4:-}"
  BUILD_END="${5:-}"
  BUILD_DURATION_SECONDS="${6:-0}"
  PUSH_START="${7:-}"
  PUSH_END="${8:-}"
  PUSH_DURATION_SECONDS="${9:-0}"
  FINAL_IMAGE_SIZE="${10:-}"

  (
    flock -x 200
    python3_update "$SUMMARY_FILE" "$SERVICE" "$BUILD_START" "$BUILD_END" "$BUILD_DURATION_SECONDS" "$PUSH_START" "$PUSH_END" "$PUSH_DURATION_SECONDS" "$FINAL_IMAGE_SIZE" <<'PY'
import json
import os
import sys

summary_file = sys.argv[1]
service = sys.argv[2]
services = ["api", "ui", "workers"]

def normalize_int(raw, default=None):
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except Exception:
        return default

def normalize_ts(raw):
    return raw or None

def default_row(name):
    return {
        "service": name,
        "build_start": None,
        "build_end": None,
        "build_duration_seconds": 0,
        "push_start": None,
        "push_end": None,
        "push_duration_seconds": 0,
        "final_image_size": None,
    }

rows = [default_row(name) for name in services]
if os.path.exists(summary_file) and os.path.getsize(summary_file) > 0:
    try:
        with open(summary_file, "r", encoding="utf-8") as fh:
            payload = json.load(fh)
        if isinstance(payload, list):
            by_service = {
                row.get("service"): row for row in payload
                if isinstance(row, dict) and row.get("service") in services
            }
            rows = []
            for name in services:
                merged = default_row(name)
                merged.update(by_service.get(name, {}))
                rows.append(merged)
    except Exception:
        rows = [default_row(name) for name in services]

if service not in services:
    tmp_path = summary_file + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as fh:
        json.dump(rows, fh, indent=2)
        fh.write("\n")
    os.replace(tmp_path, summary_file)
    sys.exit(0)

updates = {
    "service": service,
    "build_start": normalize_ts(sys.argv[3]),
    "build_end": normalize_ts(sys.argv[4]),
    "build_duration_seconds": normalize_int(sys.argv[5], 0) or 0,
    "push_start": normalize_ts(sys.argv[6]),
    "push_end": normalize_ts(sys.argv[7]),
    "push_duration_seconds": normalize_int(sys.argv[8], 0) or 0,
    "final_image_size": normalize_int(sys.argv[9], None),
}

for row in rows:
    if row["service"] == service:
        row.update(updates)
        break

tmp_path = summary_file + ".tmp"
with open(tmp_path, "w", encoding="utf-8") as fh:
    json.dump(rows, fh, indent=2)
    fh.write("\n")
os.replace(tmp_path, summary_file)
PY
  ) 200>"$LOCK"
  exit 0
fi

echo "Unknown mode: $MODE" >&2
exit 1
