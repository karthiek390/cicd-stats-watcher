# Task 07 - Remove Repo-Local Path Assumptions

task_completed: true

## Goal

Remove the assumption that the watcher implementation lives in the user's checked-out repository under `tools/ci-watcher/`.

## Why This Is Needed

A published action should carry its own implementation. Users should not need to know internal file locations or vendor your scripts into their repo.

## Work To Do

- Replace hardcoded references to `${{ github.workspace }}/tools/ci-watcher/...` in the public execution path.
- Make internal script lookup relative to the action bundle itself.
- Audit remaining assumptions around:
  - `/opt/sca/ci-stats`
  - `/tmp/ci-stage-*`
  - `/tmp/ci-stats-dir-*`
  - GitHub workspace-relative helper paths
- Convert repo-specific defaults into configurable inputs where appropriate.
- Keep Linux self-hosted runner requirements explicit and documented.

## Definition Of Done

- Public action behavior no longer depends on a vendored `tools/ci-watcher/` folder in the target repo.
- Required paths are configurable or internally resolved.

## Completed Work

- Confirmed that the public action runtime resolves bundled scripts relative to `GITHUB_ACTION_PATH` instead of `${{ github.workspace }}`.
- Confirmed that public runtime defaults are internally resolved for:
  - stats directory
  - manifest path
  - stage/state files
- Updated [README.md](</abs/path/C:/Users/Karthiek%20Duggirala/Documents/sca/ci-stats-watcher-final/README.md>) to describe the `uses:` adoption model instead of the old vendored `tools/` model.
- Updated [ADOPTION_CONTRACT.md](</abs/path/C:/Users/Karthiek%20Duggirala/Documents/sca/ci-stats-watcher-final/ADOPTION_CONTRACT.md>) to document the public action lifecycle:
  - `mode: start`
  - `mode: track`
  - `mode: finalize`
- Updated [ACTION_INTERFACE.md](</abs/path/C:/Users/Karthiek%20Duggirala/Documents/sca/ci-stats-watcher-final/ACTION_INTERFACE.md>) to document current path behavior and override points.

## Notes

- The old `.github/workflows/CI.yml` still contains many repo-local path assumptions, but it is now clearly treated as reference-only material rather than the public adoption path.
- Internal runtime files still physically live inside this repository under `tools/ci-watcher/`, but the consumer action path no longer depends on those files being copied into the target repository.
