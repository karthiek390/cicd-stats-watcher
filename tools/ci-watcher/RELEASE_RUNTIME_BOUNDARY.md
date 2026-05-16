# Release Runtime Boundary

This document defines how the current `tools/ci-watcher/` contents should be treated for the GitHub Actions-first release path.

It does not yet publish a GitHub Action by itself. Instead, it separates the current files into three groups so later tasks can package only the right pieces behind a `uses:` interface.

## 1. Core Runtime

These files are the reusable watcher engine. They should form the base runtime that a future GitHub Action bundle invokes internally.

- `capture_system_snapshot.sh`
- `generate_report.py`
- `mark_step.sh`
- `run_step.sh`
- `run_tracked_step.sh`
- `serve.py`
- `watcher.sh`
- `write_build_summary.sh`
- `write_git_context.sh`
- `write_summary.sh`

Why these are core:

- they collect filesystem, Docker, and host metrics
- they record tracked step boundaries
- they generate the final artifact and report
- they are useful beyond the current copied sample workflow

## 2. GitHub Actions Adapter Layer

These files are GitHub Actions-specific configuration and validation helpers.

- `extract_ci_inventory.py`
- `generated-ci-inventory.yaml`
- `validate_watcher_manifest.py`
- `watcher-manifest.yaml`

Why these are adapter files:

- they depend on GitHub Actions workflow structure
- they model jobs and named workflow steps
- they are useful for GitHub Actions v1, but they are not the watcher engine itself

For the future `uses:` release model, these files should be treated as the GitHub Actions adapter rather than the universal core runtime.

## 3. Project-Specific Helpers

These files should not be part of the public v1 action behavior.

- `cleanup_preview_slot.sh`
- `export_preview_fixture_bundle.sh`
- `preview_slots.py`
- `restore_preview_fixture_bundle.sh`
- `setup.sh`

Why these are excluded from the public release path:

- they are tied to the copied Xenium preview and setup flow
- they are not required for generic named-step tracking
- they would add confusion to a GitHub Actions-first watcher release

## 4. Intended Future Action Bundle Layout

Later tasks should package the watcher into a self-contained GitHub Action bundle with an internal layout similar to:

```text
action bundle
  action.yml
  runtime/
    capture_system_snapshot.sh
    generate_report.py
    mark_step.sh
    run_step.sh
    run_tracked_step.sh
    serve.py
    watcher.sh
    write_build_summary.sh
    write_git_context.sh
    write_summary.sh
  adapters/
    github-actions/
      extract_ci_inventory.py
      validate_watcher_manifest.py
      watcher-manifest.yaml
      generated-ci-inventory.yaml
```

Important rule:

- public action entrypoints should resolve internal files relative to the action bundle itself
- they should not require the consumer repository to vendor `tools/ci-watcher/`

## 5. What This Task Changes In Practice

After this task:

- the runtime boundary is defined clearly
- the GitHub Actions adapter files are identified explicitly
- project-specific helper files are excluded from the v1 public release path

What is still not done yet:

- there is no `action.yml` yet
- users still do not have a published `uses:` workflow interface
- repo-local path assumptions are still present in the current sample integration and will be addressed in later tasks
