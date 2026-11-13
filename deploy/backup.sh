#!/usr/bin/env bash
# Daily database backup (installed to /etc/cron.daily by install.sh). Keeps 14 days.
#
# Encryption: put one or more `age` public keys (age1…) in /etc/globalvpn/backup-recipients and
# every dump is encrypted to them (`age -R`). Keep the matching private key OFF this server;
# then a copied or stolen backup reveals nothing. Restore: age -d -i key.txt db-….dump.age > db.dump
set -euo pipefail
DIR=/var/backups/globalvpn
RECIPIENTS=/etc/globalvpn/backup-recipients
install -d -m 0700 "$DIR"
cd /opt/globalvpn/deploy
umask 077
dump() {
  docker compose -f docker-compose.prod.yml --env-file .env.prod exec -T postgres \
    sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --format=custom'
}
STAMP=$(date +%F)
if [[ -s $RECIPIENTS ]] && command -v age >/dev/null; then
  dump | age -R "$RECIPIENTS" > "$DIR/db-$STAMP.dump.age.tmp"
  mv "$DIR/db-$STAMP.dump.age.tmp" "$DIR/db-$STAMP.dump.age"
  rm -f "$DIR/db-$STAMP.dump"
else
  echo "warning: backups are NOT encrypted (no $RECIPIENTS) — see the header of this script" >&2
  dump > "$DIR/db-$STAMP.dump.tmp"
  mv "$DIR/db-$STAMP.dump.tmp" "$DIR/db-$STAMP.dump"
fi
chmod 600 "$DIR"/db-* 2>/dev/null || true
find "$DIR" -name 'db-*' -mtime +14 -delete
