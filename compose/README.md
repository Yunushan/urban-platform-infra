# Docker fallback profile

`docker-compose.ha.yml` is a compatibility profile for development, demos, and migration testing. It is not the preferred production HA path; use the RKE2/Kubernetes profile for enterprise production.

```bash
make docker-up
make docker-status
make docker-down
```

For a single-host standalone run with private local IP, FQDN, TLS, nginx, and
database image pins, use the variable-driven overlay. Keep `.env.standalone`
private and do not commit real addresses, domains, passwords, or certificates.

```bash
cp .env.standalone.example .env.standalone
$EDITOR .env.standalone
make docker-standalone-up
make docker-standalone-status
make docker-standalone-down
```

The default `STANDALONE_TLS_MODE=self-signed` writes a local CA to
`.standalone/tls/standalone-ca.crt`. Trust that CA on client machines to avoid
browser authority warnings. Use `STANDALONE_TLS_MODE=provided`, `wildcard`,
`lets-encrypt`, or `pfx` when an operator-managed certificate already exists.

For real Docker HA, initialize Docker Swarm and use `docker stack deploy`:

```bash
docker swarm init
REGISTRY_PREFIX=registry.example.com/urban-platform docker stack deploy -c docker-compose.ha.yml urban-platform
```
