#!/usr/bin/env python3
"""Extract a deterministic inventory of jobs and named steps from a workflow."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
from typing import Any

import yaml


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_WORKFLOW = SCRIPT_DIR.parent.parent / ".github" / "workflows" / "CI.yml"
DEFAULT_OUTPUT = SCRIPT_DIR / "generated-ci-inventory.yaml"
SCHEMA_VERSION = 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract a normalized inventory from a GitHub Actions workflow."
    )
    parser.add_argument(
        "workflow",
        nargs="?",
        default=str(DEFAULT_WORKFLOW),
        help="Path to the source workflow YAML file.",
    )
    parser.add_argument(
        "output",
        nargs="?",
        default=str(DEFAULT_OUTPUT),
        help="Path to write the generated inventory YAML file.",
    )
    return parser.parse_args()


def load_workflow(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Workflow at {path} did not parse into a mapping.")
    return data


def relpath_or_name(path: Path, start: Path) -> str:
    try:
        return path.relative_to(start).as_posix()
    except ValueError:
        return path.name


def normalize_jobs(workflow: dict[str, Any]) -> list[dict[str, Any]]:
    jobs = workflow.get("jobs")
    if not isinstance(jobs, dict):
        raise ValueError("Workflow does not contain a top-level jobs mapping.")

    normalized: list[dict[str, Any]] = []
    for job_id, job_value in jobs.items():
        if not isinstance(job_value, dict):
            continue

        job_name = job_value.get("name")
        raw_steps = job_value.get("steps")
        steps: list[dict[str, str]] = []

        if isinstance(raw_steps, list):
            for raw_step in raw_steps:
                if not isinstance(raw_step, dict):
                    continue
                step_name = raw_step.get("name")
                if not isinstance(step_name, str) or not step_name.strip():
                    continue

                step_entry: dict[str, str] = {"name": step_name}
                step_id = raw_step.get("id")
                if isinstance(step_id, str) and step_id.strip():
                    step_entry["id"] = step_id
                steps.append(step_entry)

        normalized.append(
            {
                "job_id": str(job_id),
                "job_name": job_name if isinstance(job_name, str) and job_name.strip() else None,
                "steps": steps,
            }
        )

    return normalized


def build_inventory(workflow_path: Path, workflow: dict[str, Any]) -> dict[str, Any]:
    repo_root = SCRIPT_DIR.parent.parent
    source_text = workflow_path.read_text(encoding="utf-8")

    return {
        "schema_version": SCHEMA_VERSION,
        "workflow": relpath_or_name(workflow_path.resolve(), repo_root.resolve()),
        "workflow_sha256": hashlib.sha256(source_text.encode("utf-8")).hexdigest(),
        "job_count": len(workflow.get("jobs", {})) if isinstance(workflow.get("jobs"), dict) else 0,
        "jobs": normalize_jobs(workflow),
    }


def dump_yaml(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=False),
        encoding="utf-8",
    )


def main() -> int:
    args = parse_args()
    workflow_path = Path(args.workflow).resolve()
    output_path = Path(args.output).resolve()

    workflow = load_workflow(workflow_path)
    inventory = build_inventory(workflow_path, workflow)
    dump_yaml(output_path, inventory)

    print(f"Wrote CI inventory to {output_path}")
    print(f"Jobs: {len(inventory['jobs'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
