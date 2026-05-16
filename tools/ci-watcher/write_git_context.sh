#!/usr/bin/env bash
# write_git_context.sh - write git-context.json for CI stats artifacts.
#
# Usage:
#   write_git_context.sh <output_file> <pr_number> <sha> <base_sha> <head_sha> <event_action> <api_changed> <ui_changed> <workers_changed> [changed_files_file]

set -euo pipefail

OUTPUT_FILE="${1:?output_file required}"
PR_NUMBER="${2:?pr_number required}"
SHA_VALUE="${3:?sha required}"
BASE_SHA="${4:?base_sha required}"
HEAD_SHA="${5:?head_sha required}"
EVENT_ACTION="${6:?event_action required}"
API_CHANGED="${7:?api_changed required}"
UI_CHANGED="${8:?ui_changed required}"
WORKERS_CHANGED="${9:?workers_changed required}"
CHANGED_FILES_FILE="${10:-}"

python3 - "$OUTPUT_FILE" "$PR_NUMBER" "$SHA_VALUE" "$BASE_SHA" "$HEAD_SHA" "$EVENT_ACTION" "$API_CHANGED" "$UI_CHANGED" "$WORKERS_CHANGED" "$CHANGED_FILES_FILE" <<'PY'
import json
import sys
from pathlib import Path

output_file = Path(sys.argv[1])
pr_number = sys.argv[2]
sha_value = sys.argv[3]
base_sha = sys.argv[4]
head_sha = sys.argv[5]
event_action = sys.argv[6]
api_changed = sys.argv[7]
ui_changed = sys.argv[8]
workers_changed = sys.argv[9]
changed_files_file = sys.argv[10]


def parse_bool(raw):
    return str(raw).strip().lower() == "true"


changed_files = []
if changed_files_file:
    path = Path(changed_files_file)
    if path.exists():
        changed_files = [
            line.strip()
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

payload = {
    "pr_number": int(pr_number) if str(pr_number).isdigit() else pr_number,
    "sha": sha_value,
    "base_sha": base_sha,
    "head_sha": head_sha,
    "event_action": event_action,
    "changed_files": changed_files,
    "changed_file_count": len(changed_files),
    "api_changed": parse_bool(api_changed),
    "ui_changed": parse_bool(ui_changed),
    "workers_changed": parse_bool(workers_changed),
}

output_file.parent.mkdir(parents=True, exist_ok=True)
tmp_path = output_file.with_suffix(output_file.suffix + ".tmp")
tmp_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
tmp_path.replace(output_file)
PY
