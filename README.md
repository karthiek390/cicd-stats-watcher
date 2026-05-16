# CICD Stats Watcher

GitHub Actions-first stats watcher for self-hosted runners.

The public release direction is a self-contained action:

- `uses: karthiek390/cicd-stats-watcher@v1`

The goal is to let teams track runner storage, Docker usage, CPU, memory, and inode behavior around important named workflow steps without copying a `tools/` folder into every repo.

## What This Project Contains

- a GitHub Action interface with:
  - `mode: start`
  - `mode: track`
  - `mode: finalize`
- watcher runtime scripts for collecting filesystem, Docker, and host stats
- report generation for a downloadable CICD stats artifact
- declarative GitHub Actions step-tracking support based on workflow inventory plus manifest

## Main Files

- [action.yml](</ci-stats-watcher-final/action.yml>)
  - public GitHub Action entrypoint
- [ACTION_INTERFACE.md](</ci-stats-watcher-final/ACTION_INTERFACE.md>)
  - current `uses:` interface and examples
- `action/`
  - mode implementations for start, track, and finalize
- `tools/ci-watcher/`
  - bundled runtime engine and GitHub Actions adapter files
- `reference/`
  - planning documents copied from the original Xenium work

## Current Public Shape

The public action path no longer assumes that the consumer repository vendors `tools/ci-watcher/`.

Instead:

- internal scripts are resolved relative to `GITHUB_ACTION_PATH`
- `stats-dir` is configurable
- manifest lookup defaults to the bundled action copy
- runtime state and stage files are internally resolved under `/tmp/ci-stats-watcher/`

## Minimal Usage

```yaml
- name: Start watcher
  uses: karthiek390/cicd-stats-watcher@v1
  with:
    mode: start

- name: Track build step
  uses: karthiek390/cicd-stats-watcher@v1
  with:
    mode: track
    job-id: build
    step-name: Build and push API image
    metrics: storage,docker
    command: |
      docker build --no-cache -t my-image .

- name: Finalize watcher
  if: always()
  uses: karthiek390/cicd-stats-watcher@v1
  with:
    mode: finalize
```

## Full Example

```yaml
name: CI

on:
  pull_request:
  push:
    branches: [main]

jobs:
  build:
    runs-on: self-hosted
    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Start watcher
        uses: karthiek390/cicd-stats-watcher@v1
        with:
          mode: start

      - name: Track Docker build
        uses: karthiek390/cicd-stats-watcher@v1
        with:
          mode: track
          job-id: build
          step-name: Build container image
          metrics: storage,docker,cpu,memory
          command: |
            docker build --no-cache -t my-app:test .

      - name: Track test run
        uses: karthiek390/cicd-stats-watcher@v1
        with:
          mode: track
          job-id: build
          step-name: Run unit tests
          metrics: storage,cpu,memory
          command: |
            pytest -q

      - name: Finalize watcher
        if: always()
        id: finalize-watcher
        uses: karthiek390/cicd-stats-watcher@v1
        with:
          mode: finalize

      - name: Upload stats artifact
        if: always() && steps.finalize-watcher.outputs.generated-report == 'true'
        uses: actions/upload-artifact@v4
        with:
          name: cicd-stats
          path: ${{ steps.finalize-watcher.outputs.artifact-path }}
```

## Per-Step Metric Examples

Use `metrics` to keep collection focused on the signals you care about.

- Docker-heavy build step:
  - `metrics: storage,docker,cpu,memory`
- Test step with no Docker interest:
  - `metrics: storage,cpu,memory`
- Filesystem and inode pressure check:
  - `metrics: storage,inode`
- Light storage-only tracking:
  - `metrics: storage`

## Runner Requirements

The current action is designed for self-hosted Linux GitHub Actions runners with:

- `bash`
- `python3`
- `docker`
- standard Unix tools like `df`, `awk`, `grep`, `sed`, `wc`, `find`

## What v1 Supports

- GitHub Actions only
- self-hosted Linux runners
- named step tracking
- one action with:
  - `mode: start`
  - `mode: track`
  - `mode: finalize`
- per-step metric selection with:
  - `storage`
  - `docker`
  - `cpu`
  - `memory`
  - `inode`
- downloadable artifact/report generation

## Deferred For Later

- tracking individual lines or sub-step markers inside a single shell block
- non-GitHub CI systems such as GitLab CI or Jenkins
- richer live-view packaging and hosting workflows
- a more polished release and validation pipeline

## Important Note

The public release path is the uses-based action interface in this repo.
The reference folder remains planning and history material and is not required for day-to-day action adoption.