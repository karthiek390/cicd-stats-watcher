# Task 09 - Add Validation And Release Checks

task_completed: true

## Goal

Add verification so the action can be released confidently for GitHub Actions users.

## Why This Is Needed

Moving from a reference repo to a reusable action needs stronger validation around packaging, action behavior, and upgrade safety.

## Work To Do

- Add test workflows or fixture workflows that exercise:
  - `mode: start`
  - `mode: track`
  - `mode: finalize`
- Validate that tracked named steps produce expected artifacts.
- Validate that per-step metric selection works.
- Validate failure-safe behavior when tracked commands fail.
- Validate behavior when optional inputs are omitted.
- Add release checks for action metadata and bundled runtime files.

## Definition Of Done

- There is a repeatable validation path for the public action interface.
- A release candidate can be tested end to end before publishing `v1`.

## Completed Work

- Added [`.github/workflows/action-validation.yml`](</abs/path/C:/Users/Karthiek%20Duggirala/Documents/sca/ci-stats-watcher-final/.github/workflows/action-validation.yml>) to validate:
  - action metadata and bundled runtime files
  - successful `start -> track -> finalize`
  - per-step metric selection
  - failure-safe tracked-step behavior
  - default-input behavior
- Added [RELEASE_VALIDATION.md](</abs/path/C:/Users/Karthiek%20Duggirala/Documents/sca/ci-stats-watcher-final/RELEASE_VALIDATION.md>) to document the release-validation path and pre-tag checklist.

## Notes

- This creates the first repeatable release gate for the public action interface.
- The validation workflow is designed to exercise the action against itself with `uses: ./`.
