# Task 04 - Add Track Mode

task_completed: true

## Goal

Implement `mode: track` so users can track a named GitHub Actions step with selected metrics and minimal YAML.

## Why This Is Needed

This is the core v1 product behavior. It turns the current local wrapper pattern into a reusable action interface.

## Work To Do

- Wrap the existing tracked-step behavior behind the action interface.
- Support required inputs:
  - `job-id`
  - `step-name`
  - `stats-dir`
- Support a command execution pattern that works cleanly in GitHub Actions.
- Ensure tracked steps still run even if watcher logic fails.
- Keep begin/end capture around the selected step.
- Preserve current report compatibility for step summaries and deltas.

## Open Design Question

GitHub Actions cannot automatically inject into another existing step. For v1, decide the exact UX for tracked execution, for example:

- the action itself runs the target command
- or the action exposes pre/post calls that users place around a command

## Definition Of Done

- Users can track a named step through the action without directly calling local shell scripts.
- The tracked step produces before/after stats in the existing artifact model.

## Completed Work

- Chose the v1 UX as:
  - the action itself runs the target command
- Added `command` and `working-directory` inputs in [action.yml](</abs/path/C:/Users/Karthiek%20Duggirala/Documents/sca/ci-stats-watcher-final/action.yml>) for `mode: track`.
- Added [action/mode_track.sh](</abs/path/C:/Users/Karthiek%20Duggirala/Documents/sca/ci-stats-watcher-final/action/mode_track.sh>) to:
  - load watcher runtime state when available
  - set the current stage file
  - call `mark_step.sh begin`
  - run the tracked command
  - call `mark_step.sh end`
  - return the tracked command exit code
- Updated [action/dispatch.sh](</abs/path/C:/Users/Karthiek%20Duggirala/Documents/sca/ci-stats-watcher-final/action/dispatch.sh>) so `track` is now a real runtime mode instead of a placeholder.
- Updated [ACTION_INTERFACE.md](</abs/path/C:/Users/Karthiek%20Duggirala/Documents/sca/ci-stats-watcher-final/ACTION_INTERFACE.md>) to document the tracked-command UX.

## Notes

- This task preserves the existing artifact model by continuing to use `mark_step.sh` step records.
- The `metrics` input is carried through the public interface, but per-step metric selection is still a separate Task 06.
