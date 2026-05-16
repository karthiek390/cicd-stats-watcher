#!/usr/bin/env python3
import json
import math
import shutil
import sys
from pathlib import Path
from datetime import datetime, timezone
from html import escape

# ── format_kb: Python port of formatBytes from ui/src/services/utils.js ──────
# Input: size in KB (integer). Output: human-readable string e.g. "24.8 GB".
def format_kb(kb, decimals=2):
    try:
        kb = int(kb)
    except (TypeError, ValueError):
        return "—"
    if kb == 0:
        return "0 KB"
    # Convert KB → bytes first so we can use the same size labels
    byte_val = kb * 1024
    k = 1024
    sizes = ["Bytes", "KB", "MB", "GB", "TB"]
    i = int(math.floor(math.log(byte_val) / math.log(k)))
    i = min(i, len(sizes) - 1)
    val = round(byte_val / math.pow(k, i), decimals)
    return f"{val} {sizes[i]}"


def format_count(value):
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return "—"


def format_bytes(num_bytes, decimals=2):
    try:
        num_bytes = int(num_bytes)
    except (TypeError, ValueError):
        return "—"
    if num_bytes == 0:
        return "0 Bytes"
    k = 1024
    sizes = ["Bytes", "KB", "MB", "GB", "TB"]
    i = int(math.floor(math.log(num_bytes) / math.log(k)))
    i = min(i, len(sizes) - 1)
    val = round(num_bytes / math.pow(k, i), decimals)
    return f"{val} {sizes[i]}"

def safe_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def safe_str(value, default=""):
    if value is None:
        return default
    return str(value)


def load_ndjson_safe(path):
    rows = []
    if not path.exists():
        return rows
    for raw in path.read_text(encoding="utf-8").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            obj = json.loads(raw)
            if isinstance(obj, dict):
                rows.append(obj)
        except json.JSONDecodeError:
            pass
    return rows


def load_json_safe(path, expected_type=dict):
    default = [] if expected_type is list else {}
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, expected_type):
                return data
        except Exception:
            pass
    return default


def write_json_atomic(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    tmp_path.replace(path)


def safe_bool(value):
    return bool(value)


def artifact_versions():
    return {
        "artifact_version": "v1",
        "schema_version": "v1",
    }


def artifact_presence_map(artifact_files):
    return {
        name: safe_bool(resolve_artifact_path(name, category).exists())
        for name, category in artifact_files
    }


def get_raw_path(filename):
    return RAW_DIR / filename


def get_derived_path(filename):
    return DERIVED_DIR / filename


def resolve_artifact_path(filename, category=None):
    candidates = []
    root_path = STATS_DIR / filename

    if category == "raw":
        candidates.extend([get_raw_path(filename), root_path])
    elif category == "derived":
        candidates.extend([get_derived_path(filename), root_path])
    elif category == "root":
        candidates.append(root_path)
    else:
        candidates.extend([get_raw_path(filename), get_derived_path(filename), root_path])

    for candidate in candidates:
        if candidate.exists():
            return candidate

    return root_path


def list_raw_files():
    return [
        name
        for name in RAW_FILE_NAMES
        if resolve_artifact_path(name, "raw").exists()
    ]


def list_derived_files():
    return [
        name
        for name in DERIVED_FILE_NAMES
        if resolve_artifact_path(name, "derived").exists()
    ]


def mirror_artifact(root_path, structured_path):
    if not root_path.exists():
        return
    structured_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(root_path, structured_path)


def sync_structured_artifacts():
    for name in RAW_FILE_NAMES:
        mirror_artifact(STATS_DIR / name, get_raw_path(name))

    for name in DERIVED_FILE_NAMES:
        mirror_artifact(STATS_DIR / name, get_derived_path(name))


def compute_peak_pct(ticks, mount):
    peak = 0
    for tick in ticks:
        for fs_row in tick.get("fs", []):
            if fs_row.get("mount") == mount:
                peak = max(peak, safe_int(fs_row.get("pct"), 0))
    return peak


def extract_fs_cleanup_delta(cleanup_data):
    mounts = ["/", "/var", "/opt/sca"]
    deltas = {mount: 0 for mount in mounts}
    if not isinstance(cleanup_data, dict):
        return deltas

    before_rows = cleanup_data.get("fs_before")
    after_rows = cleanup_data.get("fs_after")
    if not isinstance(before_rows, list) or not isinstance(after_rows, list):
        return deltas

    before_by_mount = {
        safe_str(row.get("mount")): safe_int(row.get("pct"), 0)
        for row in before_rows
        if isinstance(row, dict)
    }
    after_by_mount = {
        safe_str(row.get("mount")): safe_int(row.get("pct"), 0)
        for row in after_rows
        if isinstance(row, dict)
    }

    for mount in mounts:
        deltas[mount] = after_by_mount.get(mount, 0) - before_by_mount.get(mount, 0)
    return deltas


def summarize_cleanup_effectiveness(cleanup_data):
    summary = {
        "fs_delta_after_cleanup": extract_fs_cleanup_delta(cleanup_data),
        "docker_images_reclaimed": 0,
        "docker_cache_reclaimed": "0B",
        "volumes_reclaimed": 0,
        "containers_removed": 0,
        "preview_dirs_deleted": 0,
    }

    if not isinstance(cleanup_data, dict):
        return summary

    docker_before = cleanup_data.get("docker_df_before")
    docker_after = cleanup_data.get("docker_df_after")
    if not isinstance(docker_before, dict):
        docker_before = {}
    if not isinstance(docker_after, dict):
        docker_after = {}

    images_removed = cleanup_data.get("images_removed_count")
    if images_removed is None:
        images_removed = max(
            0,
            safe_int(docker_before.get("images_total"), 0) - safe_int(docker_after.get("images_total"), 0),
        )
    summary["docker_images_reclaimed"] = safe_int(images_removed, 0)

    build_cache_reclaimed = safe_str(cleanup_data.get("build_cache_reclaimed"), "").strip()
    summary["docker_cache_reclaimed"] = build_cache_reclaimed or "0B"

    volumes_removed = cleanup_data.get("volumes_removed_count")
    if volumes_removed is None:
        volumes_removed = max(
            0,
            safe_int(docker_before.get("volumes_total"), 0) - safe_int(docker_after.get("volumes_total"), 0),
        )
    summary["volumes_reclaimed"] = safe_int(volumes_removed, 0)

    containers_removed = cleanup_data.get("containers_removed_count")
    if containers_removed is None:
        containers_removed = max(
            0,
            safe_int(docker_before.get("containers_total"), 0) - safe_int(docker_after.get("containers_total"), 0),
        )
    summary["containers_removed"] = safe_int(containers_removed, 0)

    summary["preview_dirs_deleted"] = safe_int(cleanup_data.get("preview_dirs_removed"), 0)
    return summary


def parse_size_to_bytes(value):
    raw = safe_str(value, "").strip().upper().replace(" ", "")
    if not raw or raw == "0":
        return 0

    suffixes = {
        "B": 1,
        "KB": 1024,
        "MB": 1024 ** 2,
        "GB": 1024 ** 3,
        "TB": 1024 ** 4,
    }
    for suffix, multiplier in suffixes.items():
        if raw.endswith(suffix):
            number = raw[: -len(suffix)]
            try:
                return int(float(number) * multiplier)
            except (TypeError, ValueError):
                return 0
    return 0


def count_xenium_pr_images(images):
    if not isinstance(images, list):
        return 0

    count = 0
    for image in images:
        if not isinstance(image, dict):
            continue
        repository = safe_str(image.get("repository"), "").lower()
        tag = safe_str(image.get("tag"), "").lower()
        if "xenium" not in repository:
            continue
        if not (tag.startswith("pr-") or tag.startswith("build-")):
            continue
        if image.get("belongs_to_current_pr") or image.get("belongs_to_current_sha"):
            continue
        count += 1
    return count


def final_var_pct(cleanup_data, latest_fs):
    if isinstance(cleanup_data, dict):
        after_rows = cleanup_data.get("fs_after")
        if isinstance(after_rows, list):
            for row in after_rows:
                if isinstance(row, dict) and row.get("mount") == "/var":
                    return safe_int(row.get("pct"), 0)

    if isinstance(latest_fs, list):
        for row in latest_fs:
            if isinstance(row, dict) and row.get("mount") == "/var":
                return safe_int(row.get("pct"), 0)
    return 0


def build_warning(code, active=False, message="", severity="warning"):
    return {
        "code": code,
        "severity": severity,
        "active": bool(active),
        "message": safe_str(message, "") if active else "",
    }


warning_thresholds = {
    "var_usage_pct": 80,
    "old_pr_images_count": 30,
    "max_container_count": 20,
    "cache_bytes": 1024 ** 3,
}


def summarize_warnings(
    run_summary_data,
    cleanup_data,
    cleanup_effectiveness,
    docker_images,
    docker_build_cache,
    directory_sizes_latest,
    fail_diag_data,
    latest_fs,
):
    warnings = []

    peak_var_pct = safe_int(run_summary_data.get("peak_var_pct"), 0) if isinstance(run_summary_data, dict) else 0
    final_var_usage = final_var_pct(cleanup_data, latest_fs)
    old_pr_image_count = count_xenium_pr_images(docker_images)
    max_container_count = (
        safe_int(run_summary_data.get("max_container_count"), 0) if isinstance(run_summary_data, dict) else 0
    )

    cleanup_cache_bytes = parse_size_to_bytes(
        cleanup_effectiveness.get("docker_cache_reclaimed") if isinstance(cleanup_effectiveness, dict) else "0B"
    )
    observed_cache_bytes = parse_size_to_bytes(
        docker_build_cache.get("cache_reclaimable") if isinstance(docker_build_cache, dict) else "0B"
    )

    preview_failure = safe_str(fail_diag_data.get("failure_stage"), "") == "preview-up" if isinstance(fail_diag_data, dict) else False
    preview_dir_size_kb = (
        safe_int(directory_sizes_latest.get("current_pr_preview_dir_size"), 0)
        if isinstance(directory_sizes_latest, dict)
        else 0
    )
    preview_cleanup_incomplete = bool(preview_failure and preview_dir_size_kb > 0)

    warnings.append(
        build_warning(
            "var_usage_exceeded_threshold",
            peak_var_pct >= warning_thresholds["var_usage_pct"],
            f"/var usage peaked at {peak_var_pct}%, exceeding the warning threshold of "
            f"{warning_thresholds['var_usage_pct']}%.",
        )
    )
    warnings.append(
        build_warning(
            "cleanup_left_high_usage",
            final_var_usage >= warning_thresholds["var_usage_pct"],
            f"Final /var usage remained at {final_var_usage}% after cleanup, still at or above "
            f"the warning threshold of {warning_thresholds['var_usage_pct']}%.",
        )
    )
    warnings.append(
        build_warning(
            "too_many_old_pr_images",
            old_pr_image_count > warning_thresholds["old_pr_images_count"],
            f"Found {old_pr_image_count} older Xenium PR/build images, above the threshold of "
            f"{warning_thresholds['old_pr_images_count']}.",
        )
    )
    warnings.append(
        build_warning(
            "container_count_unexpectedly_high",
            max_container_count > warning_thresholds["max_container_count"],
            f"Container count peaked at {max_container_count}, above the threshold of "
            f"{warning_thresholds['max_container_count']}.",
        )
    )
    warnings.append(
        build_warning(
            "preview_cleanup_incomplete",
            preview_cleanup_incomplete,
            f"Preview-up failed and the current PR preview directory still measured "
            f"{format_kb(preview_dir_size_kb)} after cleanup.",
        )
    )
    warnings.append(
        build_warning(
            "cache_growth_unusually_high",
            cleanup_cache_bytes > warning_thresholds["cache_bytes"]
            or observed_cache_bytes > warning_thresholds["cache_bytes"],
            f"Docker build cache exceeded the 1 GB threshold "
            f"(reclaimable now: {safe_str(docker_build_cache.get('cache_reclaimable'), '0B')}, "
            f"reclaimed during cleanup: {safe_str(cleanup_effectiveness.get('docker_cache_reclaimed'), '0B')}).",
        )
    )

    return {"warnings": warnings}


def _step_extreme_payload(step, metric, delta_value):
    if not step or not metric:
        return {
            "step_name": None,
            "job_name": None,
            "metric": None,
            "delta_value": None,
        }
    return {
        "step_name": step.get("step_name"),
        "job_name": step.get("job_name"),
        "metric": metric,
        "delta_value": delta_value,
    }


def summarize_step_extremes(step_summaries):
    metric_priority = [
        ("var_pct_delta", "/var"),
        ("opt_sca_pct_delta", "/opt/sca"),
        ("root_pct_delta", "/"),
        ("container_delta", "containers"),
        ("image_delta", "images"),
        ("volume_delta", "volumes"),
    ]

    longest_step = {
        "step_name": None,
        "job_name": None,
        "duration_seconds": None,
    }

    for step in step_summaries:
        duration = safe_int(step.get("duration_seconds"), 0)
        if longest_step["duration_seconds"] is None or duration > longest_step["duration_seconds"]:
            longest_step = {
                "step_name": step.get("step_name"),
                "job_name": step.get("job_name"),
                "duration_seconds": duration,
            }

    largest_growth = _step_extreme_payload(None, None, None)
    largest_cleanup = _step_extreme_payload(None, None, None)

    for delta_key, metric_label in metric_priority:
        positive_candidates = []
        negative_candidates = []
        for step in step_summaries:
            delta = safe_int(step.get("delta_summary", {}).get(delta_key), 0)
            if delta > 0:
                positive_candidates.append((delta, step))
            elif delta < 0:
                negative_candidates.append((delta, step))

        if positive_candidates and largest_growth["metric"] is None:
            delta_value, step = max(
                positive_candidates,
                key=lambda item: (
                    item[0],
                    safe_int(item[1].get("duration_seconds"), 0),
                    str(item[1].get("job_name", "")),
                    str(item[1].get("step_name", "")),
                ),
            )
            largest_growth = _step_extreme_payload(step, metric_label, delta_value)

        if negative_candidates and largest_cleanup["metric"] is None:
            delta_value, step = min(
                negative_candidates,
                key=lambda item: (
                    item[0],
                    -safe_int(item[1].get("duration_seconds"), 0),
                    str(item[1].get("job_name", "")),
                    str(item[1].get("step_name", "")),
                ),
            )
            largest_cleanup = _step_extreme_payload(step, metric_label, delta_value)

        if largest_growth["metric"] is not None and largest_cleanup["metric"] is not None:
            break

    return longest_step, largest_growth, largest_cleanup


def derive_test_summary(step_summaries):
    summary = {
        "env_up_start": None,
        "env_up_end": None,
        "postgres_wait_duration": 0,
        "api_wait_duration": 0,
        "ui_wait_duration": 0,
        "playwright_start": None,
        "playwright_end": None,
        "playwright_duration": 0,
        "teardown_start": None,
        "teardown_end": None,
        "teardown_duration": 0,
    }
    if not isinstance(step_summaries, list):
        return summary

    tracked_steps = {
        "Bring up E2E environment": ("env_up_start", "env_up_end", None),
        "Wait for Postgres to accept connections": (None, None, "postgres_wait_duration"),
        "Wait for API to be healthy": (None, None, "api_wait_duration"),
        "Wait for UI to respond": (None, None, "ui_wait_duration"),
        "Run E2E login setup tests only (temporary CI gate)": (
            "playwright_start",
            "playwright_end",
            "playwright_duration",
        ),
        "Tear down E2E environment": ("teardown_start", "teardown_end", "teardown_duration"),
    }

    for step in step_summaries:
        if not isinstance(step, dict):
            continue
        if safe_str(step.get("job_name")) != "test":
            continue
        mapping = tracked_steps.get(safe_str(step.get("step_name")))
        if not mapping:
            continue
        start_key, end_key, duration_key = mapping
        if start_key:
            summary[start_key] = step.get("start_time")
        if end_key:
            summary[end_key] = step.get("end_time")
        if duration_key:
            summary[duration_key] = safe_int(step.get("duration_seconds"), 0)

    return summary


def derive_preview_step_breakdown(step_summaries, preview_up_data):
    summary = {
        "sync_duration": 0,
        "pull_duration": 0,
        "up_duration": 0,
        "api_health_wait": 0,
        "ui_health_wait": 0,
        "signet_health_wait": 0,
        "rhythm_health_wait": 0,
        "seed_load_duration": 0,
    }

    if isinstance(preview_up_data, dict):
        summary["pull_duration"] = safe_int(preview_up_data.get("compose_pull_duration_seconds"), 0)
        summary["up_duration"] = safe_int(preview_up_data.get("compose_up_duration_seconds"), 0)
        summary["seed_load_duration"] = safe_int(preview_up_data.get("seed_load_duration_seconds"), 0)

        waits = preview_up_data.get("health_waits")
        if isinstance(waits, list):
            wait_key_map = {
                "api": "api_health_wait",
                "ui": "ui_health_wait",
                "signet": "signet_health_wait",
                "rhythm": "rhythm_health_wait",
            }
            for wait in waits:
                if not isinstance(wait, dict):
                    continue
                service = safe_str(wait.get("service")).strip().lower()
                key = wait_key_map.get(service)
                if key:
                    summary[key] = safe_int(wait.get("waited_seconds"), 0)

    if isinstance(step_summaries, list):
        for step in step_summaries:
            if not isinstance(step, dict):
                continue
            if safe_str(step.get("job_name")) != "preview-up":
                continue
            if safe_str(step.get("step_name")) == "Sync code into isolated preview dir":
                summary["sync_duration"] = safe_int(step.get("duration_seconds"), 0)
                break

    return summary


if len(sys.argv) < 6:
    print("Usage: generate_report.py <stats_dir> <pr> <sha> <run_id> <run_url>", file=sys.stderr)
    sys.exit(1)

STATS_DIR = Path(sys.argv[1])
PR = sys.argv[2]
SHA = sys.argv[3]
RUN_ID = sys.argv[4]
RUN_URL = sys.argv[5]

META_FILE = STATS_DIR / "meta.json"
REPORT_FILE = STATS_DIR / "report.html"
RUN_SUMMARY_FILE = STATS_DIR / "run-summary.json"
CLEANUP_EFFECTIVENESS_FILE = STATS_DIR / "cleanup-effectiveness.json"
WARNINGS_FILE = STATS_DIR / "warnings.json"
LIVE_SCHEMA_FILE = STATS_DIR / "live-schema.json"
RAW_DIR = STATS_DIR / "raw"
DERIVED_DIR = STATS_DIR / "derived"

RAW_FILE_NAMES = [
    "timeline.ndjson",
    "snapshot.json",
    "step-events.ndjson",
    "directory-sizes.ndjson",
    "inode-usage.ndjson",
    "host-stats.ndjson",
]

DERIVED_FILE_NAMES = [
    "step-summaries.json",
    "docker-images.json",
    "docker-volumes.json",
    "docker-containers.json",
    "docker-build-cache.json",
    "docker-dangling-summary.json",
    "git-context.json",
    "cleanup-summary.json",
    "run-summary.json",
    "warnings.json",
    "cleanup-effectiveness.json",
    "tag-pr-summary.json",
    "preview-up-summary.json",
    "failure-diagnostics-summary.json",
    "build-summary.json",
    "test-summary.json",
    "preview-step-breakdown.json",
]

TIMELINE_FILE = resolve_artifact_path("timeline.ndjson", "raw")
STEP_SUMMARIES_FILE = resolve_artifact_path("step-summaries.json", "derived")
SNAPSHOT_FILE = resolve_artifact_path("snapshot.json", "raw")
DOCKER_IMAGES_FILE = resolve_artifact_path("docker-images.json", "derived")
DOCKER_CONTAINERS_FILE = resolve_artifact_path("docker-containers.json", "derived")
DOCKER_VOLUMES_FILE = resolve_artifact_path("docker-volumes.json", "derived")
DOCKER_DANGLING_FILE = resolve_artifact_path("docker-dangling-summary.json", "derived")
DOCKER_BUILD_CACHE_FILE = resolve_artifact_path("docker-build-cache.json", "derived")

# ── Phase 4 files ────────────────────────────────────────────
DIRECTORY_SIZES_FILE = resolve_artifact_path("directory-sizes.ndjson", "raw")
INODE_USAGE_FILE     = resolve_artifact_path("inode-usage.ndjson", "raw")
HOST_STATS_FILE      = resolve_artifact_path("host-stats.ndjson", "raw")

# ── Phase 2 files ─────────────────────────────────────────────────────────────
TAG_PR_FILE      = resolve_artifact_path("tag-pr-summary.json", "derived")
PREVIEW_UP_FILE  = resolve_artifact_path("preview-up-summary.json", "derived")
CLEANUP_FILE     = resolve_artifact_path("cleanup-summary.json", "derived")
FAIL_DIAG_FILE   = resolve_artifact_path("failure-diagnostics-summary.json", "derived")
BUILD_SUMMARY_FILE = resolve_artifact_path("build-summary.json", "derived")
TEST_SUMMARY_FILE = resolve_artifact_path("test-summary.json", "derived")
PREVIEW_STEP_BREAKDOWN_FILE = resolve_artifact_path("preview-step-breakdown.json", "derived")
GIT_CONTEXT_FILE = resolve_artifact_path("git-context.json", "derived")

ARTIFACT_FILES = [
    ("report.html", "root"),
    ("live-schema.json", "root"),
    ("timeline.ndjson", "raw"),
    ("snapshot.json", "raw"),
    ("meta.json", "root"),
    ("step-summaries.json", "derived"),
    ("docker-images.json", "derived"),
    ("docker-volumes.json", "derived"),
    ("docker-containers.json", "derived"),
    ("docker-build-cache.json", "derived"),
    ("git-context.json", "derived"),
    ("cleanup-summary.json", "derived"),
    ("run-summary.json", "derived"),
    ("warnings.json", "derived"),
    ("cleanup-effectiveness.json", "derived"),
]

ENDED_AT = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
LIVE_SCHEMA_SOURCE = Path(__file__).with_name("live-schema.json")
if LIVE_SCHEMA_SOURCE.exists():
    try:
        live_schema_payload = json.loads(LIVE_SCHEMA_SOURCE.read_text(encoding="utf-8"))
        if isinstance(live_schema_payload, dict):
            write_json_atomic(LIVE_SCHEMA_FILE, live_schema_payload)
    except Exception:
        pass

# ── Load timeline ────────────────────────────────────────────────────────────
ticks = load_ndjson_safe(TIMELINE_FILE)

# ── Load meta ────────────────────────────────────────────────────────────────
meta = {}
if META_FILE.exists():
    try:
        meta = json.loads(META_FILE.read_text(encoding="utf-8"))
    except Exception:
        meta = {}

# ── Load step summaries (Phase 1) ────────────────────────────────────────────
step_summaries = []
if STEP_SUMMARIES_FILE.exists():
    try:
        step_summaries = json.loads(STEP_SUMMARIES_FILE.read_text(encoding="utf-8"))
        if not isinstance(step_summaries, list):
            step_summaries = []
    except Exception:
        step_summaries = []

derived_test_summary = derive_test_summary(step_summaries)
if any(value not in (None, 0) for value in derived_test_summary.values()):
    write_json_atomic(TEST_SUMMARY_FILE, derived_test_summary)

docker_image_inventory = {}
docker_inventory_rows = []
if DOCKER_IMAGES_FILE.exists():
    try:
        docker_image_inventory = json.loads(DOCKER_IMAGES_FILE.read_text(encoding="utf-8"))
        docker_inventory_rows = docker_image_inventory.get("images", [])
        if not isinstance(docker_inventory_rows, list):
            docker_inventory_rows = []
    except Exception:
        docker_image_inventory = {}
        docker_inventory_rows = []

docker_container_inventory = {}
docker_container_rows = []
if DOCKER_CONTAINERS_FILE.exists():
    try:
        docker_container_inventory = json.loads(DOCKER_CONTAINERS_FILE.read_text(encoding="utf-8"))
        docker_container_rows = docker_container_inventory.get("containers", [])
        if not isinstance(docker_container_rows, list):
            docker_container_rows = []
    except Exception:
        docker_container_inventory = {}
        docker_container_rows = []

docker_volume_inventory = {}
docker_volume_rows = []
if DOCKER_VOLUMES_FILE.exists():
    try:
        docker_volume_inventory = json.loads(DOCKER_VOLUMES_FILE.read_text(encoding="utf-8"))
        docker_volume_rows = docker_volume_inventory.get("volumes", [])
        if not isinstance(docker_volume_rows, list):
            docker_volume_rows = []
    except Exception:
        docker_volume_inventory = {}
        docker_volume_rows = []

docker_dangling_summary = {}
if DOCKER_DANGLING_FILE.exists():
    try:
        docker_dangling_summary = json.loads(DOCKER_DANGLING_FILE.read_text(encoding="utf-8"))
        if not isinstance(docker_dangling_summary, dict):
            docker_dangling_summary = {}
    except Exception:
        docker_dangling_summary = {}

docker_build_cache = {}
docker_build_cache_entries = []
if DOCKER_BUILD_CACHE_FILE.exists():
    try:
        docker_build_cache = json.loads(DOCKER_BUILD_CACHE_FILE.read_text(encoding="utf-8"))
        if not isinstance(docker_build_cache, dict):
            docker_build_cache = {}
        docker_build_cache_entries = docker_build_cache.get("cache_entries", [])
        if not isinstance(docker_build_cache_entries, list):
            docker_build_cache_entries = []
    except Exception:
        docker_build_cache = {}
        docker_build_cache_entries = []

# ── Load Phase 4 NDJSON files ────────────────────────────────────────────────
def _latest_inode_usage_rows(rows):
    """Return the most recent tick worth rendering, preferring a complete 3-row tick."""
    if not rows:
        return []

    grouped = {}
    for row in rows:
        try:
            tick = int(row.get("tick"))
        except (TypeError, ValueError):
            continue
        grouped.setdefault(tick, []).append(row)

    if not grouped:
        return []

    preferred_tick = None
    for tick in sorted(grouped.keys(), reverse=True):
        tick_rows = grouped[tick]
        if len(tick_rows) >= 3:
            preferred_tick = tick
            break

    if preferred_tick is None:
        preferred_tick = max(grouped.keys())

    path_order = {"/": 0, "/var": 1, "/opt/sca": 2}
    return sorted(
        grouped.get(preferred_tick, []),
        key=lambda row: (
            path_order.get(str(row.get("path", "")), 999),
            str(row.get("mount", "")),
            str(row.get("filesystem", "")),
        ),
    )

directory_sizes_rows_data = load_ndjson_safe(DIRECTORY_SIZES_FILE)
directory_sizes_latest    = directory_sizes_rows_data[-1] if directory_sizes_rows_data else {}

inode_usage_rows_data = load_ndjson_safe(INODE_USAGE_FILE)
inode_usage_latest = _latest_inode_usage_rows(inode_usage_rows_data)

host_stats_rows_data = load_ndjson_safe(HOST_STATS_FILE)
host_stats_latest    = host_stats_rows_data[-1] if host_stats_rows_data else {}
inode_usage_note = (
    f"Showing last complete tick ({len(inode_usage_latest)} row(s))."
    if inode_usage_latest
    else "No complete inode usage tick available for this run."
)

# ── Load Phase 2 summaries ────────────────────────────────────────────────────
def _load_json(path, expected_type=dict):
    return load_json_safe(path, expected_type)


def shorten_sha(value, length=7):
    value = str(value or "").strip()
    if not value:
        return "—"
    return value[:length]


def format_bool_flag(value):
    return "✅" if bool(value) else "❌"

tag_pr_data     = _load_json(TAG_PR_FILE, dict)
preview_up_data = _load_json(PREVIEW_UP_FILE, dict)
cleanup_data    = _load_json(CLEANUP_FILE, dict)
fail_diag_data  = _load_json(FAIL_DIAG_FILE, dict)
build_summary_data = _load_json(BUILD_SUMMARY_FILE, list)
test_summary_data = _load_json(TEST_SUMMARY_FILE, dict)
git_context_data = _load_json(GIT_CONTEXT_FILE, dict)
snapshot_data = _load_json(SNAPSHOT_FILE, dict)

derived_preview_step_breakdown = derive_preview_step_breakdown(step_summaries, preview_up_data)
if any(int(value or 0) > 0 for value in derived_preview_step_breakdown.values()):
    write_json_atomic(PREVIEW_STEP_BREAKDOWN_FILE, derived_preview_step_breakdown)
preview_step_breakdown_data = _load_json(PREVIEW_STEP_BREAKDOWN_FILE, dict)

# ── Duration ─────────────────────────────────────────────────────────────────
started = meta.get("started", "unknown")
try:
    t0 = datetime.fromisoformat(started.replace("Z", "+00:00"))
    t1 = datetime.fromisoformat(ENDED_AT.replace("Z", "+00:00"))
    duration_s = int((t1 - t0).total_seconds())
    duration_str = f"{duration_s // 60}m {duration_s % 60}s"
except Exception:
    duration_str = "unknown"

# ── Latest tick data ─────────────────────────────────────────────────────────
latest = ticks[-1] if ticks else {}
if not latest and snapshot_data:
    latest = snapshot_data
latest_fs = latest.get("fs", [])
latest_df = latest.get("docker_df", {})
latest_containers = latest.get("containers", [])
latest_images = latest.get("images", [])
if docker_inventory_rows:
    latest_images = [
        {
            "repo": img.get("repository", ""),
            "tag": img.get("tag", ""),
            "size": img.get("size", ""),
        }
        for img in docker_inventory_rows
    ]

# ── Peak metrics from timeline (Phase 1 Summary Card) ────────────────────────
peak_root = compute_peak_pct(ticks, "/")
peak_var = compute_peak_pct(ticks, "/var")
peak_opt = compute_peak_pct(ticks, "/opt/sca")
max_containers = max((len(t.get("containers", [])) for t in ticks), default=0)

if not ticks and snapshot_data:
    peak_root = peak_root or compute_peak_pct([snapshot_data], "/")
    peak_var = peak_var or compute_peak_pct([snapshot_data], "/var")
    peak_opt = peak_opt or compute_peak_pct([snapshot_data], "/opt/sca")
    max_containers = max_containers or len(snapshot_data.get("containers", []))

# longest step and biggest growth step from step_summaries
longest_step_name = "—"
longest_step_dur = 0
biggest_growth_step = "—"
biggest_growth_val = 0
biggest_cleanup_step = "—"
biggest_cleanup_val = 0

for s in step_summaries:
    dur = s.get("duration_seconds", 0)
    if dur > longest_step_dur:
        longest_step_dur = dur
        longest_step_name = s.get("step_name", "—")
    delta = s.get("delta_summary", {})
    var_delta = delta.get("var_pct_delta", 0)
    if var_delta > biggest_growth_val:
        biggest_growth_val = var_delta
        biggest_growth_step = s.get("step_name", "—")
    if var_delta < biggest_cleanup_val:
        biggest_cleanup_val = var_delta
        biggest_cleanup_step = s.get("step_name", "—")

# ── HTML helpers ─────────────────────────────────────────────────────────────

max_image_count = len(docker_inventory_rows)
if not max_image_count:
    max_image_count = len(latest.get("images", []))
if not max_image_count:
    max_image_count = safe_int(latest_df.get("images_total"), 0)

max_volume_count = len(docker_volume_rows)
if not max_volume_count:
    max_volume_count = safe_int(latest_df.get("volumes_total"), 0)

longest_step, largest_step_growth, largest_cleanup_reduction = summarize_step_extremes(step_summaries)

run_summary = {
    "peak_root_pct": peak_root,
    "peak_var_pct": peak_var,
    "peak_opt_sca_pct": peak_opt,
    "max_container_count": max_containers,
    "max_image_count": max_image_count,
    "max_volume_count": max_volume_count,
    "longest_step": longest_step,
    "largest_step_growth": largest_step_growth,
    "largest_cleanup_reduction": largest_cleanup_reduction,
}
RUN_SUMMARY_FILE.write_text(json.dumps(run_summary, indent=2), encoding="utf-8")
mirror_artifact(RUN_SUMMARY_FILE, get_derived_path("run-summary.json"))
run_summary_data = _load_json(RUN_SUMMARY_FILE, dict)

cleanup_effectiveness = summarize_cleanup_effectiveness(cleanup_data)
CLEANUP_EFFECTIVENESS_FILE.write_text(json.dumps(cleanup_effectiveness, indent=2), encoding="utf-8")
mirror_artifact(CLEANUP_EFFECTIVENESS_FILE, get_derived_path("cleanup-effectiveness.json"))

warnings_data = summarize_warnings(
    run_summary_data,
    cleanup_data,
    cleanup_effectiveness,
    docker_inventory_rows,
    docker_build_cache,
    directory_sizes_latest,
    fail_diag_data,
    latest_fs,
)
WARNINGS_FILE.write_text(json.dumps(warnings_data, indent=2), encoding="utf-8")
mirror_artifact(WARNINGS_FILE, get_derived_path("warnings.json"))
warnings_render_data = _load_json(WARNINGS_FILE, dict)


def fs_rows(fs):
    rows = []
    for f in fs:
        pct = f.get("pct", 0)
        used_kb = f.get("used_kb", 0)
        avail_kb = f.get("avail_kb", 0)
        size_kb = used_kb + avail_kb
        row_style = ""
        if pct >= 80:
            row_style = "background:#ffe0e0;"
        elif pct >= 65:
            row_style = "background:#fff3cd;"
        # Render a compact usage bar via inline style
        bar_color = "#e74c3c" if pct >= 80 else ("#e67e22" if pct >= 65 else "#27ae60")
        pct_bar = (
            f"<div style='display:flex;align-items:center;gap:8px'>"
            f"<div style='flex:1;background:#e9ecef;border-radius:4px;height:8px;min-width:80px'>"
            f"<div style='width:{pct}%;background:{bar_color};border-radius:4px;height:8px'></div>"
            f"</div>"
            f"<b style='min-width:38px'>{escape(str(pct))}%</b>"
            f"</div>"
        )
        rows.append(
            f"<tr style='{row_style}'>"
            f"<td>{escape(str(f.get('mount', '')))}</td>"
            f"<td>{pct_bar}</td>"
            f"<td>{escape(format_kb(used_kb))}</td>"
            f"<td>{escape(format_kb(avail_kb))}</td>"
            f"<td style='color:#888;font-size:12px'>{escape(format_kb(size_kb))}</td>"
            f"</tr>"
        )
    return "".join(rows) or "<tr><td colspan='5'>No filesystem data</td></tr>"


def container_rows(containers):
    rows = []
    for c in containers:
        rows.append(
            f"<tr>"
            f"<td>{escape(str(c.get('name', '')))}</td>"
            f"<td>{escape(str(c.get('cpu_pct', '')))}</td>"
            f"<td>{escape(str(c.get('mem_usage', '')))}</td>"
            f"<td>{escape(str(c.get('status', '')))}</td>"
            f"</tr>"
        )
    return "".join(rows) or "<tr><td colspan='4'>No container data</td></tr>"


def inventory_container_rows(containers, limit=30):
    if not containers:
        return "<tr><td colspan='8' style='color:#888;font-style:italic'>No Docker container inventory collected for this run.</td></tr>"

    def sort_key(container):
        preview = 1 if container.get("belongs_to_preview_stack") else 0
        test = 1 if container.get("belongs_to_test_stack") else 0
        return (
            -preview,
            -test,
            str(container.get("container_name", "")),
            str(container.get("container_id", "")),
        )

    rows = []
    for c in sorted(containers, key=sort_key)[:limit]:
        rows.append(
            f"<tr>"
            f"<td style='font-size:12px;word-break:break-all'>{escape(str(c.get('container_name', '')))}</td>"
            f"<td style='font-size:12px;word-break:break-all'>{escape(str(c.get('container_id', '')))}</td>"
            f"<td style='font-size:12px;word-break:break-all'>{escape(str(c.get('image', '')))}</td>"
            f"<td>{escape(str(c.get('status', '')))}</td>"
            f"<td>{escape(str(c.get('size', '') or '—'))}</td>"
            f"<td style='white-space:nowrap'>{escape(str(c.get('created_at', '')))}</td>"
            f"<td>{'Yes' if c.get('belongs_to_preview_stack') else 'No'}</td>"
            f"<td>{'Yes' if c.get('belongs_to_test_stack') else 'No'}</td>"
            f"</tr>"
        )
    return "".join(rows)


def inventory_volume_rows(volumes, limit=30):
    if not volumes:
        return "<tr><td colspan='5' style='color:#888;font-style:italic'>No Docker volume inventory collected for this run.</td></tr>"

    def format_labels(labels):
        if not isinstance(labels, dict) or not labels:
            return "—"
        items = sorted(labels.items())
        compact = ", ".join(f"{key}={value}" for key, value in items[:3])
        if len(items) > 3:
            compact += f", +{len(items) - 3} more"
        return compact

    def sort_key(volume):
        preview = 1 if volume.get("belongs_to_preview_stack") else 0
        return (
            -preview,
            str(volume.get("volume_name", "")),
        )

    rows = []
    for volume in sorted(volumes, key=sort_key)[:limit]:
        rows.append(
            f"<tr>"
            f"<td style='font-size:12px;word-break:break-all'>{escape(str(volume.get('volume_name', '')))}</td>"
            f"<td>{escape(str(volume.get('driver', '')))}</td>"
            f"<td style='font-size:12px;word-break:break-all'>{escape(str(volume.get('mountpoint', '')))}</td>"
            f"<td>{'Yes' if volume.get('belongs_to_preview_stack') else 'No'}</td>"
            f"<td style='font-size:12px;word-break:break-all'>{escape(format_labels(volume.get('labels', {})))}</td>"
            f"</tr>"
        )
    return "".join(rows)


def dangling_summary_rows(summary):
    if not summary:
        return "<tr><td colspan='2' style='color:#888;font-style:italic'>No dangling Docker summary collected for this run.</td></tr>"

    rows = [
        ("Dangling images", summary.get("dangling_images_count", 0)),
        ("Dangling image size", summary.get("dangling_images_size", "0B")),
        ("Dangling volumes", summary.get("dangling_volumes_count", 0)),
        ("Stopped containers", summary.get("stopped_containers_count", 0)),
        ("Stopped container size", summary.get("stopped_containers_size", "0B")),
    ]
    return "".join(
        f"<tr><td style='width:220px;font-weight:600;color:#555;font-size:12px;text-transform:uppercase;letter-spacing:.04em'>{escape(str(label))}</td>"
        f"<td>{escape(str(value))}</td></tr>"
        for label, value in rows
    )


def build_cache_summary_rows(data):
    if not data:
        return "<tr><td colspan='2' style='color:#888;font-style:italic'>No Docker build cache summary collected for this run.</td></tr>"

    rows = [
        ("Cache total", data.get("cache_total", "0B")),
        ("Cache reclaimable", data.get("cache_reclaimable", "0B")),
        ("Builder backend", data.get("builder_backend", "unknown")),
    ]
    return "".join(
        f"<tr><td style='width:220px;font-weight:600;color:#555;font-size:12px;text-transform:uppercase;letter-spacing:.04em'>{escape(str(label))}</td>"
        f"<td>{escape(str(value))}</td></tr>"
        for label, value in rows
    )


def build_cache_entry_rows(entries, limit=20):
    if not entries:
        return "<tr><td colspan='5' style='color:#888;font-style:italic'>No detailed cache entries available for this run.</td></tr>"

    def sort_key(entry):
        reclaimable = 1 if entry.get("reclaimable") else 0
        shared = 1 if entry.get("shared") else 0
        return (
            -reclaimable,
            -shared,
            str(entry.get("size", "")),
            str(entry.get("id", "")),
            str(entry.get("description", "")),
        )

    rows = []
    for entry in sorted(entries, key=sort_key)[:limit]:
        rows.append(
            f"<tr>"
            f"<td style='font-size:12px;word-break:break-all'>{escape(str(entry.get('id', '')))}</td>"
            f"<td style='font-size:12px;word-break:break-all'>{escape(str(entry.get('description', '')))}</td>"
            f"<td>{escape(str(entry.get('size', '')))}</td>"
            f"<td>{'Yes' if entry.get('reclaimable') else 'No'}</td>"
            f"<td>{'Yes' if entry.get('shared') else 'No'}</td>"
            f"</tr>"
        )
    return "".join(rows)


def image_rows(images):
    rows = []
    for img in images:
        rows.append(
            f"<tr>"
            f"<td>{escape(str(img.get('repo', '')))}</td>"
            f"<td style='word-break:break-all;font-size:12px'>{escape(str(img.get('tag', '')))}</td>"
            f"<td>{escape(str(img.get('size', '')))}</td>"
            f"</tr>"
        )
    return "".join(rows) or "<tr><td colspan='3'>No Xenium images found</td></tr>"


def inventory_image_rows(images, limit=25):
    if not images:
        return "<tr><td colspan='8' style='color:#888;font-style:italic'>No Docker image inventory collected for this run.</td></tr>"

    def sort_key(img):
        current_pr = 1 if img.get("belongs_to_current_pr") else 0
        current_sha = 1 if img.get("belongs_to_current_sha") else 0
        return (
            -current_pr,
            -current_sha,
            str(img.get("repository", "")),
            str(img.get("tag", "")),
        )

    sorted_images = sorted(images, key=sort_key)
    rows = []
    for img in sorted_images[:limit]:
        current_pr = "Yes" if img.get("belongs_to_current_pr") else "No"
        current_sha = "Yes" if img.get("belongs_to_current_sha") else "No"
        digest = img.get("digest")
        rows.append(
            f"<tr>"
            f"<td style='font-size:12px;word-break:break-all'>{escape(str(img.get('repository', '')))}</td>"
            f"<td style='font-size:12px;word-break:break-all'>{escape(str(img.get('tag', '')))}</td>"
            f"<td style='font-size:12px;word-break:break-all'>{escape(str(img.get('image_id', '')))}</td>"
            f"<td style='font-size:12px;word-break:break-all'>{escape(str(digest if digest is not None else '—'))}</td>"
            f"<td style='white-space:nowrap'>{escape(str(img.get('created_since', '')))}</td>"
            f"<td>{escape(str(img.get('size', '')))}</td>"
            f"<td>{escape(current_pr)}</td>"
            f"<td>{escape(current_sha)}</td>"
            f"</tr>"
        )
    return "".join(rows)


# ── Phase 4 render helpers ────────────────────────────────────────────────────

def directory_sizes_section_rows(row):
    """Render the latest directory-sizes tick as a key/value table."""
    if not row:
        return (
            "<tr><td colspan='3' style='color:#888;font-style:italic'>"
            "No directory size data available for this run.</td></tr>"
        )

    DOCKER_NOTE = (
        "<span style='color:#e67e22;font-size:11px;margin-left:6px'>"
        "&#x26A0; runner may lack read access to Docker storage</span>"
    )

    def size_cell(size_kb, path):
        try:
            kb = int(size_kb)
        except (TypeError, ValueError):
            kb = 0
        note = ""
        if "/var/lib/docker" in str(path) and kb <= 4:
            note = DOCKER_NOTE
        return f"<td>{escape(format_kb(kb))}{note}</td>"

    fields = [
        ("Runner workspace",        row.get("runner_workspace_path", ""),        row.get("runner_workspace_size", 0)),
        ("Preview base dir",        row.get("preview_base_dir_path", ""),         row.get("preview_base_dir_size", 0)),
        ("PR preview dir",          row.get("current_pr_preview_dir_path", ""),  row.get("current_pr_preview_dir_size", 0)),
        ("Docker root dir",         row.get("docker_root_dir_path", ""),          row.get("docker_root_dir_size", 0)),
        ("/var/lib/docker",         row.get("var_lib_docker_path", ""),           row.get("var_lib_docker_size", 0)),
        ("Actions runner work dir", row.get("actions_runner_work_path", ""),      row.get("actions_runner_work_size", 0)),
        ("CI stats dir",            row.get("ci_stats_dir_path", ""),             row.get("ci_stats_dir_size", 0)),
    ]

    rows = []
    for label, path, size_kb in fields:
        if not path:
            path_cell = "<td style='color:#aaa;font-size:12px'>not resolved</td>"
        else:
            path_cell = (
                f"<td style='font-size:12px;word-break:break-all;color:#555'>"
                f"{escape(str(path))}</td>"
            )
        rows.append(
            "<tr>"
            "<td style='font-weight:600;color:#555;font-size:12px;"
            f"text-transform:uppercase;letter-spacing:.04em;white-space:nowrap'>{escape(label)}</td>"
            + path_cell
            + size_cell(size_kb, path)
            + "</tr>"
        )
    return "".join(rows)


def inode_usage_section_rows(rows):
    """Render the latest inode-usage tick rows (one per mount)."""
    if not rows:
        return (
            "<tr><td colspan='6' style='color:#888;font-style:italic'>"
            "No inode usage data available for this run.</td></tr>"
        )

    output = []
    for r in rows:
        pct = r.get("inode_pct", 0)
        try:
            pct = int(pct)
        except (TypeError, ValueError):
            pct = 0
        bar_color = "#e74c3c" if pct >= 80 else ("#e67e22" if pct >= 65 else "#27ae60")
        row_style = ""
        if pct >= 80:
            row_style = "background:#ffe0e0;"
        elif pct >= 65:
            row_style = "background:#fff3cd;"
        pct_bar = (
            f"<div style='display:flex;align-items:center;gap:8px'>"
            f"<div style='flex:1;background:#e9ecef;border-radius:4px;height:8px;min-width:80px'>"
            f"<div style='width:{pct}%;background:{bar_color};border-radius:4px;height:8px'></div>"
            f"</div>"
            f"<b style='min-width:38px'>{escape(str(pct))}%</b>"
            f"</div>"
        )
        output.append(
            f"<tr style='{row_style}'>"
            f"<td style='white-space:nowrap'>{escape(str(r.get('path', '')))}</td>"
            f"<td style='font-size:12px;color:#555'>{escape(str(r.get('filesystem', '')))}</td>"
            f"<td style='font-size:12px;color:#555'>{escape(str(r.get('mount', '')))}</td>"
            f"<td>{pct_bar}</td>"
            f"<td>{escape(format_count(r.get('inode_used', 0)))}</td>"
            f"<td>{escape(format_count(r.get('inode_total', 0)))}</td>"
            f"</tr>"
        )
    return "".join(output)


def host_stats_section_rows(row):
    """Render the latest host-stats tick as a key/value table."""
    if not row:
        return (
            "<tr><td colspan='2' style='color:#888;font-style:italic'>"
            "No host stats data available for this run.</td></tr>"
        )

    def kv(label, val):
        return (
            "<tr>"
            f"<td style='width:220px;font-weight:600;color:#555;font-size:12px;"
            f"text-transform:uppercase;letter-spacing:.04em'>{label}</td>"
            f"<td>{escape(str(val))}</td>"
            "</tr>"
        )

    def mem_bar(used_kb, total_kb):
        try:
            used_kb  = int(used_kb)
            total_kb = int(total_kb)
        except (TypeError, ValueError):
            return ""
        if total_kb <= 0:
            return ""
        pct = min(100, round(used_kb * 100 / total_kb))
        bar_color = "#e74c3c" if pct >= 90 else ("#e67e22" if pct >= 75 else "#27ae60")
        return (
            " <span style='display:inline-flex;align-items:center;gap:6px;vertical-align:middle'>"
            "<span style='display:inline-block;width:80px;background:#e9ecef;border-radius:4px;height:8px'>"
            f"<span style='display:block;width:{pct}%;background:{bar_color};border-radius:4px;height:8px'></span>"
            "</span>"
            f"<b>{pct}%</b></span>"
        )

    mem_total = row.get("memory_total", 0)
    mem_used  = row.get("memory_used", 0)
    mem_avail = row.get("memory_available", 0)
    swap_used = row.get("swap_used", 0)
    load_avg  = row.get("load_average", {})
    cpu_cores = row.get("cpu_cores", 0)

    td_label = (
        "style='width:220px;font-weight:600;color:#555;font-size:12px;"
        "text-transform:uppercase;letter-spacing:.04em'"
    )
    rows_out = [
        kv("CPU cores", cpu_cores),
        f"<tr><td {td_label}>Memory total</td>"
        f"<td>{escape(format_kb(mem_total))}</td></tr>",
        f"<tr><td {td_label}>Memory used</td>"
        f"<td>{escape(format_kb(mem_used))}{mem_bar(mem_used, mem_total)}</td></tr>",
        f"<tr><td {td_label}>Memory available</td>"
        f"<td>{escape(format_kb(mem_avail))}</td></tr>",
        kv("Swap used", format_kb(swap_used)),
        kv(
            "Load avg (1m / 5m / 15m)",
            f"{load_avg.get('1m', '?')} / {load_avg.get('5m', '?')} / {load_avg.get('15m', '?')}",
        ),
    ]
    return "".join(rows_out)


# ── Phase 2 render helpers ────────────────────────────────────────────────────

def _no_data(cols=4):
    return f"<tr><td colspan='{cols}' style='color:#aaa;font-style:italic'>No data collected for this run</td></tr>"


def tag_pr_rows(data):
    images = data.get("images_retagged", [])
    if not images:
        return _no_data(6)
    rows = []
    for img in images:
        svc   = escape(str(img.get("service", "")))
        src   = escape(str(img.get("source_tag", "")))
        dst   = escape(str(img.get("destination_tag", "")))
        start = escape(str(img.get("tag_start_time", "-")))
        end   = escape(str(img.get("tag_end_time", "-")))
        dur   = img.get("duration_seconds", 0)
        rows.append(
            f"<tr><td><b>{svc}</b></td>"
            f"<td style='font-size:12px;word-break:break-all'>{src}</td>"
            f"<td style='font-size:12px;word-break:break-all'>{dst}</td>"
            f"<td style='white-space:nowrap'>{start}</td>"
            f"<td style='white-space:nowrap'>{end}</td>"
            f"<td style='white-space:nowrap'>{fmt_dur(dur)}</td></tr>"
        )
    return "".join(rows)


def preview_up_rows(data):
    if not data:
        return _no_data(2)

    def kv(label, val, sub=""):
        return (
            f"<tr>"
            f"<td style='width:220px;font-weight:600;color:#555;font-size:12px;text-transform:uppercase;letter-spacing:.04em'>{label}</td>"
            f"<td>{escape(str(val))}<span style='color:#aaa;font-size:11px;margin-left:8px'>{sub}</span></td>"
            f"</tr>"
        )

    rows = []

    rows.append(kv("Preview dir", data.get("preview_dir", "—")))

    bef = data.get("preview_dir_size_before_kb", None)
    aft = data.get("preview_dir_size_after_kb", None)
    if bef is not None:
        rows.append(kv("Dir size before", format_kb(bef)))
    if aft is not None:
        delta_kb = (aft or 0) - (bef or 0)
        delta_str = f"+{format_kb(delta_kb)}" if delta_kb >= 0 else f"-{format_kb(-delta_kb)}"
        rows.append(kv("Dir size after", format_kb(aft), f"(Δ {delta_str})"))


    if data.get("compose_pull_duration_seconds") is not None:
        rows.append(kv("Compose pull", fmt_dur(data["compose_pull_duration_seconds"])))
    if data.get("compose_up_duration_seconds") is not None:
        rows.append(kv("Compose up", fmt_dur(data["compose_up_duration_seconds"])))


    if data.get("compose_pull_start"):
        rows.append(kv("Compose pull start", data.get("compose_pull_start", "—")))
    if data.get("compose_pull_end"):
        rows.append(kv("Compose pull end", data.get("compose_pull_end", "—")))
    if data.get("compose_up_start"):
        rows.append(kv("Compose up start", data.get("compose_up_start", "—")))
    if data.get("compose_up_end"):
        rows.append(kv("Compose up end", data.get("compose_up_end", "—")))

    svcs = data.get("services_started", [])
    if svcs:
        rows.append(kv("Services started", ", ".join(svcs)))

    rows.append(kv("Final containers", data.get("preview_final_container_count", "—")))
    rows.append(kv("Final volumes", data.get("preview_final_volume_count", "—")))
    rows.append(kv("Seed load", data.get("seed_load_status", "—")))


    waits = data.get("health_waits", [])
    if waits:
        wait_parts = []
        for w in waits:
            service = escape(str(w.get("service", "unknown")))
            waited = w.get("waited_seconds", 0)
            status = escape(str(w.get("status", "unknown")))

            status_color = "#27ae60" if status in ("healthy", "ready") else "#e67e22"
            wait_parts.append(
                f"<div style='margin-bottom:4px'>"
                f"<b>{service}</b>: {waited}s "
                f"<span style='color:{status_color};font-weight:600'>({status})</span>"
                f"</div>"
            )

        rows.append(
            f"<tr>"
            f"<td style='width:220px;font-weight:600;color:#555;font-size:12px;text-transform:uppercase;letter-spacing:.04em'>Health waits</td>"
            f"<td>{''.join(wait_parts)}</td>"
            f"</tr>"
        )

    return "".join(rows)


def cleanup_rows(data):
    if not data:
        return _no_data(2)

    def kv(label, val, highlight="", is_html=False):
        style = f"color:{highlight};font-weight:bold" if highlight else ""
        rendered_val = str(val) if is_html else escape(str(val))
        return (
            f"<tr><td style='width:220px;font-weight:600;color:#555;font-size:12px;text-transform:uppercase;letter-spacing:.04em'>{label}</td>"
            f"<td style='{style}'>{rendered_val}</td></tr>"
    )

    def fs_summary(before, after):
        if not before and not after:
            return "-"

        before_map = {entry.get("mount"): entry for entry in before or []}
        after_map = {entry.get("mount"): entry for entry in after or []}
        parts = []

        for mount in ["/", "/var", "/opt/sca"]:
            b = before_map.get(mount, {})
            a = after_map.get(mount, {})
            if not b and not a:
                continue
            b_pct = b.get("pct", "-")
            a_pct = a.get("pct", "-")
            b_used = format_kb(b.get("used_kb", 0)) if b else "-"
            a_used = format_kb(a.get("used_kb", 0)) if a else "-"
            parts.append(
                f"<div style='margin-bottom:4px'>"
                f"<b>{escape(mount)}</b>: {escape(str(b_pct))}% -> {escape(str(a_pct))}%"
                f"<span style='color:#888;font-size:11px;margin-left:8px'>used {escape(str(b_used))} -> {escape(str(a_used))}</span>"
                f"</div>"
            )

        return "".join(parts) if parts else "-"

    def docker_summary(before, after):
        if not before and not after:
            return "-"

        metrics = [
            ("Images", "images_total", "images_reclaimable"),
            ("Containers", "containers_total", "containers_reclaimable"),
            ("Volumes", "volumes_total", "volumes_reclaimable"),
            ("Build Cache", "build_cache_total", "build_cache_reclaimable"),
        ]
        parts = []

        for label, total_key, reclaim_key in metrics:
            before_total = before.get(total_key, "-") if before else "-"
            after_total = after.get(total_key, "-") if after else "-"
            before_reclaim = before.get(reclaim_key, "-") if before else "-"
            after_reclaim = after.get(reclaim_key, "-") if after else "-"
            parts.append(
                f"<div style='margin-bottom:4px'>"
                f"<b>{escape(label)}</b>: {escape(str(before_total))} -> {escape(str(after_total))}"
                f"<span style='color:#888;font-size:11px;margin-left:8px'>reclaimable {escape(str(before_reclaim))} -> {escape(str(after_reclaim))}</span>"
                f"</div>"
            )

        return "".join(parts) if parts else "-"

    def counts_summary(before, after):
        before = before or {}
        after = after or {}
        metrics = [
            ("Running containers", "container_count"),
            ("Images", "image_count"),
            ("Volumes", "volume_count"),
        ]
        parts = []

        for label, key in metrics:
            parts.append(
                f"<div style='margin-bottom:4px'>"
                f"<b>{escape(label)}</b>: {escape(str(before.get(key, '-')))} -> {escape(str(after.get(key, '-')))}"
                f"</div>"
            )

        return "".join(parts) if parts else "-"

    def directory_sizes_summary(before, after):
        before = before or {}
        after = after or {}
        metrics = [
            ("Runner workspace", "runner_workspace_size_kb"),
            ("Preview base", "preview_base_dir_size_kb"),
            ("Current PR preview dir", "current_pr_preview_dir_size_kb"),
            ("Docker root", "docker_root_dir_size_kb"),
            ("Actions runner work", "actions_runner_work_size_kb"),
            ("CI stats dir", "ci_stats_dir_size_kb"),
        ]
        parts = []

        for label, key in metrics:
            before_size = format_kb(before.get(key, 0)) if before else "-"
            after_size = format_kb(after.get(key, 0)) if after else "-"
            parts.append(
                f"<div style='margin-bottom:4px'>"
                f"<b>{escape(label)}</b>: {escape(str(before_size))} -> {escape(str(after_size))}"
                f"</div>"
            )

        return "".join(parts) if parts else "-"

    def pipeline_snapshot_summary(before, after):
        if not before and not after:
            return "-"

        before = before or {}
        after = after or {}
        sections = [
            f"<div style='margin-bottom:8px'><b>Timestamps</b>: {escape(str(before.get('timestamp', '-')))} -> {escape(str(after.get('timestamp', '-')))}</div>",
            f"<div style='margin-bottom:8px'><b>Filesystem</b>{fs_summary(before.get('fs'), after.get('fs'))}</div>",
            f"<div style='margin-bottom:8px'><b>Docker summary</b>{docker_summary(before.get('docker_df'), after.get('docker_df'))}</div>",
            f"<div style='margin-bottom:8px'><b>Object counts</b>{counts_summary(before.get('counts'), after.get('counts'))}</div>",
            f"<div><b>Tracked directory sizes</b>{directory_sizes_summary(before.get('directory_sizes'), after.get('directory_sizes'))}</div>",
        ]
        return "".join(sections)

    rows = []
    rows.append(kv("Prune ran", "Yes" if data.get("docker_prune_ran") else "No"))
    rows.append(kv("Start time", data.get("cleanup_start_time", "-")))
    rows.append(kv("End time", data.get("cleanup_end_time", "-")))
    rows.append(kv("Duration", fmt_dur(data.get("cleanup_duration_seconds", 0))))
    rec = data.get("estimated_reclaimed_space", "0B")
    highlight_color = "#27ae60" if rec and rec not in ("0B", "") else ""
    rows.append(kv("Space reclaimed", rec, highlight_color))
    rows.append(kv("Build cache reclaimed", data.get("build_cache_reclaimed", "-")))
    rows.append(kv("Images removed", data.get("images_removed_count", 0)))
    rows.append(kv("Containers removed", data.get("containers_removed_count", 0)))
    rows.append(kv("Volumes removed", data.get("volumes_removed_count", 0)))
    rows.append(kv("Preview dirs removed", data.get("preview_dirs_removed", 0)))
    rows.append(kv("Stats dirs removed", data.get("stats_dirs_removed", 0)))
    rows.append(kv("Filesystem before -> after", fs_summary(data.get("fs_before"), data.get("fs_after")), is_html=True))
    rows.append(kv("Docker before -> after", docker_summary(data.get("docker_df_before"), data.get("docker_df_after")), is_html=True))
    rows.append(
        kv(
            "Pipeline baseline -> final",
            pipeline_snapshot_summary(
                data.get("pipeline_baseline_snapshot"),
                data.get("pipeline_final_snapshot"),
            ),
            is_html=True,
        )
    )
    return "".join(rows)


def failure_rows(data):
    if not data:
        return _no_data(2)
    def kv(label, val):
        return (f"<tr><td style='width:220px;font-weight:600;color:#555;font-size:12px;text-transform:uppercase;letter-spacing:.04em'>{label}</td>"
                f"<td>{escape(str(val))}</td></tr>")
    rows = []
    rows.append(kv("Failed stage", data.get("failure_stage", "—")))
    artifacts = data.get("artifacts_generated", [])
    rows.append(kv("Artifacts", ", ".join(artifacts) if artifacts else "—"))
    logs = data.get("logs_collected", [])
    rows.append(kv("Logs collected", ", ".join(logs) if logs else "—"))
    rows.append(kv("Fallback cleanup", "Yes" if data.get("fallback_cleanup_used") else "No"))
    rows.append(kv("Extra disk growth", "Yes" if data.get("extra_disk_growth_detected") else "No"))
    return "".join(rows)


has_failures = bool(fail_diag_data)


def delta_cell(val, is_pct=True):
    """Render a delta value with color. Positive = red (growth), negative = green (freed)."""
    suffix = "%" if is_pct else ""
    if val > 0:
        return f"<td style='color:#c0392b;font-weight:bold'>+{val}{suffix}</td>"
    elif val < 0:
        return f"<td style='color:#27ae60;font-weight:bold'>{val}{suffix}</td>"
    else:
        return f"<td style='color:#888'>0{suffix}</td>"


def fmt_dur(seconds):
    try:
        seconds = int(seconds)
    except (TypeError, ValueError):
        seconds = 0
    m = seconds // 60
    s = seconds % 60
    if m > 0:
        return f"{m}m {s}s"
    return f"{s}s"


def format_percent_or_na(value):
    if value is None or value == "":
        return "â€”"
    return f"{safe_int(value, 0)}%"


def format_nullable_count(value):
    if value is None or value == "":
        return "â€”"
    return str(safe_int(value, 0))


def format_step_summary(step_data):
    if not isinstance(step_data, dict):
        return ("â€”", "n/a")

    step_name = str(step_data.get("step_name") or "").strip()
    duration = step_data.get("duration_seconds")
    if not step_name:
        return ("â€”", "n/a")
    if duration is None:
        return (step_name, "n/a")
    return (step_name, fmt_dur(duration))


def format_metric_delta(step_data):
    if not isinstance(step_data, dict):
        return ("â€”", "n/a")

    step_name = str(step_data.get("step_name") or "").strip()
    metric = str(step_data.get("metric") or "").strip()
    delta_value = step_data.get("delta_value")

    if not step_name or not metric or delta_value is None:
        return ("â€”", "n/a")

    delta = safe_int(delta_value, 0)
    sign = "+" if delta > 0 else ""
    if metric in {"/", "/var", "/opt/sca"}:
        detail = f"{sign}{delta}% {metric}"
    else:
        detail = f"{sign}{delta} {metric}"
    return (step_name, detail)


def format_percent_or_na(value):
    if value is None or value == "":
        return "N/A"
    return f"{safe_int(value, 0)}%"


def format_nullable_count(value):
    if value is None or value == "":
        return "N/A"
    return str(safe_int(value, 0))


def format_step_summary(step_data):
    if not isinstance(step_data, dict):
        return ("N/A", "n/a")

    step_name = str(step_data.get("step_name") or "").strip()
    duration = step_data.get("duration_seconds")
    if not step_name:
        return ("N/A", "n/a")
    if duration is None:
        return (step_name, "n/a")
    return (step_name, fmt_dur(duration))


def format_metric_delta(step_data):
    if not isinstance(step_data, dict):
        return ("N/A", "n/a")

    step_name = str(step_data.get("step_name") or "").strip()
    metric = str(step_data.get("metric") or "").strip()
    delta_value = step_data.get("delta_value")

    if not step_name or not metric or delta_value is None:
        return ("N/A", "n/a")

    delta = safe_int(delta_value, 0)
    sign = "+" if delta > 0 else ""
    if metric in {"/", "/var", "/opt/sca"}:
        detail = f"{sign}{delta}% {metric}"
    else:
        detail = f"{sign}{delta} {metric}"
    return (step_name, detail)


def fmt_ts(value):
    return escape(str(value)) if value else "—"


def _duration_between(start, end):
    if not start or not end:
        return None
    try:
        t0 = datetime.fromisoformat(str(start).replace("Z", "+00:00"))
        t1 = datetime.fromisoformat(str(end).replace("Z", "+00:00"))
        return max(0, int((t1 - t0).total_seconds()))
    except Exception:
        return None


def _service_label(service):
    labels = {"api": "API", "ui": "UI", "workers": "Workers"}
    return labels.get(str(service), str(service).title())


def build_breakdown_rows(rows):
    if not rows:
        return "<tr><td colspan='8' style='color:#888;font-style:italic'>No build breakdown data available for this run.</td></tr>"

    service_order = {"api": 0, "ui": 1, "workers": 2}
    normalized = {}
    for row in rows:
        if isinstance(row, dict):
            service = str(row.get("service", ""))
            if service in service_order:
                normalized[service] = row

    output = []
    for service in ["api", "ui", "workers"]:
        row = normalized.get(service, {})
        build_start = row.get("build_start")
        build_end = row.get("build_end")
        push_start = row.get("push_start")
        push_end = row.get("push_end")
        try:
            build_duration = int(row.get("build_duration_seconds", 0) or 0)
        except (TypeError, ValueError):
            build_duration = 0
        try:
            push_duration = int(row.get("push_duration_seconds", 0) or 0)
        except (TypeError, ValueError):
            push_duration = 0
        final_image_size = row.get("final_image_size")

        build_duration_cell = fmt_dur(build_duration) if (build_start or build_end or build_duration > 0) else "—"
        push_duration_cell = fmt_dur(push_duration) if (push_start or push_end or push_duration > 0) else "—"
        size_cell = format_bytes(final_image_size) if final_image_size is not None else "—"

        output.append(
            f"<tr>"
            f"<td><b>{escape(_service_label(service))}</b></td>"
            f"<td style='white-space:nowrap'>{escape(build_duration_cell)}</td>"
            f"<td style='white-space:nowrap'>{escape(push_duration_cell)}</td>"
            f"<td style='white-space:nowrap'>{escape(size_cell)}</td>"
            f"<td style='white-space:nowrap'>{fmt_ts(build_start)}</td>"
            f"<td style='white-space:nowrap'>{fmt_ts(build_end)}</td>"
            f"<td style='white-space:nowrap'>{fmt_ts(push_start)}</td>"
            f"<td style='white-space:nowrap'>{fmt_ts(push_end)}</td>"
            f"</tr>"
        )
    return "".join(output)


def test_breakdown_rows(data):
    if not data:
        return "<tr><td colspan='4' style='color:#888;font-style:italic'>No test breakdown data available for this run.</td></tr>"

    env_duration = _duration_between(data.get("env_up_start"), data.get("env_up_end"))
    playwright_duration = data.get("playwright_duration", 0)
    teardown_duration = data.get("teardown_duration", 0)

    rows = [
        ("Environment Up", data.get("env_up_start"), data.get("env_up_end"), fmt_dur(env_duration) if env_duration is not None else "—"),
        ("Postgres Wait", None, None, fmt_dur(data.get("postgres_wait_duration", 0))),
        ("API Wait", None, None, fmt_dur(data.get("api_wait_duration", 0))),
        ("UI Wait", None, None, fmt_dur(data.get("ui_wait_duration", 0))),
        ("Playwright Run", data.get("playwright_start"), data.get("playwright_end"), fmt_dur(playwright_duration)),
        ("Teardown", data.get("teardown_start"), data.get("teardown_end"), fmt_dur(teardown_duration)),
    ]

    return "".join(
        f"<tr>"
        f"<td><b>{escape(label)}</b></td>"
        f"<td style='white-space:nowrap'>{fmt_ts(start)}</td>"
        f"<td style='white-space:nowrap'>{fmt_ts(end)}</td>"
        f"<td style='white-space:nowrap'>{escape(duration)}</td>"
        f"</tr>"
        for label, start, end, duration in rows
    )


def test_breakdown_note(data):
    if not data:
        return ""
    env_duration = _duration_between(data.get("env_up_start"), data.get("env_up_end")) or 0
    durations = [
        ("Environment Up", env_duration),
        ("Postgres Wait", data.get("postgres_wait_duration", 0)),
        ("API Wait", data.get("api_wait_duration", 0)),
        ("UI Wait", data.get("ui_wait_duration", 0)),
        ("Playwright Run", data.get("playwright_duration", 0)),
        ("Teardown", data.get("teardown_duration", 0)),
    ]
    label, duration = max(durations, key=lambda item: int(item[1] or 0))
    if int(duration or 0) <= 0:
        return ""
    return f"{escape(label)} was the longest test sub-step in this run."


def preview_step_breakdown_rows(data):
    if not data:
        return "<tr><td colspan='2' style='color:#888;font-style:italic'>No preview-up breakdown data available for this run.</td></tr>"

    rows = [
        ("Sync", data.get("sync_duration", 0)),
        ("Compose Pull", data.get("pull_duration", 0)),
        ("Compose Up", data.get("up_duration", 0)),
        ("API Health Wait", data.get("api_health_wait", 0)),
        ("UI Health Wait", data.get("ui_health_wait", 0)),
        ("Signet Health Wait", data.get("signet_health_wait", 0)),
        ("Rhythm Health Wait", data.get("rhythm_health_wait", 0)),
        ("Seed Load", data.get("seed_load_duration", 0)),
    ]
    return "".join(
        f"<tr><td><b>{escape(label)}</b></td><td style='white-space:nowrap'>{escape(fmt_dur(duration))}</td></tr>"
        for label, duration in rows
    )


# ── Step summaries section ────────────────────────────────────────────────────
def active_warnings(data):
    if not isinstance(data, dict):
        return None
    warnings = data.get("warnings")
    if not isinstance(warnings, list):
        return None
    return [warning for warning in warnings if isinstance(warning, dict) and warning.get("active")]


def severity_badge_class(severity):
    severity = safe_str(severity, "").strip().lower()
    if severity == "error":
        return "warning-badge error"
    if severity == "info":
        return "warning-badge info"
    return "warning-badge warning"


def warning_banner_html(data):
    warnings = active_warnings(data)
    if warnings is None:
        return "<div class='warning-empty'>No warning data available for this run.</div>"
    if not warnings:
        return "<div class='warning-empty ok'>No warnings detected for this run.</div>"

    rows = []
    for warning in warnings:
        severity = safe_str(warning.get("severity"), "warning").title()
        message = safe_str(warning.get("message"), "").strip()
        code = safe_str(warning.get("code"), "").strip()
        if not message:
            continue
        code_html = f"<span class='warning-code'>{escape(code)}</span>" if code else ""
        rows.append(
            "<div class='warning-item'>"
            f"<span class='{severity_badge_class(severity)}'>{escape(severity)}</span>"
            f"<span class='warning-message'>{escape(message)}</span>"
            f"{code_html}"
            "</div>"
        )

    if not rows:
        return "<div class='warning-empty ok'>No warnings detected for this run.</div>"
    return "".join(rows)


def step_delta_rows(steps):
    if not steps:
        return "<tr><td colspan='9' style='color:#888;font-style:italic'>No step data collected — mark_step.sh hooks may not have run for this build.</td></tr>"
    rows = []
    for s in steps:
        delta = s.get("delta_summary", {})
        root_d = delta.get("root_pct_delta", 0)
        var_d = delta.get("var_pct_delta", 0)
        opt_d = delta.get("opt_sca_pct_delta", 0)
        c_d = delta.get("container_delta", 0)
        i_d = delta.get("image_delta", 0)
        v_d = delta.get("volume_delta", 0)
        dur = s.get("duration_seconds", 0)
        status = s.get("status", "unknown")
        step_name = escape(s.get("step_name", ""))
        job_name = escape(s.get("job_name", ""))
        status_icon = "✅" if status == "success" else "❌"

        # Row highlight: significant growth in /var
        row_style = ""
        if var_d >= 5:
            row_style = "background:#fff8e1;"
        elif var_d <= -5:
            row_style = "background:#e8f5e9;"

        rows.append(
            f"<tr style='{row_style}'>"
            f"<td>{status_icon}</td>"
            f"<td style='white-space:nowrap'><b>{step_name}</b></td>"
            f"<td style='color:#666;font-size:12px'>{job_name}</td>"
            f"<td style='white-space:nowrap'>{fmt_dur(dur)}</td>"
            + delta_cell(root_d)
            + delta_cell(var_d)
            + delta_cell(opt_d)
            + delta_cell(c_d, is_pct=False)
            + delta_cell(i_d, is_pct=False)
            + f"</tr>"
        )
    return "".join(rows)


def git_context_summary_rows(data):
    if not data:
        return "<tr><td colspan='2' style='color:#888;font-style:italic'>No Git context data available for this run.</td></tr>"

    rows = [
        ("PR Number", f"#{data.get('pr_number', '—')}"),
        ("Event Action", data.get("event_action", "—") or "—"),
        ("Commit SHA", shorten_sha(data.get("sha", ""))),
        ("Base SHA", shorten_sha(data.get("base_sha", ""))),
        ("Head SHA", shorten_sha(data.get("head_sha", ""))),
        ("Changed File Count", format_count(data.get("changed_file_count", 0))),
    ]
    return "".join(
        f"<tr><th>{escape(str(label))}</th><td>{escape(str(value))}</td></tr>"
        for label, value in rows
    )


def git_context_flag_rows(data):
    if not data:
        return "<tr><td colspan='2' style='color:#888;font-style:italic'>No Git context data available for this run.</td></tr>"

    rows = [
        ("API Changed", format_bool_flag(data.get("api_changed"))),
        ("UI Changed", format_bool_flag(data.get("ui_changed"))),
        ("Workers Changed", format_bool_flag(data.get("workers_changed"))),
    ]
    return "".join(
        f"<tr><th>{escape(str(label))}</th><td style='font-size:18px'>{value}</td></tr>"
        for label, value in rows
    )


def git_context_file_rows(data, limit=20):
    if not data:
        return "<tr><td style='color:#888;font-style:italic'>No Git context data available for this run.</td></tr>"

    files = data.get("changed_files", [])
    if not isinstance(files, list) or not files:
        return "<tr><td style='color:#888;font-style:italic'>No changed files recorded for this run.</td></tr>"

    rows = []
    for path in files[:limit]:
        rows.append(
            f"<tr><td style='font-size:12px;word-break:break-all'>{escape(str(path))}</td></tr>"
        )

    remaining = len(files) - limit
    if remaining > 0:
        rows.append(
            f"<tr><td style='color:#888;font-style:italic'>... and {remaining} more file{'s' if remaining != 1 else ''}</td></tr>"
        )
    return "".join(rows)


# ── Timeline rows ─────────────────────────────────────────────────────────────
timeline_rows = []
for t in ticks:
    mounts = {f.get("mount"): f.get("pct") for f in t.get("fs", [])}
    var_pct = mounts.get("/var", "?")
    opt_pct = mounts.get("/opt/sca", "?")

    var_style = ""
    if isinstance(var_pct, int) and var_pct >= 75:
        var_style = "color:#c0392b;font-weight:bold"
    elif isinstance(var_pct, int) and var_pct >= 65:
        var_style = "color:#e67e22;font-weight:bold"

    timeline_rows.append(
        f"<tr>"
        f"<td>{escape(str(t.get('tick', '')))}</td>"
        f"<td style='white-space:nowrap'>{escape(str(t.get('ts', '')))}</td>"
        f"<td>{escape(str(t.get('stage', '')))}</td>"
        f"<td>{escape(str(mounts.get('/', '?')))}%</td>"
        f"<td style='{var_style}'>{escape(str(var_pct))}%</td>"
        f"<td>{escape(str(opt_pct))}%</td>"
        f"<td>{len(t.get('containers', []))}</td>"
        f"</tr>"
    )

# ── Build HTML ────────────────────────────────────────────────────────────────
longest_step_label = f"{longest_step_name} ({fmt_dur(longest_step_dur)})" if longest_step_dur > 0 else "—"
growth_label = f"{biggest_growth_step} (+{biggest_growth_val}%)" if biggest_growth_val > 0 else "—"
cleanup_label = f"{biggest_cleanup_step} ({biggest_cleanup_val}%)" if biggest_cleanup_val < 0 else "—"
test_breakdown_summary_note = test_breakdown_note(test_summary_data)

summary_peak_var = format_percent_or_na(run_summary_data.get("peak_var_pct")) if run_summary_data else "â€”"
summary_peak_opt = format_percent_or_na(run_summary_data.get("peak_opt_sca_pct")) if run_summary_data else "â€”"
summary_max_containers = format_nullable_count(run_summary_data.get("max_container_count")) if run_summary_data else "â€”"
summary_max_images = format_nullable_count(run_summary_data.get("max_image_count")) if run_summary_data else "â€”"
summary_max_volumes = format_nullable_count(run_summary_data.get("max_volume_count")) if run_summary_data else "â€”"
summary_longest_step_value, summary_longest_step_sub = format_step_summary(run_summary_data.get("longest_step")) if run_summary_data else ("â€”", "n/a")
summary_growth_value, summary_growth_sub = format_metric_delta(run_summary_data.get("largest_step_growth")) if run_summary_data else ("â€”", "n/a")
summary_cleanup_value, summary_cleanup_sub = format_metric_delta(run_summary_data.get("largest_cleanup_reduction")) if run_summary_data else ("â€”", "n/a")

warnings_section_html = warning_banner_html(warnings_render_data)

html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>CI Stats Report - PR #{PR}</title>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
      margin: 0;
      background: #f5f7fa;
      color: #1a1a2e;
    }}
    .page-header {{
      background: linear-gradient(135deg, #1a1a2e 0%, #16213e 60%, #0f3460 100%);
      color: white;
      padding: 28px 40px 24px;
      border-bottom: 3px solid #e94560;
    }}
    .page-header h1 {{
      margin: 0 0 6px;
      font-size: 26px;
      font-weight: 700;
    }}
    .page-header .meta-inline {{
      font-size: 13px;
      color: #b0b8d1;
      line-height: 1.7;
    }}
    .page-header a {{ color: #7ec8e3; }}
    .content {{ padding: 28px 40px; max-width: 1400px; margin: 0 auto; }}

    /* Summary card */
    .summary-card {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
      gap: 14px;
      margin-bottom: 32px;
    }}
    .card {{
      background: white;
      border-radius: 8px;
      padding: 16px 18px;
      box-shadow: 0 1px 4px rgba(0,0,0,0.08);
      border-top: 3px solid #e94560;
    }}
    .card.green-top {{ border-top-color: #27ae60; }}
    .card.blue-top  {{ border-top-color: #2980b9; }}
    .card.orange-top {{ border-top-color: #e67e22; }}
    .card-label {{ font-size: 11px; color: #888; text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 6px; }}
    .card-value {{ font-size: 26px; font-weight: 700; color: #1a1a2e; }}
    .card-sub   {{ font-size: 11px; color: #aaa; margin-top: 4px; }}

    /* Sections */
    .section {{ margin-bottom: 32px; }}
    .section-title {{
      font-size: 16px;
      font-weight: 700;
      color: #1a1a2e;
      margin: 0 0 12px;
      padding-bottom: 6px;
      border-bottom: 2px solid #e94560;
      display: flex;
      align-items: center;
      gap: 8px;
    }}
    .pill {{
      font-size: 11px;
      background: #e94560;
      color: white;
      border-radius: 12px;
      padding: 2px 8px;
      font-weight: 600;
    }}
    .pill.green {{ background: #27ae60; }}
    .pill.blue  {{ background: #2980b9; }}
    .pill.orange {{ background: #e67e22; }}

    table {{
      border-collapse: collapse;
      width: 100%;
      background: white;
      border-radius: 8px;
      overflow: hidden;
      box-shadow: 0 1px 4px rgba(0,0,0,0.07);
    }}
    th {{
      background: #f0f2f5;
      font-size: 12px;
      font-weight: 600;
      color: #555;
      text-transform: uppercase;
      letter-spacing: 0.04em;
      padding: 10px 12px;
      text-align: left;
      border-bottom: 2px solid #e0e4ea;
    }}
    td {{
      padding: 9px 12px;
      font-size: 13px;
      border-bottom: 1px solid #f0f2f5;
    }}
    tr:last-child td {{ border-bottom: none; }}
    tr:hover td {{ background: #fafbfc; }}

    .note {{
      font-size: 12px;
      color: #888;
      font-style: italic;
      margin-top: 6px;
    }}
    .warning-item {{
      display: flex;
      align-items: center;
      gap: 10px;
      background: #fff8e1;
      border-left: 4px solid #e67e22;
      border-radius: 8px;
      padding: 12px 14px;
      margin-bottom: 10px;
      box-shadow: 0 1px 4px rgba(0,0,0,0.05);
    }}
    .warning-badge {{
      font-size: 10px;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      border-radius: 999px;
      padding: 3px 8px;
      color: white;
      background: #e67e22;
      flex: 0 0 auto;
    }}
    .warning-badge.error {{ background: #c0392b; }}
    .warning-badge.info {{ background: #2980b9; }}
    .warning-message {{
      font-size: 13px;
      color: #1a1a2e;
      flex: 1 1 auto;
    }}
    .warning-code {{
      font-size: 11px;
      color: #888;
      font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
      white-space: nowrap;
    }}
    .warning-empty {{
      background: white;
      border-left: 4px solid #c7cdd8;
      border-radius: 8px;
      padding: 12px 14px;
      color: #666;
      box-shadow: 0 1px 4px rgba(0,0,0,0.05);
    }}
    .warning-empty.ok {{
      border-left-color: #27ae60;
      color: #2d6a4f;
    }}
  </style>
</head>
<body>
  <div class="page-header">
    <h1>CI Stats Report &mdash; PR #{PR}</h1>
    <div class="meta-inline">
      <span><b>SHA:</b> <code>{escape(SHA[:18])}</code></span> &nbsp;|&nbsp;
      <span><b>Run ID:</b> {escape(RUN_ID)}</span> &nbsp;|&nbsp;
      <span><b>Run URL:</b> <a href="{escape(RUN_URL)}" target="_blank">GitHub Actions ↗</a></span><br>
      <span><b>Started:</b> {escape(started)}</span> &nbsp;|&nbsp;
      <span><b>Ended:</b> {escape(ENDED_AT)}</span> &nbsp;|&nbsp;
      <span><b>Duration:</b> {escape(duration_str)}</span> &nbsp;|&nbsp;
      <span><b>Ticks:</b> {len(ticks)}</span> &nbsp;|&nbsp;
      <span><b>Final stage:</b> {escape(str(latest.get('stage', 'unknown')))}</span>
    </div>
  </div>

  <div class="content">

    <!-- ── Summary Card ── -->
    <div class="section">
      <div class="section-title">📊 Run Summary <span class="pill blue">Phase 1</span></div>
      <div class="note" style="display:{'none' if run_summary_data else 'block'};padding:8px 4px">No run summary data available for this run.</div>
      <div class="summary-card" style="display:{'grid' if run_summary_data else 'none'}">
        <div class="card">
          <div class="card-label">Peak /var usage</div>
          <div class="card-value">{escape(summary_peak_var)}</div>
          <div class="card-sub">highest observed during run</div>
        </div>
        <div class="card orange-top">
          <div class="card-label">Peak /opt/sca usage</div>
          <div class="card-value">{escape(summary_peak_opt)}</div>
          <div class="card-sub">highest observed during run</div>
        </div>
        <div class="card">
          <div class="card-label">Max containers</div>
          <div class="card-value">{escape(summary_max_containers)}</div>
          <div class="card-sub">highest concurrent count</div>
        </div>
        <div class="card blue-top">
          <div class="card-label">Max images</div>
          <div class="card-value">{escape(summary_max_images)}</div>
          <div class="card-sub">inventory or latest snapshot</div>
        </div>
        <div class="card">
          <div class="card-label">Max volumes</div>
          <div class="card-value">{escape(summary_max_volumes)}</div>
          <div class="card-sub">inventory or latest snapshot</div>
        </div>
        <div class="card orange-top" style="display:none">
          <div class="card-label">Longest step</div>
          <div class="card-value" style="font-size:14px;padding-top:4px">{escape(biggest_growth_step) if biggest_growth_val > 0 else "—"}</div>
          <div class="card-sub">{escape(summary_longest_step_sub)}</div>
        </div>
        <div class="card green-top" style="display:none">
          <div class="card-label">Biggest cleanup</div>
          <div class="card-value" style="font-size:14px;padding-top:4px">{escape(biggest_cleanup_step) if biggest_cleanup_val < 0 else "—"}</div>
          <div class="card-sub">{str(biggest_cleanup_val) + "% /var" if biggest_cleanup_val < 0 else "n/a"}</div>
        </div>
        <div class="card">
          <div class="card-label">Longest step</div>
          <div class="card-value" style="font-size:14px;padding-top:4px">{escape(summary_longest_step_value)}</div>
          <div class="card-sub">{escape(summary_longest_step_sub)}</div>
        </div>
        <div class="card orange-top">
          <div class="card-label">Largest growth step</div>
          <div class="card-value" style="font-size:14px;padding-top:4px">{escape(summary_growth_value)}</div>
          <div class="card-sub">{escape(summary_growth_sub)}</div>
        </div>
        <div class="card green-top">
          <div class="card-label">Largest cleanup step</div>
          <div class="card-value" style="font-size:14px;padding-top:4px">{escape(summary_cleanup_value)}</div>
          <div class="card-sub">{escape(summary_cleanup_sub)}</div>
        </div>
      </div>
    </div>

    <!-- ── Step Delta Table (Phase 1) ── -->
    <div class="section">
      <div class="section-title">🔬 Step-Level Resource Deltas <span class="pill">Phase 1</span></div>
      <p class="note">Each row shows resource change <b>before → after</b> a major CI step. 🔴 positive = growth, 🟢 negative = freed space.</p>
      <table>
        <thead>
          <tr>
            <th></th>
            <th>Step</th>
            <th>Job</th>
            <th>Duration</th>
            <th>/ Δ</th>
            <th>/var Δ</th>
            <th>/opt/sca Δ</th>
            <th>Containers Δ</th>
            <th>Images Δ</th>
          </tr>
        </thead>
        <tbody>
          {step_delta_rows(step_summaries)}
        </tbody>
      </table>
    </div>

    <!-- ── Phase 2: Missing Workflow Coverage ── -->
    <div class="section">
      <div class="section-title">📋 Workflow Coverage <span class="pill blue">Phase 2</span></div>

      <!-- Tag PR -->
      <div style="margin-bottom:20px">
        <div style="font-size:13px;font-weight:700;color:#444;margin-bottom:8px;padding-left:4px">🏷 Tag PR Images
          <span style="font-size:11px;color:#aaa;font-weight:400"> — {escape(str(tag_pr_data.get('start_time', '')))}</span>
          <span style="font-size:11px;color:#666;font-weight:400"> &nbsp;Total: {fmt_dur(tag_pr_data.get('duration_seconds', 0))}</span>
          <span style="font-size:11px;color:#666;font-weight:400"> &nbsp;Retagged: {escape(str(tag_pr_data.get('images_retagged_count', 0)))}</span>
        </div>
        <table>
          <thead><tr><th>Service</th><th>Source Tag</th><th>Destination Tag</th><th>Start</th><th>End</th><th>Duration</th></tr></thead>
          <tbody>{tag_pr_rows(tag_pr_data)}</tbody>
        </table>
      </div>

      <!-- Preview Up -->
      <div style="margin-bottom:20px">
        <div style="font-size:13px;font-weight:700;color:#444;margin-bottom:8px;padding-left:4px">🚀 Preview Up</div>
        <table>
          <thead><tr><th>Metric</th><th>Value</th></tr></thead>
          <tbody>{preview_up_rows(preview_up_data)}</tbody>
        </table>
      </div>

      <!-- Cleanup -->
      <div style="margin-bottom:20px">
        <div style="font-size:13px;font-weight:700;color:#444;margin-bottom:8px;padding-left:4px">🧹 CI Cleanup</div>
        <table>
          <thead><tr><th>Metric</th><th>Value</th></tr></thead>
          <tbody>{cleanup_rows(cleanup_data)}</tbody>
        </table>
      </div>

      <!-- Failure Diagnostics (only if failure occurred) -->
      {'<div style="margin-bottom:20px"><div style="font-size:13px;font-weight:700;color:#e74c3c;margin-bottom:8px;padding-left:4px">⚠️ Failure Diagnostics</div><table><thead><tr><th>Metric</th><th>Value</th></tr></thead><tbody>' + failure_rows(fail_diag_data) + '</tbody></table></div>' if has_failures else '<div style="color:#888;font-size:12px;font-style:italic;padding:8px 4px">✅ No failures detected — failure diagnostics section not applicable.</div>'}
    </div>

    <div class="section">
      <div class="section-title">&#x1F4C2; Git / PR Context <span class="pill green">Phase 6</span></div>
      <p class="note">Raw source: <code>git-context.json</code>. Captures PR metadata, changed file list, and simple path-based change flags.</p>
      <div style="margin-bottom:20px">
        <div style="font-size:13px;font-weight:700;color:#444;margin-bottom:8px;padding-left:4px">Summary</div>
        <table>
          <tbody>{git_context_summary_rows(git_context_data)}</tbody>
        </table>
      </div>
      <div style="margin-bottom:20px">
        <div style="font-size:13px;font-weight:700;color:#444;margin-bottom:8px;padding-left:4px">Change Flags</div>
        <table>
          <tbody>{git_context_flag_rows(git_context_data)}</tbody>
        </table>
      </div>
      <div style="margin-bottom:20px">
        <div style="font-size:13px;font-weight:700;color:#444;margin-bottom:8px;padding-left:4px">Changed Files</div>
        <table>
          <thead>
            <tr><th>File Path</th></tr>
          </thead>
          <tbody>{git_context_file_rows(git_context_data)}</tbody>
        </table>
      </div>
    </div>

    <div class="section">
      <div class="section-title">&#x1F3D7; Build Breakdown <span class="pill green">Phase 5</span></div>
      <p class="note">Raw source: <code>build-summary.json</code>. Splits per-service image build time from push time.</p>
      <table>
        <thead>
          <tr><th>Service</th><th>Build Duration</th><th>Push Duration</th><th>Final Image Size</th><th>Build Start</th><th>Build End</th><th>Push Start</th><th>Push End</th></tr>
        </thead>
        <tbody>
          {build_breakdown_rows(build_summary_data)}
        </tbody>
      </table>
    </div>

    <div class="section">
      <div class="section-title">🧪 Test Breakdown <span class="pill green">Phase 5</span></div>
      <p class="note">Raw source: <code>test-summary.json</code>. Breaks test time into environment bring-up, waits, Playwright, and teardown.</p>
      <table>
        <thead>
          <tr><th>Step</th><th>Start</th><th>End</th><th>Duration</th></tr>
        </thead>
        <tbody>
          {test_breakdown_rows(test_summary_data)}
        </tbody>
      </table>
      {f'<p class="note">{test_breakdown_summary_note}</p>' if test_breakdown_summary_note else ''}
    </div>

    <div class="section">
      <div class="section-title">🚀 Preview-Up Breakdown <span class="pill green">Phase 5</span></div>
      <p class="note">Raw source: <code>preview-step-breakdown.json</code>. Highlights sync, pull, compose up, health waits, and seed loading.</p>
      <table>
        <thead>
          <tr><th>Step</th><th>Duration</th></tr>
        </thead>
        <tbody>
          {preview_step_breakdown_rows(preview_step_breakdown_data)}
        </tbody>
      </table>
    </div>

    <!-- ── Latest Filesystem Usage ── -->
    <div class="section">
      <div class="section-title">💾 Latest Filesystem Usage</div>
      <table>
        <thead>
          <tr><th>Mount</th><th>Usage</th><th>Used</th><th>Available</th><th style='color:#888'>Total</th></tr>
        </thead>
        <tbody>
          {fs_rows(latest_fs)}
        </tbody>
      </table>
    </div>

    <!-- ── Docker Summary ── -->
    <div class="section">
      <div class="section-title">🐳 Latest Docker Summary</div>
      <table>
        <tbody>
          <tr><th>Images</th><td>{escape(str(latest_df.get('images_total','?')))}</td><th>Reclaimable</th><td>{escape(str(latest_df.get('images_reclaimable','?')))}</td></tr>
          <tr><th>Containers</th><td>{escape(str(latest_df.get('containers_total','?')))}</td><th>Reclaimable</th><td>{escape(str(latest_df.get('containers_reclaimable','?')))}</td></tr>
          <tr><th>Volumes</th><td>{escape(str(latest_df.get('volumes_total','?')))}</td><th>Reclaimable</th><td>{escape(str(latest_df.get('volumes_reclaimable','?')))}</td></tr>
          <tr><th>Build Cache</th><td>{escape(str(latest_df.get('build_cache_total','?')))}</td><th>Reclaimable</th><td>{escape(str(latest_df.get('build_cache_reclaimable','?')))}</td></tr>
        </tbody>
      </table>
    </div>

    <!-- ── Latest Containers ── -->
    <div class="section">
      <div class="section-title">📦 Latest Containers <span class="pill blue">{len(latest_containers)}</span></div>
      <table>
        <thead>
          <tr><th>Name</th><th>CPU</th><th>RAM</th><th>Status</th></tr>
        </thead>
        <tbody>
          {container_rows(latest_containers)}
        </tbody>
      </table>
    </div>

    <!-- ── Xenium Images ── -->
    <div class="section">
      <div class="section-title">🖼 Latest Xenium Images <span class="pill blue">{len(latest_images)}</span></div>
      <table>
        <thead>
          <tr><th>Repository</th><th>Tag</th><th>Size</th></tr>
        </thead>
        <tbody>
          {image_rows(latest_images)}
        </tbody>
      </table>
    </div>

    <!-- ── Timeline ── -->
    <div class="section">
      <div class="section-title">⏱ Timeline <span class="pill blue">{len(ticks)} ticks</span></div>
      <p class="note">Sampled every 10 seconds. /var values ≥65% highlighted orange, ≥75% highlighted red.</p>
      <table>
        <thead>
          <tr><th>Tick</th><th>Timestamp</th><th>Stage</th><th>/</th><th>/var</th><th>/opt/sca</th><th>Containers</th></tr>
        </thead>
        <tbody>
          {"".join(timeline_rows) or "<tr><td colspan='7'>No timeline data</td></tr>"}
        </tbody>
      </table>
    </div>

    <div class="section">
      <div class="section-title">Docker Image Inventory <span class="pill blue">{len(docker_inventory_rows)}</span></div>
      <p class="note">Raw source: <code>docker-images.json</code>. Ordered by current PR images first, then current SHA matches, then remaining Xenium images. Showing up to 25 rows.</p>
      <table>
        <thead>
          <tr><th>Repository</th><th>Tag</th><th>Image ID</th><th>Digest</th><th>Created</th><th>Size</th><th>Current PR?</th><th>Current SHA?</th></tr>
        </thead>
        <tbody>
          {inventory_image_rows(docker_inventory_rows)}
        </tbody>
      </table>
      <p class="note">Captured at: {escape(str(docker_image_inventory.get("captured_at", "unknown")))}</p>
    </div>

    <div class="section">
      <div class="section-title">Docker Container Inventory <span class="pill blue">{len(docker_container_rows)}</span></div>
      <p class="note">Raw source: <code>docker-containers.json</code>. Ordered by current preview stack containers first, then current test stack containers, then remaining containers. Showing up to 30 rows.</p>
      <table>
        <thead>
          <tr><th>Name</th><th>Container ID</th><th>Image</th><th>Status</th><th>Size</th><th>Created At</th><th>Preview Stack?</th><th>Test Stack?</th></tr>
        </thead>
        <tbody>
          {inventory_container_rows(docker_container_rows)}
        </tbody>
      </table>
      <p class="note">Captured at: {escape(str(docker_container_inventory.get("captured_at", "unknown")))}</p>
    </div>

    <div class="section">
      <div class="section-title">Docker Volume Inventory <span class="pill blue">{len(docker_volume_rows)}</span></div>
      <p class="note">Raw source: <code>docker-volumes.json</code>. Ordered by preview-related volumes first. Showing up to 30 rows.</p>
      <table>
        <thead>
          <tr><th>Volume Name</th><th>Driver</th><th>Mountpoint</th><th>Preview Stack?</th><th>Labels</th></tr>
        </thead>
        <tbody>
          {inventory_volume_rows(docker_volume_rows)}
        </tbody>
      </table>
      <p class="note">Captured at: {escape(str(docker_volume_inventory.get("captured_at", "unknown")))}</p>
    </div>

    <div class="section">
      <div class="section-title">Cleanup Forensics <span class="pill blue">Phase 3</span></div>
      <p class="note">Raw source: <code>docker-dangling-summary.json</code>. Compact view of currently unused Docker objects that cleanup may reclaim.</p>
      <table>
        <thead>
          <tr><th>Metric</th><th>Value</th></tr>
        </thead>
        <tbody>
          {dangling_summary_rows(docker_dangling_summary)}
        </tbody>
      </table>
      <p class="note">Captured at: {escape(str(docker_dangling_summary.get("captured_at", "unknown")))}</p>
    </div>

    <div class="section">
      <div class="section-title">Build Cache Details <span class="pill blue">Phase 3</span></div>
      <p class="note">Raw source: <code>docker-build-cache.json</code>. Summary values are always shown when available; detailed entries appear only if the runner exposes build cache detail data.</p>
      <table>
        <thead>
          <tr><th>Metric</th><th>Value</th></tr>
        </thead>
        <tbody>
          {build_cache_summary_rows(docker_build_cache)}
        </tbody>
      </table>
      <table style="margin-top:12px">
        <thead>
          <tr><th>ID</th><th>Description</th><th>Size</th><th>Reclaimable?</th><th>Shared?</th></tr>
        </thead>
        <tbody>
          {build_cache_entry_rows(docker_build_cache_entries)}
        </tbody>
      </table>
      <p class="note">Captured at: {escape(str(docker_build_cache.get("captured_at", "unknown")))}</p>
    </div>

    <!-- ── Phase 4: Directory Sizes ── -->
    <div class="section">
      <div class="section-title">&#x1F4C1; Directory Sizes <span class="pill blue">Phase 4</span></div>
      <p class="note">Raw source: <code>directory-sizes.ndjson</code>. Sizes measured at the last watcher tick via <code>du -sk -x</code>. Docker paths may show tiny values if the runner user cannot traverse <code>/var/lib/docker</code>.</p>
      <table>
        <thead>
          <tr><th>Directory</th><th>Path</th><th>Size</th></tr>
        </thead>
        <tbody>
          {directory_sizes_section_rows(directory_sizes_latest)}
        </tbody>
      </table>
      <p class="note">Tick {escape(str(directory_sizes_latest.get('tick', '—')))} &nbsp;|&nbsp; Stage: {escape(str(directory_sizes_latest.get('stage', '—')))} &nbsp;|&nbsp; Captured at: {escape(str(directory_sizes_latest.get('timestamp', 'unknown')))}</p>
    </div>

    <!-- ── Phase 4: Inode Usage ── -->
    <div class="section">
      <div class="section-title">&#x1F5C2; Inode Usage <span class="pill blue">Phase 4</span></div>
      <p class="note">Raw source: <code>inode-usage.ndjson</code>. Three rows per tick, one per monitored mount. This tracks inode/file-entry capacity, not storage bytes. Orange &ge;65%, red &ge;80%.</p>
      <table>
        <thead>
          <tr><th>Path requested</th><th>Filesystem</th><th>Mount</th><th>Inode Usage</th><th>Used</th><th>Total</th></tr>
        </thead>
        <tbody>
          {inode_usage_section_rows(inode_usage_latest)}
        </tbody>
      </table>
      <p class="note">{escape(inode_usage_note)}</p>
    </div>

    <!-- ── Phase 4: Host Stats ── -->
    <div class="section">
      <div class="section-title">&#x1F5A5; Host Stats <span class="pill blue">Phase 4</span></div>
      <p class="note">Raw source: <code>host-stats.ndjson</code>. Memory values in KB from <code>/proc/meminfo</code>; load averages from <code>/proc/loadavg</code>. Memory bar orange &ge;75%, red &ge;90%.</p>
      <table>
        <tbody>
          {host_stats_section_rows(host_stats_latest)}
        </tbody>
      </table>
      <p class="note">Tick {escape(str(host_stats_latest.get('tick', '—')))} &nbsp;|&nbsp; Stage: {escape(str(host_stats_latest.get('stage', '—')))} &nbsp;|&nbsp; Captured at: {escape(str(host_stats_latest.get('timestamp', 'unknown')))}</p>
    </div>

  </div>
</body>
</html>
"""

warnings_section_block = (
    "\n"
    '    <div class="section">\n'
    '      <div class="section-title">⚠️ Warnings <span class="pill orange">Phase 8</span></div>\n'
    f"      {warnings_section_html}\n"
    "    </div>\n"
)
summary_end_marker = (
    f'          <div class="card-sub">{escape(summary_cleanup_sub)}</div>\n'
    "        </div>\n"
    "      </div>\n"
    "    </div>"
)
if summary_end_marker in html:
    html = html.replace(summary_end_marker, summary_end_marker + warnings_section_block, 1)

REPORT_FILE.write_text(html, encoding="utf-8")
sync_structured_artifacts()

meta.update({
    **artifact_versions(),
    "ended": ENDED_AT,
    "duration": duration_str,
    "ticks": len(ticks),
    "step_summaries_count": len(step_summaries),
    "docker_images_count": len(docker_inventory_rows),
    "docker_containers_count": len(docker_container_rows),
    "docker_volumes_count": len(docker_volume_rows),
    "docker_dangling_summary_present": bool(docker_dangling_summary),
    "docker_build_cache_entries_count": len(docker_build_cache_entries),
    "directory_sizes_ticks": len(directory_sizes_rows_data),
    "inode_usage_rows": len(inode_usage_rows_data),
    "host_stats_ticks": len(host_stats_rows_data),
    "phase4_present": safe_bool(directory_sizes_rows_data or inode_usage_rows_data or host_stats_rows_data),
    "git_context_present": safe_bool(git_context_data),
    "run_summary_present": safe_bool(resolve_artifact_path("run-summary.json", "derived").exists()),
    "cleanup_effectiveness_present": safe_bool(resolve_artifact_path("cleanup-effectiveness.json", "derived").exists()),
    "warnings_present": safe_bool(resolve_artifact_path("warnings.json", "derived").exists()),
    "artifact_layout": "hybrid",
    "artifact_presence": artifact_presence_map(ARTIFACT_FILES),
    "raw_data_files": list_raw_files(),
    "derived_data_files": list_derived_files(),
    "report_version": "phase6",
})
META_FILE.write_text(json.dumps(meta, indent=2), encoding="utf-8")

print(f"[generate_report] Report written to {REPORT_FILE}")
print(f"[generate_report] {len(ticks)} timeline ticks, {len(step_summaries)} step summaries")
