# API возвратов: Contract-First Development

В этом задании нужно описать API управления заявками на возврат в OpenAPI 3.0.3, проверить по контракту готовый сервис и исправить найденные ошибки.

Начните с [бизнес-требований](docs/requirements.md). Реализация может расходиться с ними, поэтому переносить её поведение в спецификацию не нужно.

## Запуск

Нужен Python 3.12.

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.lock.txt
python -m pip install --no-deps -e .
uvicorn refund_api.app:app --host 127.0.0.1 --port 8000
```

Сервис доступен на `http://127.0.0.1:8000`. Проверка запуска:

```bash
curl http://127.0.0.1:8000/health
```

Или через Docker:

```bash
docker compose up --build
```

База SQLite создаётся при первом запуске и заполняется данными из `fixtures/`. При обычном запуске она хранится в `data/refunds.sqlite3`, в Docker — в отдельном томе. Чтобы начать с чистой базы локально, остановите сервис и запустите его с другим путём:

```bash
REFUNDS_DB_PATH=data/new-run.sqlite3 uvicorn refund_api.app:app --host 127.0.0.1 --port 8000
```

## Что лежит в проекте

| Путь | Содержимое |
|---|---|
| `docs/requirements.md` | Бизнес-правила, операции и форматы данных |
| `contracts/openapi.yaml` | Шаблон спецификации, который нужно заполнить |
| `refund_api/` | Сервис на FastAPI с ошибками для поиска и исправления |
| `fixtures/` | Исходные заказы и заявки на возврат |
| `tests/` | Проверки окружения, контрактные и сценарные тесты |
| `docs/assignment.md` | Порядок работы и состав сдачи |
| `docs/testing.md` | Команды и пояснения к проверкам |
| `docs/report-template.md` | Шаблон отчёта |

Автоматическая спецификация FastAPI и страницы `/docs`, `/redoc` отключены. Контракт нужно составить по требованиям.

## Пример запроса

```bash
curl -i http://127.0.0.1:8000/refunds \
  -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: example-001' \
  -d '{
    "order_id": "11111111-1111-4111-8111-111111111111",
    "amount": 1500,
    "currency": "RUB",
    "reason": "Возврат товара"
  }'
```

Проверять статус, тело и заголовки ответа нужно по требованиям и вашей спецификации.

## Проверки

Готовые части проекта:

```bash
python -m pytest -m 'not assignment'
```

После заполнения спецификации:

```bash
python -m openapi_spec_validator contracts/openapi.yaml
python -m pytest tests/test_contract.py
```

Сценарии задания и весь набор тестов:

```bash
python -m pytest -m assignment
python -m pytest
```

В стартовой версии часть проверок задания падает. Разберите причины, зафиксируйте их в отчёте и исправьте сервис. Подробности — в [описании задания](docs/assignment.md).
