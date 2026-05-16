# Task 03 - Add Start Mode

task_completed: true

## Goal

Implement `mode: start` so users can initialize the watcher with one action step near the beginning of a workflow or job.

## Why This Is Needed

The current bootstrap logic is spread across the workflow and includes metadata creation, stats directory setup, watcher startup, and optional stage-file setup. Users should not have to copy that manually.

## Work To Do

- Move bootstrap responsibilities out of the sample workflow and into the action runtime.
- Support creating a per-run stats directory automatically.
- Accept GitHub metadata from the action environment:
  - run id
  - repository
  - sha
  - job context inputs
- Write `meta.json` in a stable format.
- Start the watcher background process safely.
- Optionally start the live server if v1 still wants that behavior.
- Emit outputs needed by later steps, especially the resolved stats directory.

## Definition Of Done

- One `uses:` step can start the watcher without users copying bootstrap shell code.
- The stats directory and metadata are created automatically.
- Later action steps can reuse the resulting state.

## Completed Work

- Added [action/mode_start.sh](</abs/path/C:/Users/Karthiek%20Duggirala/Documents/sca/ci-stats-watcher-final/action/mode_start.sh>) to implement real `mode: start` behavior.
- Updated [action/dispatch.sh](</abs/path/C:/Users/Karthiek%20Duggirala/Documents/sca/ci-stats-watcher-final/action/dispatch.sh>) so:
  - `start` executes the bootstrap runtime
  - `track` and `finalize` remain placeholders for the next tasks
- Updated [action.yml](</abs/path/C:/Users/Karthiek%20Duggirala/Documents/sca/ci-stats-watcher-final/action.yml>) to expose new outputs:
  - `meta-path`
  - `state-path`
  - `stage-file`
  - `watcher-pid`
  - `server-pid`
- Updated [tools/ci-watcher/watcher.sh](</abs/path/C:/Users/Karthiek%20Duggirala/Documents/sca/ci-stats-watcher-final/tools/ci-watcher/watcher.sh>) to accept a stage-file override through `CI_STATS_STAGE_FILE`.

## Notes

- `mode: start` now:
  - resolves a stats directory
  - writes `meta.json`
  - writes `watcher-runtime-state.json`
  - creates a stage file
  - starts the watcher in the background
  - optionally starts the live server when `run-server=true`
- `mode: track` and `mode: finalize` are still pending in Tasks 04 and 05.
