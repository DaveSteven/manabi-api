#!/usr/bin/env bash
set -euo pipefail
umask 077
DOMAIN="$1"; STAGE="$2"
[[ $EUID == 0 && "$DOMAIN" =~ ^[a-zA-Z0-9][a-zA-Z0-9.-]*$ && "$STAGE" == /opt/manabi/staging/* ]] || exit 2
CERTBOT=$(command -v certbot || true)
if [[ -z "$CERTBOT" && -x /opt/certbot/bin/certbot ]]; then CERTBOT=/opt/certbot/bin/certbot; fi
[[ -n "$CERTBOT" ]] || { echo 'Certbot is not installed.'; exit 1; }
# Preserve working HTTPS on subsequent updates. Bootstrap challenge-only HTTP once.
install -d -m 755 /var/www/letsencrypt
if [[ ! -f "/etc/letsencrypt/live/$DOMAIN/fullchain.pem" ]]; then
  sed "s/@DOMAIN@/$DOMAIN/g" "$STAGE/deploy/nginx-http.conf" > /etc/nginx/sites-available/manabi
  ln -sfn /etc/nginx/sites-available/manabi /etc/nginx/sites-enabled/manabi
  # Only disable the distribution's unused default site.
  if [[ -L /etc/nginx/sites-enabled/default && "$(readlink /etc/nginx/sites-enabled/default)" == /etc/nginx/sites-available/default ]]; then rm /etc/nginx/sites-enabled/default; fi
  nginx -t
  systemctl reload nginx
fi
# Verify the origin challenge route; the CA independently validates public reachability.
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
PROBE="manabi-$STAMP-$RANDOM"
install -d -m 755 /var/www/letsencrypt/.well-known/acme-challenge
printf '%s' "$PROBE" > "/var/www/letsencrypt/.well-known/acme-challenge/$PROBE"
chmod 644 "/var/www/letsencrypt/.well-known/acme-challenge/$PROBE"
ANSWER=$(curl --retry 5 --retry-all-errors --retry-delay 3 --fail --silent --show-error --max-time 20 --resolve "$DOMAIN:80:127.0.0.1" "http://$DOMAIN/.well-known/acme-challenge/$PROBE") || ANSWER=''
rm -f "/var/www/letsencrypt/.well-known/acme-challenge/$PROBE"
[[ "$ANSWER" == "$PROBE" ]] || { echo 'DNS/HTTP challenge failed. Set the domain A record to this server (DNS only) and rerun without --seed-local.'; exit 1; }
"$CERTBOT" certonly --non-interactive --agree-tos --register-unsafely-without-email --webroot -w /var/www/letsencrypt --cert-name "$DOMAIN" -d "$DOMAIN" --keep-until-expiring
install -m 644 "$STAGE/deploy/nginx-proxy.conf" /etc/nginx/manabi-proxy.conf
sed "s/@DOMAIN@/$DOMAIN/g" "$STAGE/deploy/nginx.conf" > /etc/nginx/sites-available/manabi
ln -sfn /etc/nginx/sites-available/manabi /etc/nginx/sites-enabled/manabi
nginx -t
systemctl reload nginx
# Works for both distribution and /opt/certbot installations.
cat > /etc/systemd/system/manabi-cert-renew.service <<UNIT
[Unit]
Description=Renew Manabi TLS certificate
[Service]
Type=oneshot
ExecStart=$CERTBOT renew --quiet --deploy-hook "systemctl reload nginx"
UNIT
cat > /etc/systemd/system/manabi-cert-renew.timer <<'UNIT'
[Unit]
Description=Check Manabi certificate renewal twice daily
[Timer]
OnCalendar=*-*-* 00,12:15:00
RandomizedDelaySec=3600
Persistent=true
[Install]
WantedBy=timers.target
UNIT
systemctl daemon-reload
systemctl enable --now manabi-cert-renew.timer
curl --fail --max-time 15 --resolve "$DOMAIN:443:127.0.0.1" "https://$DOMAIN/api/v1/health"
echo "HTTPS ready: https://$DOMAIN"
