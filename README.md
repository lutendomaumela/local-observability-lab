# Local Observability Lab

A learning lab that models a small production service using Docker Compose. The
stack is local-only; published web ports bind to `127.0.0.1`.

## Current stack: Phases 1–7

The lab runs Prometheus, Grafana, Alertmanager, a local webhook receiver,
Blackbox Exporter, Tempo, Node Exporter, cAdvisor, nginx, a Flask application,
PostgreSQL, their metrics exporters, Loki, and Grafana Alloy. Prometheus
scrapes the metrics targets every 15 seconds. Alloy collects Docker logs into
Loki, and Grafana's datasources and dashboards are provisioned from files. A
profile-only k6 runner adds bounded traffic scenarios; it is not started with
the normal stack. Prometheus evaluates alert rules, Alertmanager routes
notifications only to the local webhook receiver, Blackbox Exporter probes the
service health endpoint, and the app exports traces to Tempo.

On Windows with Docker Desktop, Node Exporter observes the Linux VM used by
Docker Desktop, not Windows host counters. cAdvisor also uses elevated access to
read container and host runtime metrics. Docker Desktop may expose aggregate
cgroups instead of individual named containers in cAdvisor. Keep this local
lab bound to loopback.

### Start

1. Copy `.env.example` to `.env` and adjust the local Grafana sign-in or ports
   if needed. `.env` is git-ignored.
2. From this folder, run:

   ```sh
   docker compose config
   docker compose up -d
   docker compose ps
   ```

3. Open the endpoints below. Grafana's initial username/password are the values
   in `.env` (the example defaults are only for this local lab).

| Service | URL | Purpose |
|---|---|---|
| Grafana | http://127.0.0.1:3000 | Dashboards and visual exploration |
| Prometheus | http://127.0.0.1:9090 | Metrics, targets, and PromQL |
| Alertmanager | http://127.0.0.1:9093 | Alert groups, silences, and delivery status |
| Local alert receiver | http://127.0.0.1:8090/alerts | Latest received webhook payload |
| Blackbox Exporter | http://127.0.0.1:9115 | HTTP probe metrics |
| Tempo | http://127.0.0.1:3200/ready | Trace storage readiness |
| Node Exporter | http://127.0.0.1:9100/metrics | Host VM metrics endpoint |
| cAdvisor | http://127.0.0.1:8085 | Container metrics and UI |
| Simulated service | http://127.0.0.1:8080 | nginx → Flask → PostgreSQL |
| PostgreSQL | `127.0.0.1:5432` | Optional local database access |
| nginx exporter | http://127.0.0.1:9113/metrics | nginx connection metrics |
| PostgreSQL exporter | http://127.0.0.1:9187/metrics | Database metrics |
| Loki | http://127.0.0.1:3100/ready | Log store readiness |
| Alloy | http://127.0.0.1:12345 | Collector component health |

If you changed ports in `.env`, use those values instead.

### Generate traffic

The k6 image is downloaded on first use; no host-side k6 installation is
needed. In Git Bash, choose one scenario per run:

```sh
docker compose --profile traffic run --rm -e SCENARIO=steady k6
docker compose --profile traffic run --rm -e SCENARIO=daily-wave k6
docker compose --profile traffic run --rm -e SCENARIO=spike k6
docker compose --profile traffic run --rm -e SCENARIO=error-burst k6
```

`steady` lasts 45 seconds by default; `daily-wave`, `spike`, and `error-burst`
are short, bounded learning runs. Use
`docker compose --profile traffic run --rm -e SCENARIO=steady -e STEADY_DURATION=5s k6`
for a quick smoke run. The error-burst scenario enables the app's authenticated
chaos endpoint and clears it during teardown. If the run is interrupted, clear
all app chaos settings manually using the `/chaos` instructions below.

### Fault experiments

These Git Bash scripts have explicit resource/time caps. Run one experiment at a
time and watch Grafana's Phase 2 host/container and Phase 3 application RED
dashboards. For example:

```sh
bash scripts/cpu-burn.sh 20
bash scripts/memory-pressure.sh 64 15
bash scripts/disk-fill.sh 16 5
bash scripts/slow-database.sh
bash scripts/stop-exporter.sh node-exporter 20
bash scripts/kill-app.sh 15
```

The disk, app-stop, and exporter-stop scripts clean up or restart their target
when they exit; do not close Docker Desktop while an experiment is running.
Memory pressure is capped at 256 MiB; CPU, app interruption, and exporter
interruption are capped at 60 seconds. Disk fill is capped at 64 MiB and
temporary to the app container's writable layer. These experiments are for this
local lab only; do not point the scripts or traffic runner at external systems.

### Alerts and webhook delivery

Prometheus evaluates eight rules for target availability, host VM CPU/disk/
memory, application error rate and p95 latency, missing PostgreSQL exporter
health samples, and HTTP probe failure. Alert labels and response guidance are
in the rules and [docs/RUNBOOK.md](docs/RUNBOOK.md). Alertmanager has one
receiver: the local webhook container; no email, Teams, or external service is
configured.

Open **Dashboards → Lab → Phase 6 - Alerts and probes**, Prometheus
**Alerts**, and Alertmanager to inspect rule state and notification groups.
The receiver's `/alerts` endpoint shows the latest delivered notification
payload in memory; its history resets if the container restarts. The
`DatabaseMetricsNoData` rule is a teaching analogue for a missing backup
freshness signal, using the PostgreSQL exporter `pg_up` series; it does not
claim that a backup system is installed.

### Traces

The Flask app and its PostgreSQL client emit OpenTelemetry spans to Tempo. Open
Grafana **Explore**, choose **Tempo**, and search for service `app`; open a
trace and use its trace-to-logs link to find app JSON logs carrying the same
trace ID. Tempo retains local traces for 48 hours. Its OTLP receiver ports
4317/4318 are internal to the Compose network; only the Tempo query UI/API on
3200 is published to localhost.

The Flask app exposes `/health`, `/metrics`, and `/chaos` internally. Use
`/chaos` through the service URL with the `X-Admin-Token` header; the example
token is local-only and is read from `.env`.

Alloy reads Docker container logs through the Docker socket. Socket access can
grant broad control of the local Docker engine even when mounted read-only.
This lab filters to the configured Compose project and publishes its UI only on
loopback; do not expose Alloy, Loki, or the Docker socket to untrusted networks.

### Stop and reset

Stop the containers but keep their stored data:

```sh
docker compose down
```

To reset the lab's stored Grafana, Prometheus, PostgreSQL, Loki, and Alloy data,
remove the named volumes as well:

```sh
docker compose down --volumes
```

This deletes the lab's local time-series, Grafana state, database contents, and
stored logs and traces. Do not use the volume-removal option if you want to
keep them. It does not remove source configuration files.

See [docs/LEARNING-GUIDE.md](docs/LEARNING-GUIDE.md) for lessons, queries, and
investigation exercises for each completed phase.
