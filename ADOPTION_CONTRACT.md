# CICD Stats Watcher Adoption Contract

This document defines the minimum contract for adopting `cicd-stats-watcher` in another self-hosted GitHub Actions project.

## Goal

Adopt the watcher with the smallest possible GitHub Actions integration surface:

- start the watcher near the beginning of the workflow
- track selected named steps with a simple `uses:` call
- generate the final report near the end of the workflow

## Public Adoption Model

The intended public model is:

- `uses: karthiek390/cicd-stats-watcher@v1`

That means the adopting repo does not need to copy the bundled watcher runtime into its own workspace.

The action carries its own implementation and resolves internal scripts relative to the action bundle.

## Workflow Integration

The minimum workflow integration has three parts.

### 1. Start

Early in the workflow, call:

- `mode: start`

Current responsibilities handled by the action:

- resolve a per-run `stats-dir`
- write `meta.json`
- write runtime state
- create the internal stage file
- start `watcher.sh` in the background

### 2. Optional Step Tracking

For any named step you want detailed before/after stats for, call:

- `mode: track`

Required public inputs:

- `job-id`
- `step-name`
- `command`

Optional inputs:

- `stats-dir`
- `metrics`
- `working-directory`
- `manifest-path`

The action runs the tracked command itself and records begin/end step data around it.

### 3. Finalize

Near the end of the workflow, call:

- `mode: finalize`

Current responsibilities handled by the action:

- mark the pipeline complete
- give the watcher time for a last tick
- run `generate_report.py`
- stop watcher/server background processes
- leave the final stats directory ready for artifact upload or later publishing

## Manifest Location Expectations

Current default expectation inside the action bundle:

- bundled `watcher-manifest.yaml`

Current inventory expectation inside the action bundle:

- bundled `generated-ci-inventory.yaml`

Recommended workflow when the CI file changes:

1. Regenerate the inventory with `extract_ci_inventory.py`
2. Update the manifest if job ids or named steps changed
3. Run `validate_watcher_manifest.py`

## Runner Assumptions

The current watcher assumes a self-hosted Linux-style runner environment.

Expected capabilities:

- `bash`
- `python3`
- `docker`
- standard Unix tools like `df`, `awk`, `grep`, `sed`, `wc`, `find`

Expected runtime behavior:

- the runner can launch long-lived background processes
- the runner allows writing under `/tmp`
- the runner can inspect Docker state

## Artifact Expectations

At minimum, a run should produce a stats directory containing:

- `meta.json`
- `timeline.ndjson`
- `snapshot.json`
- `report.html`

Optional richer outputs may also appear:

- `step-summaries.json`
- `docker-images.json`
- `docker-volumes.json`
- `docker-containers.json`
- `docker-build-cache.json`
- `directory-sizes.ndjson`
- `inode-usage.ndjson`
- `host-stats.ndjson`
- `run-summary.json`
- `warnings.json`

## Naming and Identity Expectations

The current implementation works best when a run can provide:

- a PR number or similar review identifier
- a commit SHA
- a run URL
- a stable per-run stats directory

If a project does not use pull requests, another stable run key can replace the PR number.

## Live View Expectations

The current design still assumes:

- watcher startup remains explicit in the workflow
- watcher shutdown remains explicit in the workflow
- live serving is separate from final report generation

Projects that do not want a live page can still adopt the artifact/report side only.

## Minimal Adoption Checklist

1. Add `uses: karthiek390/cicd-stats-watcher@v1` with `mode: start`.
2. Add one or more `mode: track` steps for important named commands.
3. Add `mode: finalize` under `if: always()`.
4. Optionally override `stats-dir` or `manifest-path` if your repo needs custom behavior.
5. Confirm `report.html` and the stats artifact are produced successfully.
