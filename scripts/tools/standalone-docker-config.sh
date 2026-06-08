#!/usr/bin/env bash
set -euo pipefail

env_file="${STANDALONE_ENV_FILE:-.env.standalone}"
if [ -f "$env_file" ]; then
  set -a
  # shellcheck disable=SC1090
  . "$env_file"
  set +a
fi

domain="${STANDALONE_DOMAIN:-app.example.local}"
runtime_dir="${STANDALONE_RUNTIME_DIR:-.standalone}"
tls_mode="${STANDALONE_TLS_MODE:-self-signed}"
upstream_url="${STANDALONE_UPSTREAM_URL:-http://app-27:5000}"
bind_ip="${STANDALONE_BIND_IP:-0.0.0.0}"
tls_dir="${runtime_dir}/tls"
nginx_dir="${runtime_dir}/nginx"

case "$domain" in
  *[!A-Za-z0-9._-]* | "" | .* | *..* | *.)
    echo "Invalid STANDALONE_DOMAIN: $domain" >&2
    exit 2
    ;;
esac

case "$upstream_url" in
  http://* | https://*) ;;
  *)
    echo "STANDALONE_UPSTREAM_URL must start with http:// or https://." >&2
    exit 2
    ;;
esac

mkdir -p "$tls_dir" "$nginx_dir"

run_privileged() {
  if [ "$(id -u 2>/dev/null || printf '1')" = "0" ]; then
    "$@"
  elif command -v sudo >/dev/null 2>&1; then
    sudo -n "$@"
  else
    return 1
  fi
}

ensure_openssl() {
  if command -v openssl >/dev/null 2>&1; then
    return
  fi
  if [ "${STANDALONE_AUTO_INSTALL_OPENSSL:-true}" != "true" ]; then
    echo "openssl is required for STANDALONE_TLS_MODE=${tls_mode}." >&2
    exit 2
  fi

  echo "openssl is missing; attempting automatic package install."
  if command -v apt-get >/dev/null 2>&1; then
    run_privileged apt-get update
    run_privileged apt-get install -y openssl
  elif command -v dnf >/dev/null 2>&1; then
    run_privileged dnf install -y openssl
  elif command -v yum >/dev/null 2>&1; then
    run_privileged yum install -y openssl
  else
    echo "Could not install openssl automatically; install it or set STANDALONE_TLS_MODE=provided." >&2
    exit 2
  fi

  if ! command -v openssl >/dev/null 2>&1; then
    echo "openssl install did not make openssl available on PATH." >&2
    exit 2
  fi
}

is_ip_address() {
  case "$1" in
    *[!0-9.]* | "" | *.*.*.*.*) return 1 ;;
    *.*.*.*) return 0 ;;
    *) return 1 ;;
  esac
}

generate_self_signed_tls() {
  ca_key="${tls_dir}/standalone-ca.key"
  ca_crt="${tls_dir}/standalone-ca.crt"
  leaf_key="${tls_dir}/tls.key"
  leaf_crt="${tls_dir}/tls.crt"
  csr="${tls_dir}/standalone.csr"
  openssl_conf="${tls_dir}/standalone.openssl.cnf"
  alt_names="${tls_dir}/standalone.alt-names"

  dns_index=1
  ip_index=1
  : > "$alt_names"

  add_dns_name() {
    printf 'DNS.%s = %s\n' "$dns_index" "$1" >> "$alt_names"
    dns_index=$((dns_index + 1))
  }

  add_ip_name() {
    printf 'IP.%s = %s\n' "$ip_index" "$1" >> "$alt_names"
    ip_index=$((ip_index + 1))
  }

  add_dns_name "$domain"
  if is_ip_address "$bind_ip" && [ "$bind_ip" != "0.0.0.0" ]; then
    add_ip_name "$bind_ip"
  fi

  old_ifs="$IFS"
  IFS=','
  for raw_san in ${STANDALONE_TLS_EXTRA_SANS:-}; do
    san="$(printf '%s' "$raw_san" | sed 's/^ *//;s/ *$//')"
    [ -n "$san" ] || continue
    case "$san" in
      DNS:*) add_dns_name "${san#DNS:}" ;;
      IP:*) add_ip_name "${san#IP:}" ;;
      *)
        if is_ip_address "$san"; then
          add_ip_name "$san"
        else
          add_dns_name "$san"
        fi
        ;;
    esac
  done
  IFS="$old_ifs"

  if [ ! -s "$ca_key" ] || [ ! -s "$ca_crt" ]; then
    openssl genrsa -out "$ca_key" 4096
    openssl req -x509 -new -nodes -key "$ca_key" -sha256 -days 3650 \
      -subj "/CN=Urban Platform Standalone CA" -out "$ca_crt"
  fi

  {
    printf '%s\n' '[req]'
    printf '%s\n' 'default_bits = 2048'
    printf '%s\n' 'prompt = no'
    printf '%s\n' 'default_md = sha256'
    printf '%s\n' 'distinguished_name = dn'
    printf '%s\n' 'req_extensions = v3_req'
    printf '%s\n\n' '[dn]'
    printf 'CN = %s\n\n' "$domain"
    printf '%s\n' '[v3_req]'
    printf '%s\n' 'basicConstraints = CA:FALSE'
    printf '%s\n' 'keyUsage = digitalSignature, keyEncipherment'
    printf '%s\n' 'extendedKeyUsage = serverAuth'
    printf '%s\n\n' 'subjectAltName = @alt_names'
    printf '%s\n' '[alt_names]'
    cat "$alt_names"
  } > "$openssl_conf"

  openssl genrsa -out "$leaf_key" 2048
  openssl req -new -key "$leaf_key" -out "$csr" -config "$openssl_conf"
  openssl x509 -req -in "$csr" -CA "$ca_crt" -CAkey "$ca_key" -CAcreateserial \
    -out "$leaf_crt" -days 3650 -sha256 -extensions v3_req -extfile "$openssl_conf"
}

install_provided_tls() {
  cert_file="${STANDALONE_TLS_CERT_FILE:-}"
  key_file="${STANDALONE_TLS_KEY_FILE:-}"
  if [ -z "$cert_file" ] || [ -z "$key_file" ]; then
    echo "STANDALONE_TLS_MODE=${tls_mode} requires STANDALONE_TLS_CERT_FILE and STANDALONE_TLS_KEY_FILE." >&2
    exit 2
  fi
  cp "$cert_file" "${tls_dir}/tls.crt"
  cp "$key_file" "${tls_dir}/tls.key"
}

install_pfx_tls() {
  pfx_file="${STANDALONE_TLS_PFX_FILE:-}"
  pass_file="${STANDALONE_TLS_PFX_PASSWORD_FILE:-}"
  if [ -z "$pfx_file" ]; then
    echo "STANDALONE_TLS_MODE=pfx requires STANDALONE_TLS_PFX_FILE." >&2
    exit 2
  fi
  pass_arg=()
  if [ -n "$pass_file" ]; then
    pass_arg=(-passin "file:${pass_file}")
  else
    pass_arg=(-passin pass:)
  fi
  openssl pkcs12 -in "$pfx_file" "${pass_arg[@]}" -clcerts -nokeys -out "${tls_dir}/tls.crt"
  openssl pkcs12 -in "$pfx_file" "${pass_arg[@]}" -nocerts -nodes -out "${tls_dir}/tls.key"
}

case "$tls_mode" in
  self-signed)
    ensure_openssl
    generate_self_signed_tls
    ;;
  provided | wildcard | lets-encrypt | letsencrypt)
    install_provided_tls
    ;;
  pfx)
    ensure_openssl
    install_pfx_tls
    ;;
  *)
    echo "Unsupported STANDALONE_TLS_MODE: $tls_mode" >&2
    echo "Supported modes: self-signed, provided, wildcard, lets-encrypt, pfx." >&2
    exit 2
    ;;
esac

cat > "${nginx_dir}/nginx.conf" <<EOF
worker_processes auto;
pid /tmp/nginx.pid;

events {
    worker_connections 1024;
}

http {
    client_body_temp_path /tmp/client_body;
    proxy_temp_path /tmp/proxy;
    fastcgi_temp_path /tmp/fastcgi;
    uwsgi_temp_path /tmp/uwsgi;
    scgi_temp_path /tmp/scgi;
    server_tokens off;

    server {
        listen 8080 default_server;
        server_name _;
        return 308 https://${domain}\$request_uri;
    }

    server {
        listen 8443 ssl default_server;
        server_name ${domain};

        ssl_certificate /etc/nginx/tls/tls.crt;
        ssl_certificate_key /etc/nginx/tls/tls.key;
        ssl_protocols TLSv1.2 TLSv1.3;

        add_header X-Content-Type-Options nosniff always;
        add_header X-Frame-Options SAMEORIGIN always;
        add_header X-XSS-Protection "1; mode=block" always;

        if (\$host != "${domain}") {
            return 308 https://${domain}\$request_uri;
        }

        location / {
            proxy_http_version 1.1;
            proxy_set_header Host \$host;
            proxy_set_header X-Forwarded-Proto https;
            proxy_set_header X-Forwarded-Host \$host;
            proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
            proxy_set_header Upgrade \$http_upgrade;
            proxy_set_header Connection "upgrade";
            proxy_pass ${upstream_url};
        }
    }
}
EOF

echo "Standalone Docker config ready:"
echo "- nginx config: ${nginx_dir}/nginx.conf"
echo "- TLS cert: ${tls_dir}/tls.crt"
if [ "$tls_mode" = "self-signed" ]; then
  echo "- trust this CA on client machines: ${tls_dir}/standalone-ca.crt"
fi
echo "- URL: https://${domain}"
