# Task 06 - Support Per-Step Metric Selection

task_completed: true

## Goal

Let users choose what to track for each named step, such as disk, CPU, memory, inode, and Docker-related metrics.

## Why This Is Needed

This is part of the intended v1 product experience and keeps the action flexible without forcing all metrics on all steps.

## Work To Do

- Review current metric toggles in `watcher-manifest.yaml` and related scripts.
- Define the public input format for metrics, such as:
  - comma-separated values
  - YAML list
  - manifest-only configuration
- Make sure `track` mode can pass metric selections into the runtime.
- Support step-level overrides on top of any global defaults.
- Validate unknown or unsupported metric names with clear messages.
- Confirm the report handles partial metric collection gracefully.

## Definition Of Done

- Users can select metrics per tracked step.
- The runtime respects those selections.
- The report stays correct even when only a subset of metrics is enabled.

## Completed Work

- Updated [tools/ci-watcher/run_tracked_step.sh](</abs/path/C:/Users/Karthiek%20Duggirala/Documents/sca/ci-stats-watcher-final/tools/ci-watcher/run_tracked_step.sh>) to:
  - resolve metric settings from either the public `metrics` input or the manifest
  - validate supported metric names
  - export the effective metric selection into the step runtime
- Updated [tools/ci-watcher/mark_step.sh](</abs/path/C:/Users/Karthiek%20Duggirala/Documents/sca/ci-stats-watcher-final/tools/ci-watcher/mark_step.sh>) so tracked step snapshots can now selectively collect:
  - `storage`
  - `docker`
  - `cpu`
  - `memory`
  - `inode`
- Updated [action/mode_track.sh](</abs/path/C:/Users/Karthiek%20Duggirala/Documents/sca/ci-stats-watcher-final/action/mode_track.sh>) so the public `metrics` input is passed into the tracked-step runtime.
- Updated [ACTION_INTERFACE.md](</abs/path/C:/Users/Karthiek%20Duggirala/Documents/sca/ci-stats-watcher-final/ACTION_INTERFACE.md>) to document supported metric names.

## Notes

- The action-level `metrics` input currently acts as the step-level override.
- When no explicit `metrics` input is supplied, the runtime falls back to manifest/default metric settings.
- The report generator already tolerates missing step fields, so partial metric collection remains compatible.
