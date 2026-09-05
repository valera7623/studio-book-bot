# Бот записи в фотостудию

Telegram-бот почасовой записи для фотостудий (РФ/СНГ). Одна задача: слот → запись по ссылке → предоплата → напоминание.

Не CRM, не конструктор ботов, не горизонталь «для всех пространств». Подкаст-студии — шаблон после первых платящих.

Вертикаль: только фотостудии (зал / циклорама / грим).

## Что есть

- Публичная запись по `t.me/Studio_book_bot?start=<slug>`: зал → дата → длительность → слот → контакты → согласие ПДн → hold.
- Кабинет `/studio`: залы (до 6 на тарифе Плюс), часы, сетка цен, правила, ссылка и QR, тексты для клиентов, брони, закрытие интервалов, отмена, iCal.
- Предоплата 50/100% и подписка владельца через Prodamus (чек 54-ФЗ); webhook идемпотентен; возврат при отмене по правилу 24–120 ч.
- Напоминания за 24 ч и за 2 ч, истечение hold (20 мин – 24 ч на студии). Бэкап SQLite в `data/backups/`.
- Студийный час: шаг 30/60, минимум 1/2 ч, буфер уборки, наценка за одиночный час, будни/выходные/ночь.
- Free / 490 / 990. Публичный лендинг с прайсом: `https://studiobook.com.ru/` (якорь `#prices`). Traefik → бот `:8088`, см. [deploy/traefik-studiobook.yml](deploy/traefik-studiobook.yml).
- Проверка боли: [docs/pain_check.md](docs/pain_check.md). Аутрич: [docs/outreach.md](docs/outreach.md). Касса и пилот: [docs/go_live.md](docs/go_live.md).

## Доступ

| Роль | Как попадает | Что видит |
|---|---|---|
| Клиент студии | `t.me/Studio_book_bot?start=<slug>` или `start=book_<id>` | Публичная запись, `/my` отмена, без пароля |
| Владелец студии | Онбординг и привязка Telegram | Кабинет: слоты, брони, отмена, часы, тексты |
| Админ платформы | `ADMINS` в `.env` | `/admin` — саппорт продукта, не контент |
| Superadmin | `SUPERADMINS` (пусто = `ADMINS`) | `/superadmin` — кол-во и Telegram ID платных подписчиков |

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
- Чеки 54-ФЗ и возврат — через Prodamus, не руками. Шаблон правил: `data/legal/cancel_rules.md`.

## Структура

```
src/main.py                 polling, ParseMode.HTML
src/config.py               pydantic-settings
src/bot/loader.py           Dispatcher, FSM (MemoryStorage; Redis опционально)
src/middlewares/            Database, User, Throttling, Logging
src/database/               engine, Base, модели
src/handlers/               /start /studio /help /my, запись, кабинет
src/services/               слоты, hold, тарифы, Prodamus, iCal, jobs, отмены
src/web/app.py              лендинг, webhook, подписка .ics
landing/index.html          лендинг-минимум
docs/go_live.md             ключи Prodamus, три платежа, пилот за вечер
docs/pain_check.md          скрипт разговоров с владельцами
docs/outreach.md            тексты аутрича и kill 3–5%
data/legal/consent_pdn.md   согласие на ПДн
data/legal/cancel_rules.md  шаблон отмены / обеспечительный платёж
```

Инфраструктура снята со справочника СМП (`/home/ubuntu/my_telegram_bot-1`). Тот репозиторий не менялся.

## Деплой

Прод: VPS `185.106.95.16`, каталог `/home/valera/studio-book`, контейнер `studio-book-bot-1`.

Автодеплой: push в `main` репозитория [valera7623/studio-book-bot](https://github.com/valera7623/studio-book-bot) → GitHub Actions собирает образ `ghcr.io/valera7623/studio-book-bot` и перезапускает контейнер. Вручную: Actions → Deploy studio-book to VPS → Run workflow.

Секреты репозитория: `VPS_HOST`, `VPS_USERNAME`, `VPS_SSH_KEY`.

Локально на VPS без Actions: `./scripts/deploy-vps.sh`.
