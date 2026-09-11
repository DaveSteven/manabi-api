#!/usr/bin/env bash
set -euo pipefail
umask 077
DOMAIN="$1"; STAGE="$2"; BOOTSTRAP="$3"; SEED="$4"
[[ $EUID == 0 ]] || { echo 'The SSH user must be root for this deployment.'; exit 1; }
[[ "$DOMAIN" =~ ^[a-zA-Z0-9][a-zA-Z0-9.-]*$ && "$STAGE" == /opt/manabi/staging/* ]] || exit 2
cd /opt/manabi
if [[ "$BOOTSTRAP" == 1 ]]; then
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -qq
  apt-get install -y docker.io docker-compose-v2 nginx certbot rsync curl
  systemctl enable --now docker nginx
  if command -v ufw >/dev/null && ufw status | grep -q 'Status: active'; then
    ufw allow 80/tcp
    ufw allow 443/tcp
  fi
fi
for tool in docker nginx rsync python3 curl; do command -v "$tool" >/dev/null; done
CERTBOT=$(command -v certbot || true)
if [[ -z "$CERTBOT" && -x /opt/certbot/bin/certbot ]]; then CERTBOT=/opt/certbot/bin/certbot; fi
[[ -n "$CERTBOT" ]] || { echo 'Certbot missing; rerun with --bootstrap.'; exit 1; }
python3 - <<'PY'
from pathlib import Path
import secrets
p=Path('/opt/manabi/.env')
if not p.exists(): p.write_text('POSTGRES_PASSWORD='+secrets.token_hex(32)+'\n')
p.chmod(0o600)
PY
install -d -m 700 backups
# Refuse reseeding before changing any running application.
if [[ -f compose.yml ]]; then
  docker compose up -d --wait db
  TABLES=$(docker compose exec -T db psql -U manabi -d manabi -Atc "SELECT count(*) FROM information_schema.tables WHERE table_schema='public';")
else TABLES=0; fi
if [[ "$SEED" == 1 && "$TABLES" != 0 ]]; then
  echo 'Refusing to import: remote DB is not empty. Rerun without --seed-local.'
  rm -f "$STAGE/seed.dump"
  exit 1
fi
if [[ "$TABLES" == 0 && "$SEED" != 1 ]]; then
  echo 'Remote DB is empty. First deployment requires --seed-local.'
  exit 1
fi
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
if [[ "$TABLES" != 0 ]]; then
  docker compose exec -T db pg_dump -U manabi -d manabi -Fc --no-owner --no-acl > "backups/pre-deploy-$STAMP.dump"
fi
if [[ -d api ]]; then tar -czf "backups/code-$STAMP.tar.gz" api compose.yml; fi
rsync -rt --delete "$STAGE/api/" api/
cp "$STAGE/deploy/compose.yml" compose.yml
install -d -m 755 assets
# Build first; the current API stays running if build fails.
docker compose build api
docker compose up -d --wait db
if [[ "$SEED" == 1 ]]; then
  docker compose exec -T db pg_restore -U manabi -d manabi --no-owner --no-acl --exit-on-error --single-transaction < "$STAGE/seed.dump"
  # Local login tokens must not become valid on the public server.
  docker compose exec -T db psql -U manabi -d manabi -v ON_ERROR_STOP=1 -c 'DELETE FROM tokens;'
  mv "$STAGE/seed.dump" "backups/initial-$STAMP.dump"
fi
docker compose run --rm --no-deps api python -m alembic upgrade head
docker compose up -d --wait --wait-timeout 120 api
curl --fail --max-time 15 http://127.0.0.1:8001/api/v1/health
bash "$STAGE/deploy/tls.sh" "$DOMAIN" "$STAGE"
rm -rf "$STAGE"
