#!/usr/bin/env bash
# Деплой на VPS: rsync + docker compose build.
# Использование с рабочей станции:
#   DEPLOY_HOST=valera@185.106.95.16 ./scripts/deploy-vps.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEPLOY_HOST="${DEPLOY_HOST:-valera@185.106.95.16}"
SSH_KEY="${SSH_KEY:-$HOME/.ssh/id_ed25519}"
DEPLOY_DIR="${DEPLOY_DIR:-/home/valera/studio-book}"
SSH=(ssh -i "$SSH_KEY" -o BatchMode=yes -o ConnectTimeout=25 -o ConnectionAttempts=3)
RSYNC_SSH="ssh -i ${SSH_KEY} -o BatchMode=yes -o ConnectTimeout=25"

log() { printf '==> %s\n' "$*"; }

[[ -f "$ROOT/.env" ]] || { echo "Нет $ROOT/.env"; exit 1; }

log "Каталог на сервере ${DEPLOY_DIR}"
"${SSH[@]}" "$DEPLOY_HOST" "mkdir -p '${DEPLOY_DIR}/data'"

log "Синхронизация кода"
rsync -az --delete \
  --exclude '.git/' \
  --exclude '.venv/' \
  --exclude 'venv/' \
  --exclude '.env' \
  --exclude '*.db' \
  --exclude 'bot.log' \
  --exclude '__pycache__/' \
  --exclude '.pytest_cache/' \
  -e "$RSYNC_SSH" \
  "$ROOT/" "${DEPLOY_HOST}:${DEPLOY_DIR}/"

log "Синхронизация .env (BOT_TOKEN / BOT_USERNAME на VPS не затираем)"
python3 - "$ROOT/.env" <<'PY' | "${SSH[@]}" "$DEPLOY_HOST" "cat > '${DEPLOY_DIR}/.env.incoming'"
import sys
from pathlib import Path
sys.stdout.write(Path(sys.argv[1]).read_text())
PY
"${SSH[@]}" "$DEPLOY_HOST" "python3 '${DEPLOY_DIR}/scripts/merge_vps_env.py' '${DEPLOY_DIR}'"

log "Сборка и запуск"
"${SSH[@]}" "$DEPLOY_HOST" "cd '${DEPLOY_DIR}' && docker compose -f docker-compose.prod.yml up -d --build"

log "Логи (15 сек)"
sleep 8
"${SSH[@]}" "$DEPLOY_HOST" "docker compose -f '${DEPLOY_DIR}/docker-compose.prod.yml' logs --tail 40"
