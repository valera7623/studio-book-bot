# Бот записи в фотостудию

Telegram-бот почасовой записи для фотостудий (РФ/СНГ). Одна задача: слот → запись по ссылке → предоплата → напоминание.

Не CRM, не конструктор ботов, не горизонталь «для всех пространств». Подкаст-студии — шаблон после первых платящих, не в MVP.

Вертикаль первых 30 дней: только фотостудии (зал / циклорама / грим).

## Что есть в MVP

- Публичная запись по `t.me/bot?start=<slug>`: дата → слот → контакты → согласие ПДн → hold.
- Кабинет владельца `/studio`: ресурс, часы, цена, ссылка и QR, брони, отмена, iCal.
- Предоплата слота и подписка владельца через Prodamus (чек 54-ФЗ у кассы); webhook идемпотентен.
- Напоминания и истечение hold — APScheduler. Бэкап SQLite в `data/backups/`.
- Free / 490 / 990. Лендинг: `landing/index.html` (HTTP `:8088`).
- Проверка боли: [docs/pain_check.md](docs/pain_check.md) — 8–10 разговоров до рекламы.

## Доступ

| Роль | Как попадает | Что видит |
|---|---|---|
| Клиент студии | `t.me/bot?start=<slug>` или `start=book_<id>` | Публичная запись, без пароля |
| Владелец студии | Онбординг и привязка Telegram | Кабинет: слоты, брони, отмена, часы |
| Админ платформы | `ADMINS` в `.env` | `/admin` — саппорт продукта, не контент |

## Быстрый старт

```bash
cp .env.example .env
# укажите BOT_TOKEN
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python create_tables.py
python -m src.main
```

Docker:

```bash
docker compose up -d --build
```

Тесты:

```bash
pytest
```

## Комплаенс

- ПДн только на хостинге в РФ (152-ФЗ). Cloud Supabase / Vercel для ПДн — нельзя.
- Согласие на обработку — отдельный документ, не оферта.
- Чеки 54-ФЗ — через Prodamus (неделя 2), не руками.

## Структура

```
src/main.py                 polling, ParseMode.HTML
src/config.py               pydantic-settings
src/bot/loader.py           Dispatcher, FSM (MemoryStorage; Redis опционально)
src/middlewares/            Database, User, Throttling, Logging
src/database/               engine, Base, модели
src/handlers/               /start /studio /help, запись, кабинет
src/services/               слоты, hold, тарифы, Prodamus, iCal, jobs
src/web/app.py              лендинг, webhook, подписка .ics
landing/index.html          лендинг-минимум
docs/pain_check.md          скрипт разговоров с владельцами
data/legal/consent_pdn.md   согласие на ПДн
```

Инфраструктура снята со справочника СМП (`/home/ubuntu/my_telegram_bot-1`). Тот репозиторий не менялся. Выкинуты: клинические модели, ingest DOCX, whitelist, `/register`, `MASTER_PASSWORD`, `AccessControlMiddleware`, python-docx.

## Деплой

Прод: VPS `185.106.95.16`, каталог `/home/valera/studio-book`, контейнер `studio-book-bot-1`.

Автодеплой: push в `main` репозитория [valera7623/studio-book-bot](https://github.com/valera7623/studio-book-bot) → GitHub Actions собирает образ `ghcr.io/valera7623/studio-book-bot` и перезапускает контейнер. Вручную: Actions → Deploy studio-book to VPS → Run workflow.

Секреты репозитория: `VPS_HOST`, `VPS_USERNAME`, `VPS_SSH_KEY`.

Локально на VPS без Actions: `./scripts/deploy-vps.sh`.
