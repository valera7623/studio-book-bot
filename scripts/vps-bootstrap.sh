#!/usr/bin/env bash
# Одноразовая подготовка VPS РФ: каталог деплоя и data/. Запуск на сервере.
set -euo pipefail

DEPLOY_ROOT="${DEPLOY_ROOT:-/home/valera/studio-book}"

if [[ "${EUID:-$(id -u)}" -ne 0 ]] && ! mkdir -p "$DEPLOY_ROOT" 2>/dev/null; then
  echo "Нет прав на ${DEPLOY_ROOT}. Запустите: sudo DEPLOY_ROOT=${DEPLOY_ROOT} $0"
  exit 1
fi

mkdir -p "${DEPLOY_ROOT}/data"
chmod 755 "${DEPLOY_ROOT}" "${DEPLOY_ROOT}/data"

if [[ "${EUID:-$(id -u)}" -eq 0 ]] && [[ -n "${SUDO_USER:-}" ]]; then
  chown -R "${SUDO_USER}:${SUDO_USER}" "${DEPLOY_ROOT}"
fi

echo "Готово: ${DEPLOY_ROOT} и ${DEPLOY_ROOT}/data"
echo "Дальше: скопируйте в ${DEPLOY_ROOT}/.env файл с BOT_TOKEN, ADMINS и"
echo "  DOCKER_IMAGE=<ваш_docker_hub_login>/studio-book:latest"
echo "Добавьте SSH public key в ~/.ssh/authorized_keys пользователя деплоя."
echo "ПДн (152-ФЗ): хостинг только в РФ."
