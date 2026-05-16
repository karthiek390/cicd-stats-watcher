# CICD Stats Watcher Release Tasks

This folder tracks the work needed to turn the current `tools/ci-watcher/` implementation into a GitHub Actions-first product based on:

- `uses: karthiek390/cicd-stats-watcher@v1`
- named GitHub Actions step tracking
- per-step metric selection
- start / track / finalize workflow modes

Each task file has:

- `task_completed: true` for completed tasks in this repo
- a goal
- the concrete changes needed
- a definition of done

Current task files:

- `01_extract_core_runtime.md`
- `02_publish_github_action_interface.md`
- `03_add_start_mode.md`
- `04_add_track_mode.md`
- `05_add_finalize_mode.md`
- `06_support_per_step_metric_selection.md`
- `07_remove_repo_local_path_assumptions.md`
- `08_add_docs_and_examples.md`
- `09_add_validation_and_release_checks.md`
