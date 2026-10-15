# Learning guide

## Phase 1: Metrics, scraping, and dashboards

### The concept

Prometheus is a time-series database and monitoring system. It usually **pulls**
metrics: on a schedule, it requests a metrics endpoint from each target and
stores the samples with a timestamp and labels. In this phase, Prometheus is
both the monitoring server and its first target. Its `up` metric reports whether
the latest scrape succeeded (`1`) or failed (`0`).

Grafana does not store these metrics. It queries Prometheus through a datasource
and turns query results into panels. The datasource and dashboard provider are
provisioned from files, so a new lab instance starts with the same setup.

The recording rule in `prometheus/rules/recording.yml` periodically evaluates
`sum(up)` and stores the result under the shorter name
`lab:targets_up:count`. Recording rules are useful when a commonly used
calculation is expensive or needs a consistent reusable name.

### Look at the running system

1. Open Prometheus at http://127.0.0.1:9090 and visit **Status → Targets**.
   The `prometheus` target should be `UP`.
2. Open Grafana at http://127.0.0.1:3000 and sign in with the values in `.env`.
3. Open **Dashboards → Lab → Phase 1 - Metrics foundation**. The panels show
   target status, ingested samples, and scrape duration.
4. In Prometheus, open **Graph** and run the queries below. Use the range view
   to see how successive samples form a time series.

### PromQL to try

1. `up` — one health value for each currently configured scrape target.
2. `scrape_duration_seconds{job="prometheus"}` — how long Prometheus's scrape
   of itself took.
3. `rate(prometheus_tsdb_head_samples_appended_total[5m])` — approximate sample
   ingestion rate over five minutes.
4. `lab:targets_up:count` — the recording rule's precomputed count of healthy
   targets.

### Break it, then investigate

With this phase's single target, stop the lab's Prometheus service:

```sh
docker compose stop prometheus
```

The Prometheus UI will also become unavailable because it is the component you
stopped. In Grafana, observe that queries stop returning fresh samples; this
demonstrates an important monitoring limitation: a monitoring server cannot
report its own outage while it is down. Restore it with
`docker compose start prometheus`, then check **Status → Targets** and confirm
the target becomes `UP` again. Later phases add independent probes and alerts to
make failures more visible.

### Investigation checklist

| Symptom | Dashboard or view | Query / check | Possible cause |
|---|---|---|---|
| Target is missing or down | Prometheus **Status → Targets**; Grafana Phase 1 dashboard | `up` | Prometheus cannot reach the target, or its scrape configuration is wrong |
| No recent graph data | Grafana Phase 1 dashboard; Prometheus **Graph** | `up{job="prometheus"}` | Prometheus stopped, scrape failed, or the selected time range is wrong |
| Sample-ingestion panel is empty | Grafana Phase 1 dashboard | `prometheus_tsdb_head_samples_appended_total` | Prometheus has not ingested samples yet, or the metric name changed |
| Scrapes take longer than expected | Grafana Phase 1 dashboard | `scrape_duration_seconds` | A slow or overloaded target; in this phase, investigate the Prometheus container |

## Phase 2: Host and container metrics

### The concept

An exporter translates system measurements into Prometheus metrics. Node
Exporter exposes operating-system counters such as CPU time, memory, filesystems,
and network traffic. cAdvisor gathers per-container usage such as CPU and
working-set memory. Prometheus scrapes both exporters; Grafana can then compare
host-wide pressure with the resource use of individual containers.

Metrics are counters or gauges. A counter only increases, so use `rate()` over a
time window to estimate its per-second change. A gauge, such as memory currently
in use, is read directly. Rates need enough samples, so allow at least a minute
after startup before interpreting short-window queries.

On Windows with Docker Desktop, Node Exporter reports the Linux VM that runs
Docker containers; it does not report Windows host CPU or memory. cAdvisor
requires elevated access to the Docker host's runtime and cgroups to observe
containers. Docker Desktop's cgroup layout may expose aggregate hierarchy IDs
such as `/docker` instead of individual named containers; the dashboard uses
the `id` label and shows the cgroups cAdvisor actually reports. On a Linux host,
you may see individual containers instead. This lab keeps its web interfaces on
loopback and is intended only for local learning.

### Look at the running system

1. In Prometheus, visit **Status → Targets**. `prometheus`, `node-exporter`,
   and `cadvisor` should all be `UP`.
2. Open Grafana's **Dashboards → Lab → Phase 2 - Host and containers**.
3. Open http://127.0.0.1:8085 to inspect cAdvisor's container view.
4. Visit http://127.0.0.1:9100/metrics to see Node Exporter's raw text format.
5. Compare host-wide metrics with the cAdvisor cgroup series. On this Docker
   Desktop setup, the cAdvisor API may show aggregate cgroups rather than named
   Compose containers.

### PromQL to try

1. `up{job=~"node-exporter|cadvisor"}` — whether each exporter scrape succeeds.
2. `100 * (1 - avg by (instance) (rate(node_cpu_seconds_total{mode="idle"}[5m])))`
   — approximate host-VM CPU utilization percentage.
3. `100 * (1 - node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes)`
   — approximate host-VM memory use percentage.
4. `sum by (id) (rate(container_cpu_usage_seconds_total{id!="/"}[5m]))`
   — CPU cores used by each non-root cgroup reported by cAdvisor.
5. `container_memory_working_set_bytes{id!="/"}`
   — working-set memory for each non-root cgroup. Check the `id` label to see
   whether this host reports named containers or only aggregate groups.

### Break it, then investigate

Stop just the cAdvisor exporter:

```sh
docker compose stop cadvisor
```

After a scrape interval, run `up{job="cadvisor"}` in Prometheus: the result
should be `0`, while the Node Exporter target remains `1`. In the Phase 2
dashboard, container panels should lose fresh data, but host metrics should
continue. Restore collection with `docker compose start cadvisor`, revisit
**Status → Targets**, and confirm the cAdvisor target returns to `UP`.

This distinguishes an exporter failure from a whole-host outage: one telemetry
path can fail while another remains healthy.

### Investigation checklist

| Symptom | Dashboard or view | Query / check | Possible cause |
|---|---|---|---|
| Host panels have no fresh data | Phase 2 dashboard; Prometheus **Status → Targets** | `up{job="node-exporter"}` | Node Exporter stopped, or its host mounts are unavailable |
| Container panels have no fresh data | Phase 2 dashboard; cAdvisor UI | `up{job="cadvisor"}` | cAdvisor stopped or could not access Docker runtime metrics |
| Host memory looks unlike Windows Task Manager | Phase 2 dashboard | `node_memory_MemTotal_bytes` | Expected on Docker Desktop: Node Exporter measures the Linux VM |
| Container CPU rises | Phase 2 dashboard | `sum by (id) (rate(container_cpu_usage_seconds_total{id!="/"}[5m]))` | The cgroup is consuming more CPU; inspect the corresponding workload. Docker Desktop may only expose an aggregate cgroup |

## Phase 3: A database-backed service and exporters

### The concept

The simulated request path is nginx → Flask → PostgreSQL. nginx accepts browser
traffic and reverse-proxies it to Flask; the app records each home-page visit in
PostgreSQL. This separates the public entry point, application logic, and
persistent storage into independently observable services.

The app publishes Prometheus counters and a request-duration histogram.
Counters answer "how many?" and become rates with `rate()`. A histogram records
observations in cumulative buckets; `histogram_quantile()` estimates latency
percentiles such as p95 and p99 from those buckets. These are the RED signals:
request **Rate**, **Errors**, and **Duration**. nginx and PostgreSQL exporters
translate their respective service statistics into Prometheus metrics too.

The `/health` route checks database connectivity, so a running Flask process
with a broken database is not reported as ready. The `/chaos` route is protected
by a local token and lets you inject request latency, PostgreSQL query delay, or
a controlled HTTP 500 rate. Chaos state is in memory and resets when the app
restarts.

### Look at the running system

1. Open http://127.0.0.1:8080 a few times. Each response includes the visit
   count stored in PostgreSQL.
2. Open **Dashboards → Lab → Phase 3 - Application RED** in Grafana.
3. Visit Prometheus **Status → Targets**. The `app`, `nginx-exporter`, and
   `postgres-exporter` jobs should be `UP`.
4. Inspect http://127.0.0.1:9113/metrics and
   http://127.0.0.1:9187/metrics for exporter output.
5. Read `app/app.py` and compare the metric labels with the labels shown by
   Prometheus. The route label uses Flask's route template rather than raw
   request paths, keeping metric cardinality bounded.

### PromQL to try

1. `sum(rate(http_requests_total{route="/"}[5m]))` — home-page requests per
   second.
2. `100 * sum(rate(http_requests_total{status=~"5.."}[5m])) / clamp_min(sum(rate(http_requests_total{route="/"}[5m])), 0.001)`
   — percentage of home-page requests ending in a server error.
3. `histogram_quantile(0.95, sum by (le) (rate(http_request_duration_seconds_bucket{route="/"}[5m])))`
   — estimated p95 home-page latency.
4. `nginx_connections_active` — currently active nginx connections.
5. `pg_up` — whether the PostgreSQL exporter can connect to the database.

### Break it, then investigate

In Git Bash, load the local-only settings and ask the app to add 800 ms to each
home-page request and return a 500 for every request:

```sh
. ./.env
curl -X POST http://127.0.0.1:8080/chaos \
  -H "Content-Type: application/json" \
  -H "X-Admin-Token: $CHAOS_ADMIN_TOKEN" \
  -d '{"latency_ms":800,"error_rate":1}'
```

Refresh the home page a few times. Observe the RED dashboard: request rate
continues, the error ratio rises, and p95/p99 latency increases. Use the queries
above to confirm each signal. Then clear chaos and verify recovery:

```sh
curl -X DELETE http://127.0.0.1:8080/chaos \
  -H "X-Admin-Token: $CHAOS_ADMIN_TOKEN"
```

Compare the Prometheus metrics with the Flask JSON request logs in
`docker compose logs app`. A metric tells you *how often* and *how long*;
the structured log identifies the request route, status, and duration. Logs and
metrics become easier to correlate in Phase 4.

### Investigation checklist

| Symptom | Dashboard or view | Query / check | Possible cause |
|---|---|---|---|
| Application target is down | Prometheus **Status → Targets** | `up{job="app"}` | Flask failed to start, or Prometheus cannot reach its metrics endpoint |
| Home page returns an error | Phase 3 RED dashboard; app logs | `rate(http_requests_total{route="/",status=~"5.."}[5m])` | PostgreSQL unavailable, application exception, or deliberate chaos injection |
| p95 latency rises | Phase 3 RED dashboard | `histogram_quantile(0.95, sum by (le) (rate(http_request_duration_seconds_bucket{route="/"}[5m])))` | Injected delay, slow database query, or overloaded app |
| Health check fails | Simulated service `/health`; app logs | `pg_up` and `up{job="postgres-exporter"}` | PostgreSQL is unavailable or the exporter cannot connect |

## Phase 4: Logs and metric-to-log correlation

### The concept

Prometheus stores numeric time series; Loki stores log lines with indexed
labels. Grafana Alloy discovers containers through the Docker Engine API and
ships their logs to Loki. The pipeline keeps the Compose service name as a
`service` label and the container name as `container`, making it possible to
filter by service without indexing every word in each log message.

The app's JSON log fields (`method`, `route`, `status`, and `duration_ms`) stay
inside the log line rather than becoming high-cardinality Loki labels. LogQL's
`| json` stage parses those fields while querying, so you can filter error
responses or inspect request duration without creating an index entry for every
URL or status combination.

The RED dashboard's app-metric panels link to the Log Explorer with the
dashboard time range and `service=app` carried across. This lets you move from
"latency or errors increased" to the corresponding request records for the same
time window.

Alloy requires access to `/var/run/docker.sock` to discover and read container
logs. A read-only mount does not make the Docker API itself read-only; treat
socket access as powerful local-machine access. The relabel rule limits log
collection to this Compose project, and the UI is bound to loopback.

### Look at the running system

1. Open **Dashboards → Lab → Phase 4 - Log explorer** and select `app`.
2. Generate a few requests at http://127.0.0.1:8080; app request logs should
   appear in the dashboard after a short collection delay.
3. Open **Dashboards → Lab → Phase 3 - Application RED**. Use **Open app logs**
   on a metric panel and confirm the log dashboard retains its time range.
4. In Grafana **Explore**, select the Loki datasource and try the LogQL queries
   below.
5. Inspect http://127.0.0.1:12345 to see Alloy's component graph and health.

### LogQL to try

1. `{service="app"}` — all collected application container logs.
2. `{service="app"} | json` — parse the structured request fields.
3. `{service="app"} | json | status >= 500` — show application error responses.
4. `{service="nginx"}` — inspect reverse-proxy access and error logs.
5. `sum(count_over_time({service="app"} | json | status >= 500 [5m]))`
   — count application error log lines over the last five minutes.

### Break it, then investigate

Reuse Phase 3's authenticated chaos endpoint to create server errors:

```sh
. ./.env
curl -X POST http://127.0.0.1:8080/chaos \
  -H "Content-Type: application/json" \
  -H "X-Admin-Token: $CHAOS_ADMIN_TOKEN" \
  -d '{"latency_ms":300,"error_rate":1}'
```

Make several requests, then compare the Phase 3 RED dashboard's error and
latency signals with the Phase 4 Log Explorer. Select `app` and run
`{service="app"} | json | status >= 500`; the log entries should show the
matching 500 statuses and durations. Clear the injected fault afterward:

```sh
curl -X DELETE http://127.0.0.1:8080/chaos \
  -H "X-Admin-Token: $CHAOS_ADMIN_TOKEN"
```

### Investigation checklist

| Symptom | Dashboard or view | Query / check | Possible cause |
|---|---|---|---|
| No app logs appear | Phase 4 Log Explorer; Alloy UI | `{service="app"}` | Alloy cannot reach Docker, project label filter is wrong, or Loki is unavailable |
| RED panel shows errors | Phase 3 RED dashboard, then its **Open app logs** link | `{service="app"} \| json \| status >= 500` | Chaos injection, database failure, or an application error |
| Logs do not match the metric time window | Open app logs from the RED panel | Check dashboard time range and Loki stream labels | Time range was not carried over or the service label does not match |
| Logs stop for every service | Alloy UI; Loki `/ready` endpoint | `{service=~".+"}` | Alloy stopped, Docker socket unavailable, or Loki is not ready |

## Phase 5: Traffic generation and fault injection

### The concept

k6 runs virtual users (VUs) that repeatedly make requests. The steady scenario
keeps a small, constant number of users; the daily-wave scenario ramps users up
and down; the spike scenario quickly increases concurrency; and error-burst
uses the app's protected chaos endpoint to produce predictable HTTP 500s.
These small traffic patterns make it possible to compare a normal baseline with
changes in request rate, errors, and latency without installing k6 on Windows.

The fault scripts add controlled pressure to one component at a time: CPU and
memory in the app container, temporary disk use in its writable layer,
PostgreSQL query delay, an app interruption, or a stopped metrics exporter.
Faults are deliberately bounded and most scripts restore their target
automatically. cAdvisor may show only aggregate cgroups on Docker Desktop, so
correlate resource experiments with application request metrics and logs too.

### Look at the running system

1. Open **Dashboards → Lab → Phase 3 - Application RED** and note its current
   request rate, error ratio, and p95/p99 latency.
2. Run the short steady scenario from Git Bash:

   ```sh
   docker compose --profile traffic run --rm -e SCENARIO=steady -e STEADY_DURATION=5s k6
   ```

3. For a longer experiment, run the `steady`, `daily-wave`, `spike`, or
   `error-burst` command from the README. The profile keeps k6 out of the
   everyday stack.
4. Run one bounded script under `scripts/`, then compare the RED dashboard,
   Phase 2 host/container dashboard, Prometheus targets, and Phase 4 logs.
5. Let each change appear in Prometheus for a few scrape intervals before
   drawing conclusions; rates and percentiles need a time window.

### PromQL to try

1. `sum(rate(http_requests_total{route="/"}[1m]))` — home-page request rate.
2. `sum(rate(http_requests_total{route="/",status=~"5.."}[1m]))` — rate of
   home-page server errors.
3. `histogram_quantile(0.95, sum by (le) (rate(http_request_duration_seconds_bucket{route="/"}[1m])))`
   — estimated p95 response duration.
4. `sum(rate(container_cpu_usage_seconds_total{id!="/"}[1m]))` — CPU cores
   used by non-root cgroups reported by cAdvisor.
5. `up{job=~"node-exporter|cadvisor|nginx-exporter|postgres-exporter"}` —
   verify whether each exporter is still being scraped.

### Break it, then investigate

Use the spike scenario for a bounded increase in concurrent traffic:

```sh
docker compose --profile traffic run --rm -e SCENARIO=spike k6
```

Follow the request-rate and p95 lines in the Phase 3 RED dashboard. If errors
also rise, open the Phase 4 log explorer from the RED panel and filter app logs
for status 500. Check Phase 2 for CPU or memory pressure, and check the
Prometheus targets page if exporter data disappears. Repeat with
`SCENARIO=error-burst` to compare load-driven behavior with deliberate errors.
The error-burst script resets chaos when k6 completes normally. If the run is
interrupted, clear it in Git Bash:

```sh
. ./.env
curl -X DELETE http://127.0.0.1:8080/chaos \
  -H "X-Admin-Token: $CHAOS_ADMIN_TOKEN"
```

Do not run multiple fault experiments concurrently. `disk-fill.sh`,
`kill-app.sh`, and `stop-exporter.sh` have cleanup/restart traps, but if a
terminal is forcibly closed, recover with `docker compose up -d app` or
`docker compose up -d <exporter>` as appropriate. `slow-database.sh` clears
chaos on normal exit; after an interrupted run, use the same authenticated
DELETE request above. Never run these scripts against systems outside this lab.

### Investigation checklist

| Symptom | Dashboard or view | Query / check | Possible cause |
|---|---|---|---|
| Request rate rises during a test | Phase 3 Application RED | `sum(rate(http_requests_total{route="/"}[1m]))` | More virtual users or an unexpected repeat request |
| p95 rises but errors stay low | Phase 3 Application RED; then Phase 4 Log Explorer | p95 query above; `{service="app"} \| json` | Injected latency, PostgreSQL delay, or resource contention |
| Error rate rises | Phase 3 Application RED; app logs | `sum(rate(http_requests_total{route="/",status=~"5.."}[1m]))` | Error-burst injection, app interruption, or dependency failure |
| An exporter target disappears | Prometheus **Status → Targets**; Phase 2 dashboard | `up{job=~"node-exporter|cadvisor|nginx-exporter|postgres-exporter"}` | Exporter was deliberately stopped or failed |
| App CPU or memory pressure changes | Phase 2 Host and containers; Phase 3 Application RED | cAdvisor CPU and working-set queries from Phase 2 | Bounded CPU/memory experiment or load; cAdvisor label granularity varies by host |

## Phase 6: Alerting and first response

### The concept

An alert rule evaluates a PromQL expression repeatedly. The rule can remain
pending for a configured `for` duration before becoming firing, which filters
brief spikes. Labels such as `severity` classify the alert; annotations carry
the summary and first-response hint. Prometheus sends firing and resolved
notifications to Alertmanager, which groups related alerts and routes them to
the configured receiver.

This lab's webhook receiver is local-only: it logs incoming notification
summaries and retains the latest payload in memory at `/alerts`. Alertmanager
does not send messages to email, Teams, or any external endpoint. Blackbox
Exporter separately probes `http://nginx:8080/health`, so a service check is
measured from the monitoring network path rather than inferred only from
Prometheus scrape health.

The "no data" exercise watches PostgreSQL exporter's `pg_up` series with
`absent_over_time`. It models a missing freshness signal such as a backup
heartbeat, not an actual backup system. The HTTP probe alert uses the
Blackbox-exported `probe_success` metric.

### Look at the running system

1. Open **Dashboards → Lab → Phase 6 - Alerts and probes**. With a healthy stack,
   the probe should be `1` and there should be no firing alerts.
2. Open Prometheus **Alerts** to see the eight rules and their states; the
   configured `for` duration is visible for pending alerts.
3. Open Alertmanager at http://127.0.0.1:9093 to inspect notification groups.
4. Open http://127.0.0.1:8090/alerts to inspect the latest locally received
   notification payload (it is in-memory and resets on receiver restart).
5. Read [docs/RUNBOOK.md](RUNBOOK.md) for alert-by-alert first response.

### PromQL to try

1. `ALERTS` — current pending/firing alert series and their labels.
2. `ALERTS{alertstate="firing"}` — only firing rules.
3. `up{job!="prometheus"}` — scrape health for all targets other than the
   Prometheus self-scrape.
4. `probe_success{job="blackbox-http"}` — independent HTTP health-probe result.
5. `absent_over_time(pg_up{job="postgres-exporter"}[5m])` — whether expected
   database health telemetry has been missing for five minutes.

### Break it, then investigate

The **safe baseline test** is to inspect all services and the alert pages:

```sh
docker compose ps
curl -fsS http://127.0.0.1:9115/metrics
curl -fsS http://127.0.0.1:8090/health
```

For a non-disruptive webhook-path check, submit a clearly named test alert to
the local Alertmanager API. It is a synthetic notification only; it does not
change Prometheus rule state or inject load:

```sh
start_time=$(date -u -d '1 minute ago' +%Y-%m-%dT%H:%M:%SZ)
end_time=$(date -u -d '+2 minutes' +%Y-%m-%dT%H:%M:%SZ)
curl -X POST http://127.0.0.1:9093/api/v2/alerts \
  -H "Content-Type: application/json" \
  -d "[{\"labels\":{\"alertname\":\"LabWebhookSmokeTest\",\"severity\":\"info\"},\"annotations\":{\"summary\":\"Local webhook delivery test\"},\"startsAt\":\"$start_time\",\"endsAt\":\"$end_time\",\"generatorURL\":\"http://127.0.0.1:9090/alerts\"}]"
```

After a few seconds, inspect `http://127.0.0.1:8090/alerts`. This verifies the
Alertmanager-to-receiver route without stopping a service. To test the actual
rule transitions for target-down or probe failure, use the Phase 5
`stop-exporter.sh` or `kill-app.sh` experiment only when you are ready to
interrupt the local lab; restore the target promptly and confirm the alert
resolves. High CPU, disk, memory, error-rate, latency, and no-data alerts need
their stated threshold and duration, so do not expect a brief test to trigger
them.

To mark the synthetic notification resolved, post it again with the same
labels and a past end time:

```sh
end_time=$(date -u -d '1 minute ago' +%Y-%m-%dT%H:%M:%SZ)
curl -X POST http://127.0.0.1:9093/api/v2/alerts \
  -H "Content-Type: application/json" \
  -d "[{\"labels\":{\"alertname\":\"LabWebhookSmokeTest\",\"severity\":\"info\"},\"annotations\":{\"summary\":\"Local webhook delivery test\"},\"startsAt\":\"$start_time\",\"endsAt\":\"$end_time\",\"generatorURL\":\"http://127.0.0.1:9090/alerts\"}]"
```

### Investigation checklist

| Symptom | Dashboard or view | Query / check | Possible cause |
|---|---|---|---|
| TargetDown is pending or firing | Prometheus **Targets** and **Alerts** | `up{job!="prometheus"}` | Target container stopped, unhealthy, or unreachable |
| Probe is failing while scrapes are up | Phase 6 dashboard; Blackbox metrics | `probe_success{job="blackbox-http"}` | HTTP health endpoint or service network path failed |
| Alert is firing but no notification arrived | Alertmanager; receiver `/health` and `/alerts` | `ALERTS{alertstate="firing"}` | Alertmanager route, receiver health, or group-wait interval |
| DatabaseMetricsNoData fires | Prometheus **Targets**; Postgres exporter logs | `absent_over_time(pg_up{job="postgres-exporter"}[5m])` | Exporter stopped or the metric series stopped arriving; this is not proof of backup failure |
| A threshold alert resolves slowly | Prometheus **Alerts**; Phase 2/3 dashboards | Check rule `for` duration and expression | Recovery must persist through evaluation; rate/percentile windows retain recent samples |

## Phase 7: Distributed tracing with Tempo

### The concept

Metrics show how often a condition occurs, and logs describe individual
events. A trace follows one request across its work: the inbound Flask request
is the parent span, and instrumented PostgreSQL operations appear as child
spans. Each span has a trace ID shared by every span in that request. This
reveals where time was spent and whether slow work occurred in the app or its
database call.

The app uses OpenTelemetry Flask and psycopg instrumentation and exports spans
using OTLP over HTTP to Tempo. Tempo stores traces locally for 48 hours; the
Grafana Tempo datasource is provisioned from file. App JSON request logs include
the active trace and span IDs, and Grafana's trace-to-logs integration filters
the Loki stream by trace ID. Traces are not sent outside the Compose network.

### Look at the running system

1. Confirm Tempo is ready at http://127.0.0.1:3200/ready.
2. Generate a request at http://127.0.0.1:8080/ and wait several seconds for
   the batch exporter to send spans.
3. In Grafana **Explore**, choose **Tempo**, select service `app`, and run one
   of the TraceQL queries below.
4. Open a returned trace. Inspect the Flask server span and PostgreSQL child
   spans, then use **Logs for this span** / the trace-to-logs action to locate
   the matching JSON request log.
5. For a controlled slow span, set a small PostgreSQL delay as in Phase 3,
   make one request, and then clear chaos. Compare the database child-span
   duration with the overall request span and the p95 metric.

### TraceQL to try

1. `{ resource.service.name = "app" }` — search traces emitted by Flask.
2. `{ resource.service.name = "app" } | duration > 500ms` — find long traces.
3. `{ resource.service.name = "app" && status = error }` — find traces with an
   error status.
4. `{ resource.service.name = "app" && span.http.route = "/" }` — find traces
   for the home-page route.
5. `{ resource.service.name = "app" } >> { span.db.system = "postgresql" }`
   — find request traces with a descendant PostgreSQL span.

### Break it, then investigate

Inject a 600 ms database delay for one request, and always clear the setting
afterward:

```sh
. ./.env
curl -sS -X POST "http://127.0.0.1:${APP_PORT}/chaos" \
  -H "Content-Type: application/json" \
  -H "X-Admin-Token: $CHAOS_ADMIN_TOKEN" \
  -d '{"db_delay_ms":600}'
curl -sS "http://127.0.0.1:${APP_PORT}/"
curl -sS -X DELETE "http://127.0.0.1:${APP_PORT}/chaos" \
  -H "X-Admin-Token: $CHAOS_ADMIN_TOKEN"
```

Find the matching trace in Tempo and compare total request duration with the
PostgreSQL child span. Then use trace-to-logs to confirm the same trace ID is
present in the app's JSON request log. Finally compare with the Phase 3 RED
dashboard: traces explain an individual slow request while the histogram shows
whether that latency is common across requests.

### Investigation checklist

| Symptom | Dashboard or view | Query / check | Possible cause |
|---|---|---|---|
| No traces appear | Grafana Tempo Explore; Tempo `/ready`; app logs | `{ resource.service.name = "app" }` | Tempo unavailable, OTLP export endpoint wrong, or no request has completed |
| Trace exists but has no database child | Open trace in Tempo | Inspect spans under the Flask server span | Request did not query PostgreSQL, or psycopg instrumentation was not loaded |
| Trace-to-logs returns no lines | Trace details; Phase 4 Log Explorer | Search app logs for the trace ID | Batch log ingestion delay, missing trace ID in the JSON line, or time-range mismatch |
| Request is slow and DB span dominates | Tempo trace, then Phase 3 RED dashboard | Long-trace query and p95 histogram | Slow SQL, injected `db_delay_ms`, or database contention |
