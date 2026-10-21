#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
exec 9>/opt/ticketflow/shared/backup.lock
flock -n 9 || exit 0
export TICKETFLOW_ENV_FILE=/opt/ticketflow/shared/runtime.env
set -a
. "$TICKETFLOW_ENV_FILE"
set +a
release=$(readlink -f /opt/ticketflow/current)
dc(){ docker compose --env-file "$TICKETFLOW_ENV_FILE" -f "$release/deploy/compose.prod.yaml" "$@"; }
dest="/opt/ticketflow/backups/backup-$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -m 700 "$dest"
dc exec -T db pg_dump -U ticketflow -d ticketflow -Fc > "$dest/database.dump"
dc exec -T api tar -C /data/attachments -czf - . > "$dest/attachments.tar.gz"
printf '%s\n' "$release" > "$dest/release.txt"
(cd "$dest" && sha256sum database.dump attachments.tar.gz release.txt > SHA256SUMS)
printf '%s\n' "$dest"
# Retention is intentionally manual until an off-host backup destination is chosen.
