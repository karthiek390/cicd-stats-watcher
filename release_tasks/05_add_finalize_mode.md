# Task 05 - Add Finalize Mode

task_completed: true

## Goal

Implement `mode: finalize` so users can generate the final report and stop background processes with one action step.

## Why This Is Needed

The current finalization logic is also embedded in the sample workflow. That should move into the public action so users do not have to copy report-generation and cleanup shell blocks.

## Work To Do

- Move final report generation into the action runtime.
- Stop watcher-related background processes safely.
- Support one last polling delay if needed before final capture.
- Generate `report.html` and all current artifact outputs.
- Return the final stats/report location as outputs.
- Keep behavior safe when start mode did not run or when upstream steps failed.

## Definition Of Done

- One `uses:` step can finalize the watcher and generate the artifact.
- Finalization remains safe under `if: always()` workflow usage.

## Completed Work

- Added [action/mode_finalize.sh](</abs/path/C:/Users/Karthiek%20Duggirala/Documents/sca/ci-stats-watcher-final/action/mode_finalize.sh>) to implement real `mode: finalize` behavior.
- Updated [action/dispatch.sh](</abs/path/C:/Users/Karthiek%20Duggirala/Documents/sca/ci-stats-watcher-final/action/dispatch.sh>) so `finalize` is now a real runtime mode instead of a placeholder.
- Updated [action.yml](</abs/path/C:/Users/Karthiek%20Duggirala/Documents/sca/ci-stats-watcher-final/action.yml>) to expose finalize outputs:
  - `finalized`
  - `generated-report`
- Updated [ACTION_INTERFACE.md](</abs/path/C:/Users/Karthiek%20Duggirala/Documents/sca/ci-stats-watcher-final/ACTION_INTERFACE.md>) to document that finalize now completes the watcher lifecycle.

## Notes

- `mode: finalize` now:
  - loads watcher runtime state when present
  - marks the pipeline as complete
  - waits for one last watcher tick
  - runs `generate_report.py`
  - stops watcher and server background processes
  - safely skips when start mode never ran
