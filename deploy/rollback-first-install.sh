#!/usr/bin/env bash
# Restores only the route added by this first install; keeps TicketFlow data volumes.
set -Eeuo pipefail
umask 077
current=/etc/nginx/sites-enabled/pulse-public
backup=/opt/ticketflow/shared/nginx-pulse-public.before
python3 - "$current" "$backup" <<'PYCODE'
from pathlib import Path
import sys
source=Path(sys.argv[1]).resolve(); before=Path(sys.argv[2]).read_text()
expected=before.replace('server {','server {\n    include /etc/nginx/snippets/ticketflow.conf;',1)
if source.read_text()!=expected:raise SystemExit('Nginx changed since install; manual review required')
source.write_text(before)
PYCODE
nginx -t
systemctl reload nginx
systemctl disable --now ticketflow-backup.timer 2>/dev/null || true
export TICKETFLOW_ENV_FILE=/opt/ticketflow/shared/runtime.env
set -a
. "$TICKETFLOW_ENV_FILE"
set +a
docker compose --env-file "$TICKETFLOW_ENV_FILE" -f /opt/ticketflow/current/deploy/compose.prod.yaml stop api db
printf 'TicketFlow route removed and its containers stopped; data volumes retained.\n'
