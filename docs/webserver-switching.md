# Webserver Switching

Default webserver is `nginxinc/nginx-unprivileged:1.31.1`. Default ingress controller is RKE2-bundled Traefik.

```bash
python3 scripts/configure.py --ingress-controller traefik --webserver nginx
python3 scripts/configure.py --ingress-controller nginx --webserver nginx
python3 scripts/configure.py --webserver apache-httpd
python3 scripts/configure.py --webserver apache-tomcat
python3 scripts/configure.py --webserver traefik
make deploy
```

Profiles are in `config/webservers.yaml` and `helm/urban-platform-infra/values.yaml`.

For RKE2, keep `rke2_traefik_source: bundled` in inventory to use the Traefik
version tested with the pinned `rke2_version`. To pin an upstream Traefik chart
instead, set `rke2_traefik_source: upstream`,
`rke2_traefik_chart_version: "40.2.0"`, and
`rke2_traefik_image_tag: "v3.7.1"`.
