# Task 02 - Publish GitHub Action Interface

task_completed: true

## Goal

Create the public GitHub Actions interface so adopters can use the project with:

`uses: karthiek390/cicd-stats-watcher@v1`

## Why This Is Needed

This is the main change that removes the need for users to copy the `tools/` folder into their own repositories.

## Work To Do

- Add an `action.yml` definition for the public action interface.
- Decide whether v1 should be:
  - one action with `mode: start | track | finalize`
  - or separate actions for start, track, and finalize
- Define stable inputs for:
  - `mode`
  - `job-id`
  - `step-name`
  - `stats-dir`
  - `metrics`
  - `manifest-path`
  - inline config if supported
- Define outputs such as:
  - resolved stats directory
  - generated report path
  - artifact-ready path
- Decide versioning and release tag format for `v1`.

## Definition Of Done

- A valid GitHub Action definition exists.
- The public inputs and outputs are documented and stable.
- A consumer workflow can reference the action using `uses:`.

## Completed Work

- Added [action.yml](</abs/path/C:/Users/Karthiek%20Duggirala/Documents/sca/ci-stats-watcher-final/action.yml>) as the public GitHub Action definition.
- Chose the v1 interface shape as one action with:
  - `mode: start | track | finalize`
- Added [action/dispatch.sh](</abs/path/C:/Users/Karthiek%20Duggirala/Documents/sca/ci-stats-watcher-final/action/dispatch.sh>) to:
  - validate the public mode input
  - validate required `track` inputs
  - resolve default outputs such as stats directory, report path, and artifact path
- Added [ACTION_INTERFACE.md](</abs/path/C:/Users/Karthiek%20Duggirala/Documents/sca/ci-stats-watcher-final/ACTION_INTERFACE.md>) to document:
  - intended `uses:` syntax
  - public inputs
  - public outputs
  - recommended v1 tag format

## Notes

- This task creates the public GitHub Action contract.
- Full runtime behavior for `start`, `track`, and `finalize` is still handled by Tasks 03, 04, and 05.
