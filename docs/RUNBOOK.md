# Alert runbook

All alerts in this lab notify the local Alertmanager webhook receiver only.
Before changing or removing data, check the affected service and confirm that
the experiment is not intentionally running.

## TargetDown

1. In Prometheus, open **Status → Targets** and identify the failed job.
2. Check `docker compose ps` and `docker compose logs <service>`.
3. Verify its health endpoint and service DNS/network path; restore only the
   affected lab service.

## HighCPU

1. Check the Phase 2 host/container dashboard and the CPU experiment or k6 run.
2. Compare `rate(node_cpu_seconds_total{mode="idle"}[5m])` with cAdvisor CPU
   metrics; Docker Desktop reports its Linux VM, not Windows host CPU.
3. Stop the bounded experiment or traffic run and confirm CPU returns to normal.

## LowDiskSpace

1. Check the Phase 2 filesystem metrics and identify the root filesystem.
2. Check Docker Desktop disk usage and lab volume sizes before taking action.
3. Do not delete volumes as a first response; `docker compose down --volumes`
   deletes the lab's stored metrics, logs, Grafana state, and database data.

## HighMemory

1. Check Phase 2 memory metrics and whether `memory-pressure.sh` or k6 is
   currently running.
2. Correlate cAdvisor working-set metrics with the affected workload.
3. End the bounded experiment and verify memory recovers; avoid restarting
   unrelated services.

## HighApplicationErrorRate

1. Check the Phase 3 RED dashboard for the error ratio and request volume.
2. Open the linked Phase 4 app logs and run
   `{service="app"} | json | status >= 500`.
3. Check PostgreSQL health (`pg_up`) and the authenticated `/chaos` state.
   Clear an intentional chaos test with `DELETE /chaos`.

## HighApplicationP95Latency

1. Check the Phase 3 RED dashboard and compare p50, p95, and p99.
2. Inspect app logs and check PostgreSQL exporter health and resource panels.
3. Check whether `slow-database.sh`, latency injection, or a traffic test is
   running; stop the test and confirm latency recovers.

## DatabaseMetricsNoData

This is a backup-style missing-freshness-signal exercise using `pg_up` as the
expected periodic signal; it does not assert that a real backup system exists.

1. Check Prometheus **Status → Targets** for `postgres-exporter`.
2. Check `docker compose logs postgres-exporter` and the PostgreSQL container
   health.
3. Restore the exporter or database path. Verify `pg_up` returns and the alert
   resolves; distinguish missing telemetry from a database explicitly reporting
   `pg_up == 0`.

## HttpProbeFailed

1. Check `probe_success` and `probe_duration_seconds` for `blackbox-http`.
2. Visit the local app `/health` endpoint and check nginx and app health.
3. Inspect `docker compose logs blackbox-exporter nginx app` and verify the
   probe target uses the internal Docker service name.
