#!/usr/bin/env bash
# Прод-код только из GHCR (GitHub Actions: push в main).
# Скрипт не собирает образ: merge .env + перезапуск контейнера.
#   DEPLOY_HOST=valera@185.106.95.16 ./scripts/deploy-vps.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEPLOY_HOST="${DEPLOY_HOST:-valera@185.106.95.16}"
SSH_KEY="${SSH_KEY:-$HOME/.ssh/id_ed25519}"
DEPLOY_DIR="${DEPLOY_DIR:-/home/valera/studio-book}"
GHCR_IMAGE="${GHCR_IMAGE:-ghcr.io/valera7623/studio-book-bot:latest}"
SSH=(ssh -i "$SSH_KEY" -o BatchMode=yes -o ConnectTimeout=25 -o ConnectionAttempts=3)
RSYNC_SSH="ssh -i ${SSH_KEY} -o BatchMode=yes -o ConnectTimeout=25"

log() { printf '==> %s\n' "$*"; }

[[ -f "$ROOT/.env" ]] || { echo "Нет $ROOT/.env"; exit 1; }

log "Каталог на сервере ${DEPLOY_DIR}"
"${SSH[@]}" "$DEPLOY_HOST" "mkdir -p '${DEPLOY_DIR}/data' '${DEPLOY_DIR}/scripts'"

log "compose и merge_vps_env (не исходники бота)"
rsync -az -e "$RSYNC_SSH" \
  "$ROOT/docker-compose.prod.yml" \
  "${DEPLOY_HOST}:${DEPLOY_DIR}/"
rsync -az -e "$RSYNC_SSH" \
  "$ROOT/scripts/merge_vps_env.py" \
  "${DEPLOY_HOST}:${DEPLOY_DIR}/scripts/"

log "Синхронизация .env (BOT_TOKEN / BOT_USERNAME на VPS не затираем)"
python3 - "$ROOT/.env" <<'PY' | "${SSH[@]}" "$DEPLOY_HOST" "cat > '${DEPLOY_DIR}/.env.incoming'"
import sys
from pathlib import Path
sys.stdout.write(Path(sys.argv[1]).read_text())
PY
"${SSH[@]}" "$DEPLOY_HOST" "python3 '${DEPLOY_DIR}/scripts/merge_vps_env.py' '${DEPLOY_DIR}'"

log "Перезапуск образа GHCR без сборки"
"${SSH[@]}" "$DEPLOY_HOST" bash -s -- "$DEPLOY_DIR" "$GHCR_IMAGE" <<'EOS'
set -euo pipefail
DEPLOY_DIR="$1"
GHCR_IMAGE="$2"
cd "$DEPLOY_DIR"
if grep -q '^DOCKER_IMAGE=studio-book:local' .env 2>/dev/null || ! grep -q '^DOCKER_IMAGE=' .env 2>/dev/null; then
  if grep -q '^DOCKER_IMAGE=' .env 2>/dev/null; then
    sed -i "s|^DOCKER_IMAGE=.*|DOCKER_IMAGE=${GHCR_IMAGE}|" .env
  else
    printf '\nDOCKER_IMAGE=%s\n' "$GHCR_IMAGE" >> .env
  fi
fi
docker compose -f docker-compose.prod.yml up -d --no-build --force-recreate
docker compose -f docker-compose.prod.yml ps
EOS

log "Логи"
sleep 8
"${SSH[@]}" "$DEPLOY_HOST" "docker compose -f '${DEPLOY_DIR}/docker-compose.prod.yml' logs --tail 40"
