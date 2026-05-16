# Task 01 - Extract Core Runtime

task_completed: true

## Goal

Separate the reusable watcher engine from the current repo-local workflow assumptions so the implementation can be called through a stable GitHub Action interface.

## Why This Is Needed

Today the watcher works because the target repo contains `tools/ci-watcher/` and the workflow directly calls local scripts. That is fine for an internal reference repo, but not for a `uses:`-based release.

## Work To Do

- Identify which files are true runtime core:
  - `watcher.sh`
  - `mark_step.sh`
  - `run_tracked_step.sh`
  - `capture_system_snapshot.sh`
  - `generate_report.py`
  - `serve.py`
- Identify which files are GitHub Actions adapter logic:
  - `extract_ci_inventory.py`
  - `validate_watcher_manifest.py`
  - `watcher-manifest.yaml`
  - `generated-ci-inventory.yaml`
- Identify which files are still project-specific helpers and should not be part of v1 public action behavior.
- Define a clean internal runtime layout that the action can call without requiring the user's repo to contain `tools/ci-watcher/`.

## Definition Of Done

- Core runtime files are clearly separated from adapter-specific files.
- Action entrypoints can invoke the runtime without depending on user-repo-relative paths.
- Project-specific helpers are excluded from the main release path.

## Completed Work

- Added [tools/ci-watcher/RELEASE_RUNTIME_BOUNDARY.md](</abs/path/C:/Users/Karthiek%20Duggirala/Documents/sca/ci-stats-watcher-final/tools/ci-watcher/RELEASE_RUNTIME_BOUNDARY.md>) to define:
  - reusable core runtime files
  - GitHub Actions adapter files
  - project-specific helpers excluded from the public v1 path
  - the intended future internal action bundle layout
- Added [tools/ci-watcher/release-runtime-layout.json](</abs/path/C:/Users/Karthiek%20Duggirala/Documents/sca/ci-stats-watcher-final/tools/ci-watcher/release-runtime-layout.json>) as a machine-readable classification file for later packaging tasks.

## Notes

- This task defines the release boundary and target layout.
- It does not yet publish the GitHub Action interface.
- Removing repo-local runtime path assumptions is still tracked separately in Task 07.
