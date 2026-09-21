#!/usr/bin/env bash
set -euo pipefail
: "${DEPLOY_PATH:?DEPLOY_PATH is required}"
APP_ENV="$DEPLOY_PATH/deploy/app.env"
if [[ ! -f "$APP_ENV" ]]; then
  echo "Missing $APP_ENV (copy from deploy/app.env.example)"
  exit 1
fi
set -a
# shellcheck disable=SC1090
source "$APP_ENV"
set +a
: "${UNIVERSITY_HOST:?}"
: "${PSY_HOST:?}"
: "${CERTBOT_EMAIL:?}"
: "${GHCR_USER:?}"
COMPOSE_FILE="$DEPLOY_PATH/docker-compose.prod.yml"
COMPOSE_ENV="$DEPLOY_PATH/compose.env"
INIT_TPL="$DEPLOY_PATH/deploy/nginx/site.init.conf.template"
SSL_TPL="$DEPLOY_PATH/deploy/nginx/site.conf.template"
WEBROOT="/var/www/certbot"
DOMAINS=("$UNIVERSITY_HOST" "$PSY_HOST")
install_packages() {
  apt-get update -qq
  DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
    nginx certbot python3-certbot-nginx curl
  if ! command -v docker >/dev/null; then
    DEBIAN_FRONTEND=noninteractive apt-get install -y -qq docker.io docker-compose-plugin
  fi
  systemctl enable --now docker nginx
}
render_site() {
  local domain="$1" template="$2"
  sed "s/__DOMAIN__/${domain}/g" "$template" > "/etc/nginx/sites-available/${domain}"
  ln -sfn "/etc/nginx/sites-available/${domain}" "/etc/nginx/sites-enabled/${domain}"
}
reload_nginx() {
  nginx -t
  systemctl reload nginx
}
ensure_ssl() {
  local domain="$1"
  local cert="/etc/letsencrypt/live/${domain}/fullchain.pem"
  if [[ -f "$cert" ]]; then
    echo "Cert already exists for ${domain}"
    render_site "$domain" "$SSL_TPL"
    return 0
  fi
  render_site "$domain" "$INIT_TPL"
  reload_nginx
  mkdir -p "$WEBROOT"
  if certbot certonly --webroot -w "$WEBROOT" \
    -d "$domain" -d "www.${domain}" \
    --email "$CERTBOT_EMAIL" --agree-tos --no-eff-email --non-interactive; then
    render_site "$domain" "$SSL_TPL"
  else
    echo "Certbot failed for ${domain}; leaving HTTP-only nginx"
  fi
}
deploy_stack() {
  cd "$DEPLOY_PATH"
  if [[ ! -f "$COMPOSE_ENV" ]]; then
    echo "Missing $COMPOSE_ENV"
    exit 1
  fi
  : "${GHCR_TOKEN:?GHCR_TOKEN is required in the environment}"
  echo "$GHCR_TOKEN" | docker login ghcr.io -u "$GHCR_USER" --password-stdin
  docker compose --env-file "$COMPOSE_ENV" -f "$COMPOSE_FILE" pull
  docker compose --env-file "$COMPOSE_ENV" -f "$COMPOSE_FILE" up -d --remove-orphans
}
wait_local() {
  local url="$1"
  local i
  for i in $(seq 1 30); do
    if curl -fsS "$url" >/dev/null; then
      echo "OK $url"
      return 0
    fi
    sleep 2
  done
  echo "Failed $url"
  docker compose --env-file "$COMPOSE_ENV" -f "$COMPOSE_FILE" logs --tail 80
  exit 1
}
if ! command -v docker >/dev/null || ! command -v nginx >/dev/null; then
  install_packages
fi
mkdir -p /etc/nginx/sites-available /etc/nginx/sites-enabled "$WEBROOT"
rm -f /etc/nginx/sites-enabled/default
deploy_stack
wait_local "http://127.0.0.1:13002/"
wait_local "http://127.0.0.1:8000/api/v1/health/"
for domain in "${DOMAINS[@]}"; do
  ensure_ssl "$domain"
done
reload_nginx
