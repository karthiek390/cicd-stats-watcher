#!/usr/bin/env python3
"""Validate watcher-manifest.yaml against generated-ci-inventory.yaml."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import yaml


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_INVENTORY = SCRIPT_DIR / "generated-ci-inventory.yaml"
DEFAULT_MANIFEST = SCRIPT_DIR / "watcher-manifest.yaml"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate a watcher manifest against a generated CI inventory."
    )
    parser.add_argument(
        "--inventory",
        default=str(DEFAULT_INVENTORY),
        help="Path to generated CI inventory YAML.",
    )
    parser.add_argument(
        "--manifest",
        default=str(DEFAULT_MANIFEST),
        help="Path to watcher manifest YAML.",
    )
    return parser.parse_args()


def load_yaml(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} did not parse into a mapping.")
    return data


def inventory_index(inventory: dict[str, Any]) -> dict[str, dict[str, Any]]:
    jobs = inventory.get("jobs")
    if not isinstance(jobs, list):
        raise ValueError("Inventory is missing a jobs list.")

    index: dict[str, dict[str, Any]] = {}
    for job in jobs:
        if not isinstance(job, dict):
            continue
        job_id = job.get("job_id")
        if not isinstance(job_id, str) or not job_id:
            continue
        index[job_id] = job
    return index


def manifest_jobs(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    jobs = manifest.get("jobs")
    if not isinstance(jobs, list):
        raise ValueError("Manifest is missing a jobs list.")
    return [job for job in jobs if isinstance(job, dict)]


def validate(inventory: dict[str, Any], manifest: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    inventory_jobs = inventory_index(inventory)
    manifest_job_rows = manifest_jobs(manifest)

    manifest_inventory = manifest.get("inventory")
    if isinstance(manifest_inventory, dict):
        manifest_workflow = manifest_inventory.get("workflow")
        inventory_workflow = inventory.get("workflow")
        if manifest_workflow != inventory_workflow:
            errors.append(
                "Manifest workflow does not match inventory workflow: "
                f"manifest={manifest_workflow!r}, inventory={inventory_workflow!r}"
            )

        manifest_sha = manifest_inventory.get("workflow_sha256")
        inventory_sha = inventory.get("workflow_sha256")
        if manifest_sha != inventory_sha:
            errors.append(
                "Manifest workflow_sha256 does not match inventory workflow_sha256: "
                f"manifest={manifest_sha!r}, inventory={inventory_sha!r}"
            )

    manifest_job_ids = []
    for job in manifest_job_rows:
        job_id = job.get("job_id")
        if not isinstance(job_id, str) or not job_id:
            errors.append("Manifest contains a job entry with no valid job_id.")
            continue

        manifest_job_ids.append(job_id)
        inventory_job = inventory_jobs.get(job_id)
        if inventory_job is None:
            errors.append(f"Unknown manifest job_id: {job_id}")
            continue

        inventory_steps = inventory_job.get("steps")
        inventory_step_names = {
            step.get("name")
            for step in inventory_steps
            if isinstance(step, dict) and isinstance(step.get("name"), str)
        }

        raw_steps = job.get("steps", [])
        if not isinstance(raw_steps, list):
            errors.append(f"Manifest job {job_id} has a non-list steps field.")
            continue

        for step in raw_steps:
            if not isinstance(step, dict):
                errors.append(f"Manifest job {job_id} has a non-mapping step entry.")
                continue
            step_name = step.get("name")
            if not isinstance(step_name, str) or not step_name:
                errors.append(f"Manifest job {job_id} has a step with no valid name.")
                continue
            if step_name not in inventory_step_names:
                errors.append(
                    f"Unknown step for job {job_id}: {step_name}"
                )

    inventory_job_ids = list(inventory_jobs.keys())
    missing_jobs = [job_id for job_id in inventory_job_ids if job_id not in manifest_job_ids]
    if missing_jobs:
        errors.append(
            "Manifest is missing job_id entries for: " + ", ".join(missing_jobs)
        )

    return errors


def main() -> int:
    args = parse_args()
    inventory_path = Path(args.inventory).resolve()
    manifest_path = Path(args.manifest).resolve()

    try:
        inventory = load_yaml(inventory_path)
        manifest = load_yaml(manifest_path)
        errors = validate(inventory, manifest)
    except Exception as exc:
        print(f"Validation failed to run: {exc}", file=sys.stderr)
        return 2

    if errors:
        print("Watcher manifest validation failed:")
        for error in errors:
            print(f"- {error}")
        return 1

    print("Watcher manifest validation passed.")
    print(f"Inventory: {inventory_path}")
    print(f"Manifest:  {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
