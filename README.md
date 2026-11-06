# ci-agent-janitor

![ci](https://github.com/yashaswinin61-sketch/ci-agent-janitor/actions/workflows/ci.yml/badge.svg)

Keeps CI build agents (Jenkins, GitLab runners, Buildkite, anything with a workspace directory)
from running out of disk, and makes every cleanup **observable** in Prometheus and Grafana.

Agents that fill their disk fail builds in confusing ways ("No space left on device" halfway
through a compile, a corrupt git checkout, docker refusing to start). Cron jobs running `rm -rf`
work, but nobody can see what they deleted, how much space came back, or whether they are even
still running. This tool fixes that.

## How it works

```
                   ┌────────────── every hour (systemd timer / k8s CronJob) ──────────────┐
                   ▼                                                                       │
  /srv/ci/workspace/*  ──►  1. age pass:   delete workspaces idle > max_age_days           │
                            2. space pass: still < min_free_percent? delete LRU first      │
                            (skips dirs with a .janitor-keep lock file = running builds)   │
                                     │                                                     │
                 ┌───────────────────┴───────────────────┐                                 │
                 ▼                                       ▼                                 │
     textfile collector (.prom)                JSON summary on stdout                     │
                 │                                       │                                 │
         node_exporter → Prometheus              journald → Splunk / Loki / ELK            │
                 │                                                                         │
       Grafana dashboard + alerts ─────────────────────────────────────────────────────────┘
```

- **Safe by default.** Running builds drop a `.janitor-keep` file in their workspace, and the
  janitor never touches it. Keep patterns (`*@tmp`, `*@libs`) protect shared caches. `--dry-run`
  reports what it *would* delete, including an estimate for the space pass.
- **Two-pass policy.** Age-based cleanup handles normal churn. The free-space pass only kicks in
  under disk pressure and removes the least-recently-used workspaces first, so hot workspaces
  (and their incremental build caches) survive.
- **Observable.** Each run writes Prometheus metrics atomically (temp file + rename, so
  node_exporter never scrapes half a file) and a one-line JSON event for log pipelines.
- **No dependencies.** Pure standard library, Python 3.11+. Ships as a wheel or a non-root container.

## Quick start

```bash
pip install .
agent-janitor /srv/ci/workspace --max-age-days 3 --min-free-percent 20 --dry-run --json
```

```json
{"event": "agent_janitor_run", "agent": "build-07", "dry_run": true, "removed": 14,
 "protected": 2, "errors": 0, "bytes_reclaimed": 48318382080,
 "free_percent_before": 8.4, "free_percent_after": 8.4, "duration_seconds": 3.212}
```

### Run it on every agent

```bash
install -m 0644 deploy/agent-janitor.example.toml /etc/agent-janitor.toml
install -m 0644 deploy/systemd/agent-janitor.{service,timer} /etc/systemd/system/
systemctl enable --now agent-janitor.timer
```

The unit is sandboxed (`ProtectSystem=strict`, write access only to the workspace root and the
textfile directory) and runs at idle I/O priority so it doesn't slow down builds that are running.

### Mark a workspace as in use (Jenkins example)

```groovy
sh 'touch .janitor-keep'
try { /* build */ } finally { sh 'rm -f .janitor-keep' }
```

## Metrics

| metric | meaning |
|---|---|
| `agent_janitor_last_run_timestamp_seconds` | liveness: alert if the janitor stops running |
| `agent_janitor_free_percent_before` / `_after` | did the cleanup actually help? |
| `agent_janitor_bytes_reclaimed` | capacity trend per agent / pool |
| `agent_janitor_workspaces_removed` / `_protected` | how much churn there is |
| `agent_janitor_errors` | permission problems, files held open, etc. |

`deploy/prometheus/alerts.yml` ships three alerts: disk still low after cleanup (the janitor
can't fix it, so a human needs to look), janitor not running, and repeated deletion errors.
Recording rules aggregate by a `pool` label that you attach in your scrape config, so you can
compare agent pools.

`deploy/grafana/agent-janitor-dashboard.json` gives you a fleet overview (agents reporting, space
reclaimed, agents still low on disk) plus per-agent time series.

## Development

```bash
pip install -e '.[dev]'
pytest -v          # disk usage is injected, so tests never depend on the real disk
ruff check . && ruff format --check .
```

CI runs on Python 3.11 to 3.13, validates the alert rules with `promtool`, and builds the container image.

## License

MIT
