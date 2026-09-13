#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
HOST=manabi
DOMAIN=biblenotes.cc
MODE=check
SEED=0
ASSETS=1
BOOTSTRAP=0
usage() {
  cat <<'HELP'
Usage: bash deploy/deploy.sh [check|deploy|tls] [options]
  --host NAME       SSH alias (default: manabi)
  --domain NAME     HTTPS hostname (default: biblenotes.cc)
  --seed-local      Export local Docker DB; import ONLY into an empty remote DB
  --skip-assets     Skip audio/image sync on code-only updates
  --bootstrap       Install Ubuntu Docker/Nginx/Certbot dependencies
  --help            Show this help
Default command is read-only check. No passwords or SSH keys are stored here.
HELP
}
while (($#)); do
  case "$1" in
    check|deploy|tls) MODE="$1"; shift;;
    --host|--domain) (($# >= 2)) || { usage; exit 2; }; if [[ "$1" == --host ]]; then HOST="$2"; else DOMAIN="$2"; fi; shift 2;;
    --seed-local) SEED=1; shift;;
    --skip-assets) ASSETS=0; shift;;
    --bootstrap) BOOTSTRAP=1; shift;;
    --help|-h) usage; exit 0;;
    *) usage; exit 2;;
  esac
done
[[ "$HOST" =~ ^[a-zA-Z0-9][a-zA-Z0-9_.-]*$ ]] || { echo 'Invalid SSH alias'; exit 2; }
[[ "$DOMAIN" =~ ^[a-zA-Z0-9]([a-zA-Z0-9.-]*[a-zA-Z0-9])?$ && "$DOMAIN" == *.* ]] || { echo 'Invalid domain'; exit 2; }
SSH=(ssh -o ControlMaster=auto -o ControlPersist=600 -o ControlPath=/tmp/manabi-deploy-%C -o IPQoS=none -c aes128-gcm@openssh.com -o BatchMode=yes -o ConnectTimeout=15 "$HOST")
if [[ "$MODE" == check ]]; then
  "${SSH[@]}" "bash -s -- '$DOMAIN'" <<'REMOTE'
set -euo pipefail
echo 'Domain addresses:'
getent ahostsv4 "$1" || true
getent ahostsv6 "$1" || true
echo 'Deployment:'
if [[ -f /opt/manabi/compose.yml ]]; then
  cd /opt/manabi
  docker compose ps
  docker compose exec -T db psql -U manabi -d manabi -Atc "SELECT count(*) AS public_tables FROM information_schema.tables WHERE table_schema='public';" </dev/null
fi
if [[ -d /opt/manabi/assets ]]; then du -sh /opt/manabi/assets; fi
curl --max-time 10 -fsS "https://$1/api/v1/health" || echo 'HTTPS is not ready.'
REMOTE
  exit 0
fi
command -v rsync >/dev/null
if [[ "$MODE" == deploy && "$ASSETS" == 1 && ! -d "$ROOT/../mojitest_spider/data/assets" ]]; then echo 'Assets directory missing; use --skip-assets only if remote resources already exist.'; exit 1; fi
STAGE="/opt/manabi/staging/$(date -u +%Y%m%dT%H%M%SZ)-$$"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
chmod 700 "$TMP"
if [[ "$MODE" != deploy && "$SEED" == 1 ]]; then echo "--seed-local requires deploy"; exit 2; fi
if [[ "$SEED" == 1 ]]; then
  echo 'Exporting local DB (local data is unchanged)…'
  (cd "$ROOT" && docker compose exec -T db pg_dump -U manabi -d manabi -Fc --no-owner --no-acl) > "$TMP/seed.dump"
  chmod 600 "$TMP/seed.dump"
fi
if [[ "$BOOTSTRAP" == 1 ]]; then
  "${SSH[@]}" 'command -v rsync >/dev/null || (apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y rsync)'
fi
"${SSH[@]}" "install -d -m 700 '$STAGE/api' '$STAGE/deploy'"
if [[ "$MODE" == deploy ]]; then
rsync -rt --exclude=.venv --exclude=.env --exclude=data --exclude=__pycache__ --exclude=.pytest_cache --exclude=deploy --exclude=.git -e 'ssh -o ControlMaster=auto -o ControlPersist=600 -o ControlPath=/tmp/manabi-deploy-%C -o IPQoS=none -c aes128-gcm@openssh.com -o BatchMode=yes' "$ROOT/" "$HOST:$STAGE/api/"
fi
rsync -rt -e 'ssh -o ControlMaster=auto -o ControlPersist=600 -o ControlPath=/tmp/manabi-deploy-%C -o IPQoS=none -c aes128-gcm@openssh.com -o BatchMode=yes' "$ROOT/deploy/" "$HOST:$STAGE/deploy/"
if [[ "$MODE" == tls ]]; then
  "${SSH[@]}" "flock -n /opt/manabi/deploy.lock bash '$STAGE/deploy/tls.sh' '$DOMAIN' '$STAGE' && rm -rf '$STAGE'"
  curl --fail --show-error --max-time 20 "https://$DOMAIN/api/v1/health"
  exit 0
fi
if [[ "$SEED" == 1 ]]; then rsync -rt --partial --bwlimit=256 -e 'ssh -o ControlMaster=auto -o ControlPersist=600 -o ControlPath=/tmp/manabi-deploy-%C -o IPQoS=none -c aes128-gcm@openssh.com -o BatchMode=yes' "$TMP/seed.dump" "$HOST:$STAGE/seed.dump"; fi
if [[ "$ASSETS" == 1 ]]; then
  echo 'Syncing audio/images (existing resources are not deleted)…'
  "${SSH[@]}" 'install -d -m 755 /opt/manabi/assets'
  rsync -rt --partial --stats -e 'ssh -o ControlMaster=auto -o ControlPersist=600 -o ControlPath=/tmp/manabi-deploy-%C -o IPQoS=none -c aes128-gcm@openssh.com -o BatchMode=yes' "$ROOT/../mojitest_spider/data/assets/" "$HOST:/opt/manabi/assets/"
fi
"${SSH[@]}" "flock -n /opt/manabi/deploy.lock bash '$STAGE/deploy/remote.sh' '$DOMAIN' '$STAGE' '$BOOTSTRAP' '$SEED'"
curl --fail --show-error --max-time 20 "https://$DOMAIN/api/v1/health"
printf '\nDeployment verified: https://%s\n' "$DOMAIN"
