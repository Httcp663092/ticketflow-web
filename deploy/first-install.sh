#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
release=$(cd "$(dirname "$0")/.." && pwd)
case "$release" in /opt/ticketflow/releases/*) ;; *) echo "Unexpected release directory"; exit 1;; esac
[ "$(id -u)" = 0 ] || { echo 'Run as root'; exit 1; }
[ ! -e /opt/ticketflow/current ] || { echo 'Existing TicketFlow deployment found; refusing first install'; exit 1; }
[ ! -e /opt/ticketflow/shared/runtime.env ] || { echo 'Existing runtime config found; refusing overwrite'; exit 1; }
if ss -lntH | awk '{print $4}' | grep -Eq ':18080$'; then echo 'Port 18080 is occupied'; exit 1; fi
install -d -m 700 /opt/ticketflow/shared /opt/ticketflow/backups
if docker volume ls --filter label=com.docker.compose.project=ticketflow-prod -q | grep -q .; then echo 'Existing TicketFlow volumes found; refusing migration'; exit 1; fi
python3 - "$release" <<'PYENV'
from pathlib import Path
import json,secrets,sys
root=Path('/opt/ticketflow/shared')
release=Path(sys.argv[1]).name
password=secrets.token_hex(24)
secret=secrets.token_urlsafe(48)
admin_password=secrets.token_urlsafe(24)
values={'POSTGRES_PASSWORD':password,'DATABASE_URL':f'postgresql+psycopg://ticketflow:{password}@db:5432/ticketflow','SECRET_KEY':secret,'TICKETFLOW_RELEASE':release,'TICKETFLOW_ENV_FILE':'/opt/ticketflow/shared/runtime.env','TICKETFLOW_API_PORT':'18080'}
with (root/'runtime.env').open('x') as f:f.write(''.join(f'{k}={v}\n' for k,v in values.items()))
with (root/'bootstrap.json').open('x') as f:json.dump({'username':'admin','password':admin_password},f)
with (root/'first-login.txt').open('x') as f:f.write('TicketFlow 首次登录\n网址：https://8.159.144.194/ticketflow/\n账号：admin\n初始密码：'+admin_password+'\n首次登录后请在个人设置中修改密码。\n')
for name in ['runtime.env','bootstrap.json','first-login.txt']:(root/name).chmod(0o600)
PYENV
cp -L /etc/nginx/sites-enabled/pulse-public /opt/ticketflow/shared/nginx-pulse-public.before
sha256sum /opt/ticketflow/shared/nginx-pulse-public.before > /opt/ticketflow/shared/nginx-before.sha256
curl --fail --silent --show-error https://8.159.144.194/ -o /opt/ticketflow/shared/existing-root.before
export TICKETFLOW_ENV_FILE=/opt/ticketflow/shared/runtime.env
set -a
. "$TICKETFLOW_ENV_FILE"
set +a
dc(){ docker compose --env-file "$TICKETFLOW_ENV_FILE" -f "$release/deploy/compose.prod.yaml" "$@"; }
trap 'status=$?; echo "INSTALL_FAILED:$status (existing Nginx unchanged)"; exit "$status"' ERR
if docker ps -a --filter label=com.docker.compose.project=ticketflow-prod --format '{{.ID}}' | grep -q .; then echo 'TicketFlow containers already exist'; exit 1; fi
echo 'PHASE: build API image'
dc config --quiet
dc build api
echo 'PHASE: start isolated database'
dc up -d --wait --wait-timeout 120 db
echo 'PHASE: validate PostgreSQL migration roundtrip on new empty database'
dc run --rm -T api alembic upgrade head
dc run --rm -T api alembic downgrade base
dc run --rm -T api alembic upgrade head
echo 'PHASE: create first administrator'
dc run --rm -T api python -m app.bootstrap < /opt/ticketflow/shared/bootstrap.json
echo 'PHASE: run regression tests'
dc run --rm -T api python -m pytest -q -p no:cacheprovider
echo 'PHASE: start API'
dc up -d --wait --wait-timeout 120 api
curl --fail --silent --show-error http://127.0.0.1:18080/api/health
# Only public static assets are served by the host proxy.
chmod 755 /opt/ticketflow /opt/ticketflow/releases "$release" "$release/public" "$release/public/ticketflow"
find "$release/public" -type d -exec chmod 755 {} +
find "$release/public" -type f -exec chmod 644 {} +
ln -s "$release" /opt/ticketflow/current
printf '%s\n' "$release" > /opt/ticketflow/shared/installed-release
printf 'READY_FOR_PROXY\n'
