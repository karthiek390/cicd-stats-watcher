# Release Validation

This file defines the repeatable validation path for `karthiek390/cicd-stats-watcher@v1`.

## Goal

Before publishing or moving the floating `v1` tag, we want a small but real validation path that checks:

- action metadata integrity
- bundled runtime file presence
- `mode: start`
- `mode: track`
- `mode: finalize`
- success-path artifacts
- failure-safe tracked-step behavior
- default-input behavior

## Primary Validation Workflow

Use:

- `.github/workflows/action-validation.yml`

That workflow validates:

1. Action metadata and required bundled runtime files.
2. A successful `start -> track -> finalize` path.
3. Per-step metric selection behavior.
4. A failing tracked step that still allows finalize/report generation.
5. Default-input behavior when optional inputs are omitted.

## What To Check Before Tagging `v1`

1. The `Action Validation` workflow passes on the candidate commit.
2. The success-path artifact contains:
   - `meta.json`
   - `report.html`
   - `step-summaries.json`
   - `watcher-runtime-state.json`
3. The failure-path artifact still contains:
   - `report.html`
   - failed tracked-step summary with the expected exit code
4. The default-input job proves the action still works without custom `stats-dir` or `manifest-path`.

## Manual Spot Checks

Recommended manual checks after the automated workflow passes:

1. Open the uploaded success artifact and confirm `report.html` renders useful content.
2. Inspect `step-summaries.json` and confirm `metrics_enabled` matches the chosen `metrics` input.
3. Inspect the failure artifact and confirm the failed step is recorded as `status: failed`.

## Current Limits Of Validation

- These checks run in GitHub Actions on Linux.
- They do not validate Windows self-hosted runner support.
- They do not validate non-GitHub CI platforms.
- They do not yet validate a polished live-hosting path.
