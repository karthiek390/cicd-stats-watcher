# Task 08 - Add Docs And Examples

task_completed: true

## Goal

Document the GitHub Actions-first adoption path with examples that match the new `uses:` interface.

## Why This Is Needed

Once the action interface exists, the current README and adoption guidance will no longer match the easiest installation path.

## Work To Do

- Rewrite `README.md` around the GitHub Action release model.
- Add a minimal example using:
  - start
  - one tracked named step
  - finalize
- Add an example showing per-step metric selection.
- Explain self-hosted Linux runner prerequisites.
- Explain what v1 supports:
  - named step tracking
  - GitHub Actions only
- Explain what is deferred:
  - line-level markers inside a single `run:` block
  - non-GitHub CI systems

## Definition Of Done

- A new user can adopt the project by following the README alone.
- Examples reflect the public action interface instead of local script calls.

## Completed Work

- Expanded [README.md](</abs/path/C:/Users/Karthiek%20Duggirala/Documents/sca/ci-stats-watcher-final/README.md>) with:
  - a fuller workflow example
  - per-step metric examples
  - explicit `v1` support boundaries
  - explicit deferred items
- Expanded [ACTION_INTERFACE.md](</abs/path/C:/Users/Karthiek%20Duggirala/Documents/sca/ci-stats-watcher-final/ACTION_INTERFACE.md>) with:
  - a practical workflow example
  - deferred items for later phases

## Notes

- The docs now center the `uses:` interface rather than local script calls.
- The README now gives a new GitHub Actions user enough information to start with the action directly.
