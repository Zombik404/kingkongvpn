#!/usr/bin/env bash
# Daily database backup (installed to /etc/cron.daily by install.sh). Keeps 14 days.
set -euo pipefail
DIR=/var/backups/globalvpn
install -d -m 0700 "$DIR"
cd /opt/globalvpn/deploy
docker compose -f docker-compose.prod.yml --env-file .env.prod exec -T postgres \
  sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --format=custom' > "$DIR/db-$(date +%F).dump"
chmod 600 "$DIR"/db-*.dump
find "$DIR" -name 'db-*.dump' -mtime +14 -delete
