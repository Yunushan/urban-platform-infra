#!/usr/bin/env python3
import argparse
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[1]

def load_yaml(path):
    with open(path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)

def write_yaml(path, data):
    with open(path, 'w', encoding='utf-8') as f:
        yaml.safe_dump(data, f, sort_keys=False, default_flow_style=False, width=120)

def main():
    parser = argparse.ArgumentParser(description='Switch urban-platform-infra defaults without editing templates.')
    parser.add_argument('--engine', choices=['rke2','k3s','microk8s','docker','raw'])
    parser.add_argument('--webserver', choices=['nginx','apache-httpd','apache-tomcat','traefik'])
    parser.add_argument('--ingress-controller', choices=['traefik','nginx'])
    parser.add_argument('--database')
    parser.add_argument('--observability', choices=['disabled','elasticsearch','loki','opensearch','graylog','clickhouse','grafana'])
    parser.add_argument('--values', default=str(ROOT / 'helm/urban-platform-infra/values.yaml'))
    args = parser.parse_args()

    values_path = Path(args.values)
    values = load_yaml(values_path)

    if args.engine:
        values.setdefault('global', {}).setdefault('cluster', {})['engine'] = args.engine
    if args.webserver:
        values.setdefault('webserver', {})['provider'] = args.webserver
        for name, provider in values.get('webserver', {}).get('providers', {}).items():
            provider['enabled'] = name == args.webserver
    if args.ingress_controller:
        values.setdefault('ingress', {})['className'] = args.ingress_controller
    if args.database:
        # PostgreSQL-compatible databases use CloudNativePG; other databases are represented as external/operator profiles.
        if args.database in ['postgresql','postgres','postgis','timescaledb']:
            values.setdefault('databases', {})['provider'] = 'cloudnative-pg'
        else:
            values.setdefault('databases', {})['provider'] = args.database
    if args.observability:
        obs = values.setdefault('observability', {})
        obs['profile'] = args.observability
        disabled = args.observability == 'disabled'
        stack = obs.setdefault('stack', {})
        if disabled:
            stack.update({
                'name': 'disabled',
                'logging': 'none',
                'search': 'none',
                'metrics': 'none',
                'dashboards': 'none',
                'telemetry': 'none',
                'traces': 'none',
            })
        else:
            stack.update({
                'name': 'elastic-eck-prometheus-grafana-opentelemetry' if args.observability == 'elasticsearch' else args.observability,
                'logging': args.observability,
                'search': args.observability if args.observability in ['elasticsearch', 'opensearch'] else 'none',
                'metrics': 'prometheus',
                'dashboards': 'grafana',
                'telemetry': 'opentelemetry',
                'traces': 'opentelemetry',
            })
        for key in ['loki','opensearch','graylog','clickhouse']:
            obs.setdefault(key, {})['enabled'] = (not disabled) and key == args.observability
        obs.setdefault('elasticsearch', {})['enabled'] = args.observability == 'elasticsearch'
        obs.setdefault('kibana', {})['enabled'] = args.observability == 'elasticsearch'
        obs.setdefault('grafana', {})['enabled'] = (not disabled) and args.observability in ['grafana','loki','clickhouse','elasticsearch']
        obs.setdefault('prometheus', {})['enabled'] = not disabled
        obs.setdefault('opentelemetry', {})['enabled'] = not disabled
        obs.setdefault('logstash', {})['enabled'] = args.observability == 'elasticsearch'

    write_yaml(values_path, values)
    print(f'Updated {values_path}')

if __name__ == '__main__':
    main()
