# Service levels and operations

Only needed once something is deployed. Based on the Google SRE Workbook: start small and imperfect.

## SLOs (≤ 5, 4-week rolling window)

| SLI | Target | Measured by |
|---|---|---|
| Availability: successful requests / all requests | 99.5% | _uptime monitor / metrics_ |
| Latency: requests under _X_ ms | 95% | _metrics_ |

**Error-budget policy:** when the budget is spent, stop feature work and fix reliability until it recovers.

## Observability

- Errors: Sentry (free Developer plan) or equivalent.
- Traces and metrics: OpenTelemetry → Grafana Cloud free tier (or any OTLP backend).
- Logs: structured JSON with trace IDs.

## Incidents

Write a blameless postmortem for user-visible outages, data loss, security incidents or a spent error budget: what happened, impact, timeline, root cause, what we'll change. Store under `docs/runbooks/postmortems/`.
