# GitHub Action Interface

This file defines the public GitHub Actions interface for the future `uses:` release model.

Current intended usage:

```yaml
- name: Start CI stats watcher
  uses: karthiek390/cicd-stats-watcher@v1
  with:
    mode: start

- name: Track build step
  uses: karthiek390/cicd-stats-watcher@v1
  with:
    mode: track
    job-id: build
    step-name: Build and push API image
    metrics: storage,docker,cpu,memory
    command: |
      docker build --no-cache -t my-image .

- name: Finalize CI stats watcher
  if: always()
  uses: karthiek390/cicd-stats-watcher@v1
  with:
    mode: finalize
```

## v1 Interface Decision

v1 will use one action with:

- `mode: start | track | finalize`

This keeps adoption simple and avoids making users learn multiple action names for the basic workflow lifecycle.

## Public Inputs

- `mode`
  - required
  - valid values: `start`, `track`, `finalize`
- `job-id`
  - required for `track`
- `step-name`
  - required for `track`
- `stats-dir`
  - optional explicit stats directory
- `metrics`
  - optional comma-separated metrics list
  - current interface default: `storage,docker`
  - supported values: `storage`, `docker`, `cpu`, `memory`, `inode`
- `command`
  - required for `track`
  - the action runs this command itself for tracked execution
- `working-directory`
  - optional working directory for `track`
- `manifest-path`
  - optional path to the GitHub Actions manifest
- `inline-config`
  - reserved for future support
- `run-server`
  - reserved for future live-server control

## Example Workflow

```yaml
jobs:
  build:
    runs-on: self-hosted
    steps:
      - uses: actions/checkout@v4

      - name: Start watcher
        uses: karthiek390/cicd-stats-watcher@v1
        with:
          mode: start

      - name: Track build
        uses: karthiek390/cicd-stats-watcher@v1
        with:
          mode: track
          job-id: build
          step-name: Build image
          metrics: storage,docker,cpu,memory
          command: |
            docker build --no-cache -t my-image .

      - name: Finalize watcher
        if: always()
        id: finalize-watcher
        uses: karthiek390/cicd-stats-watcher@v1
        with:
          mode: finalize

      - name: Upload artifact
        if: always() && steps.finalize-watcher.outputs.generated-report == 'true'
        uses: actions/upload-artifact@v4
        with:
          name: cicd-stats
          path: ${{ steps.finalize-watcher.outputs.artifact-path }}
```

## Public Outputs

- `mode`
- `resolved-stats-dir`
- `report-path`
- `artifact-path`
- `metrics`
- `manifest-path`
- `meta-path`
- `state-path`
- `stage-file`
- `watcher-pid`
- `server-pid`
- `exit-code`
- `finalized`
- `generated-report`

## Path Behavior

The public action path no longer requires the consumer repository to contain `tools/ci-watcher/`.

Current behavior:

- bundled runtime files are resolved relative to `GITHUB_ACTION_PATH`
- the default manifest path points to the bundled action copy
- the default stats directory is resolved under `/tmp/ci-stats-watcher/`
- internal stage/state files are also resolved under `/tmp/ci-stats-watcher/`

Override points:

- `stats-dir`
- `manifest-path`

## Notes For Current State

- `action.yml` now exists and defines the public contract.
- `mode: start` now creates the stats directory, writes `meta.json`, starts the watcher, and records runtime state.
- `mode: track` now runs the target command itself and records before/after step data.
- `mode: track` now honors per-step metric selection through the `metrics` input.
- `mode: finalize` now generates the final report and stops background processes.
- the public action no longer depends on a vendored `tools/ci-watcher/` folder in the consumer repo

## Deferred For Later

- line-level markers inside a single `run:` block
- non-GitHub CI platforms
- deeper packaging around live serving

## Planned Release Tag Format

Recommended public tag format:

- `v1`
- `v1.0.0`
- later patch/minor tags such as `v1.0.1`, `v1.1.0`

Recommended release practice:

- move the floating `v1` tag to the latest stable v1 release
- keep immutable semver tags for exact pinning
