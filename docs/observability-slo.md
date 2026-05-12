# Observability, SLOs, and Production Operations

This project should be observable before it is scaled. The default enterprise stack is Elastic ECK plus Prometheus/Grafana plus OpenTelemetry Collector: Elasticsearch/Kibana/Logstash handle log search, kube-prometheus-stack provides metrics and dashboards, and OpenTelemetry Collector gathers cluster telemetry. SLO and alerting resources are disabled by default in the application chart so the chart can render without Prometheus Operator CRDs, then enabled after `kube-prometheus-stack` is installed.

## Article 8 Baseline

The production baseline is:

1. Install ECK, kube-prometheus-stack/Grafana, and OpenTelemetry Collector through `deploy/helmfile.yaml.gotmpl`.
2. Enable chart monitoring only after the Prometheus Operator CRDs exist.
3. Keep service objectives in `config/slo.yaml`.
4. Keep alert runbooks in `docs/runbooks.md`.
5. Page only on user-impacting or data-risk conditions; create tickets for early warning.

## Enable Monitoring Rules

Example production override:

```yaml
monitoring:
  enabled: true
  prometheus:
    releaseLabel: kube-prometheus-stack
  prometheusRules:
    enabled: true
    runbookBaseUrl: https://example.com/runbooks/urban-platform
```

The chart emits `PrometheusRule` resources for Kubernetes availability signals:

- Deployment replicas unavailable.
- Stateful dependency replicas unavailable.
- Elevated container restart rate.
- HPA saturation.
- Persistent volume capacity pressure.

## Service Monitors

ServiceMonitor generation is generic and disabled until a service exposes real Prometheus-format metrics. Do not create fake `/metrics` targets for placeholder services.

Example:

```yaml
monitoring:
  enabled: true
  serviceMonitors:
    enabled: true
    targets:
      - name: app-01
        selector:
          matchLabels:
            app.kubernetes.io/name: app-01
        endpoints:
          - port: http
            path: /metrics
```

## Operational Reviews

Every monthly operations review should answer:

- Which SLOs consumed error budget?
- Which alerts paged humans?
- Which alerts created noise?
- Which services had rising restart, saturation, or storage-pressure trends?
- Which dashboard or runbook was missing during incidents?

## References

- Prometheus Operator API: https://prometheus-operator.dev/docs/api-reference/api/
- Kubernetes probes: https://kubernetes.io/docs/concepts/configuration/liveness-readiness-startup-probes/
- Google SRE SLOs: https://sre.google/sre-book/service-level-objectives/
- Grafana SLO best practices: https://grafana.com/docs/grafana-cloud/alerting-and-irm/slo/best-practices/
