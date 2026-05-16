# CICD Stats Watcher

Lightweight per-pipeline disk and Docker stats monitor for the `builddev1` CI runner.

## What it does

- **During each CI run**: collects disk space, Docker usage, and container CPU/memory stats every 10 seconds
- **Live view**: serves a plain HTML report on `https://builddev1.sca.iu.edu:5999` (auto-refreshes every 10s)
- **History**: stores a static `report.html` per run at `/home/scadev/ci-stats/pr-<N>/run-<SHA>-<date>/`
- **PR comment**: posts the live URL to the PR at the start of every pipeline run
- **Auto-cleanup**: runs older than 30 days are automatically deleted

## Files

| File | Purpose |
|---|---|
| `watcher.sh` | Background bash loop — polls disk + Docker every 10s |
| `serve.py` | Single-threaded Python stdlib HTTP server on port 5999 |
| `generate_report.py` | One-shot final report generator (called at teardown) |
| `setup.sh` | One-time deploy script — copies scripts to `builddev1` |

## One-time Setup (run once by a team admin)

```bash
# From repo root, on your local machine:
bash tools/ci-watcher/setup.sh scadev@builddev1
```

This will:
1. Copy the three runtime scripts to `~/ci-watcher/` on `builddev1`
2. Create `~/ci-stats/` for data storage
3. Verify Python 3 is available

**Port 5999** must be open in the firewall (same VPN zone as the preview ports 5000–6000).

## Live Dashboard (during a pipeline run)

Navigate to `https://builddev1.sca.iu.edu:5999` (VPN required).

The page shows plain structured text:
- **Filesystem**: `/`, `/var`, `/opt/sca` — size, used, available, use%
- **Docker disk usage**: images, containers, volumes, build cache (with reclaimable)
- **Xenium images**: `xenium/ui`, `xenium/api`, `xenium/workers` — tag + size
- **Container stats**: CPU%, memory used/limit/% per running container
- **Current pipeline stage**: disk-check → building API/UI/Workers → E2E tests → complete

Navigate to `/history` to see all past runs for this PR, with links to their static reports.

## Stored Reports

Each run stores:

```
~/ci-stats/
  pr-70/
    run-abc1234-2026-03-08/
      meta.json          ← identity (PR, SHA, run_id, start/end times)
      timeline.ndjson    ← one JSON line per 10s tick (raw data)
      watcher.log        ← watcher stderr log
      serve.log          ← HTTP server stderr log
      report.html        ← self-contained plain HTML report (viewable forever)
```

The `report.html` includes:
- Identity block (PR, SHA, Actions run URL, start/end time, duration)
- Disk snapshot: start vs end
- Delta summary (what changed)
- Docker totals: start vs end
- Per-image sizes: start vs end
- **Peak memory per container** across all ticks (useful for memory leak detection)
- Full timeline log: one line per tick

## Data collected per tick

| Source | Command | Data |
|---|---|---|
| Filesystem | `df -P / /var /opt/sca` | size_kb, used_kb, avail_kb, pct per mount |
| Docker totals | `docker system df` | images, containers, volumes, build cache total + reclaimable |
| Xenium images | `docker images` filtered to `xenium/*` | repo, tag, size |
| Container stats | `docker stats --no-stream` | CPU%, mem used, mem limit, mem% |

> **Note:** `docker stats --no-stream` reads cgroup metrics once and exits (~1s per call). It does **not** stream or stay attached to containers.

## CI.yml Integration

Three points of integration:

1. **`disk-check` job** — starts watcher + server, posts PR comment with live URL
2. **`build` job** — writes current stage (building API/UI/Workers) to `/tmp/ci-stage-<PR>` for the live dashboard
3. **`cleanup` job** — generates final report, stops watcher + server, prunes old runs
