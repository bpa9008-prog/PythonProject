# Cardio Clinic

Информационная система кардиологической клиники с REST API на FastAPI.
Итоговый проект по дисциплине «Разработка на Python и инженерия данных».

Система ведёт пациентов и врачей, записывает на приёмы по бизнес-правилам, хранит результаты медосмотров
и оценивает по ним риск сердечно-сосудистого заболевания с помощью ML-модели.
Данные можно массово загрузить из CSV (ETL), а по накопленной истории строятся аналитические отчёты.

> Это учебный проект, а не медицинское изделие: оценка модели не является диагнозом.

## Предметная область

| Что | Как |
|---|---|
| Регистратура | Пациенты и врачи, справочник диагнозов МКБ-10 |
| Запись на приём | Выбор врача и времени с проверкой занятости, часов работы и статуса врача |
| Приём | Статусы: запланирован → состоялся / отменён / неявка; диагнозы ставятся при завершении |
| Медосмотр | Рост, вес, давление, холестерин, глюкоза → риск заболевания от ML-модели (low / medium / high) |
| Аналитика | Загрузка врачей, динамика риска, топ диагнозов, пациенты с высоким риском без записи |

ML-часть (обучение моделей, `/predict`, `/predict-from-csv`, `/upload-model`) осталась из лабораторной №10 и описана в
[docs/ml-service.md](docs/ml-service.md). Здесь она встроена в систему: модель оценивает риск при сохранении осмотра.

## Стек

Python 3.12 · FastAPI · Pydantic 2 · SQLAlchemy 2 · Alembic · PostgreSQL 16 (SQLite в тестах) · pandas · scikit-learn ·
pytest + pytest-cov · ruff · HTML/JS без фреймворков (ESLint, Prettier, node:test) · Docker Compose · GitHub Actions.

## Запуск

### Docker (основной способ)

```bash
cp .env.example .env            # по желанию; значения по умолчанию подходят
docker compose up --build
```

Поднимется PostgreSQL, применятся миграции, запустится API.

- Интерфейс клиники: http://localhost:8000/clinic.html
- ML-оценка и загрузка модели: http://localhost:8000/
- Swagger: http://localhost:8000/docs

Модель: пока ничего не загружено, используется модель из образа (`models/model.pkl`, воспроизводимый артефакт
`python -m ml.train`; файлы в `reports/` — эталонный отчёт последнего обучения, они перегенерируются той же командой). Загруженная через `/upload-model` хранится в томе
`model-data` (`/app/storage`), переживает перезапуск и пересборку и имеет приоритет над моделью из образа.

Наполнить БД:

```bash
docker compose exec api python -m app.seed                       # врачи, диагнозы, пациенты, приёмы
docker compose exec api python -m app.etl.import_data --source data/raw/cardio_train.csv --score
```

### Локально

```bash
python -m venv .venv
.venv/Scripts/activate           # Windows; на Linux/macOS: source .venv/bin/activate
pip install -r requirements-dev.txt

# БД по умолчанию — файл clinic.db (SQLite); для PostgreSQL задайте DATABASE_URL (см. ниже)
alembic upgrade head             # создать схему
python -m ml.train               # обучить модель, если models/model.pkl ещё нет
python -m app.seed
uvicorn app.main:app --reload
```

### Переменные окружения

Пример — в [.env.example](.env.example). Секреты в коде не хранятся.

| Переменная | По умолчанию | Назначение |
|---|---|---|
| `DATABASE_URL` | `sqlite:///clinic.db` | адрес БД, например `postgresql+psycopg://clinic:clinic@localhost:5432/clinic` |
| `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` | `clinic` | параметры PostgreSQL в docker compose |
| `CLINIC_TIMEZONE` | `UTC` (в compose — `Europe/Moscow`) | часовой пояс, в котором заданы часы работы клиники; неверное значение останавливает запуск |
| `CLINIC_OPEN_HOUR`, `CLINIC_CLOSE_HOUR` | `8`, `20` | часы приёма |
| `MIN_CANCEL_HOURS` | `2` | за сколько часов до приёма ещё можно отменить |
| `RISK_MEDIUM_THRESHOLD`, `RISK_HIGH_THRESHOLD` | `0.4`, `0.7` | границы уровней риска осмотра |
| `RISK_THRESHOLD` | `0.5` | порог вердикта в `/predict` (ML-модуль) |
| `MODEL_PATH`, `METRICS_PATH` | `models/model.pkl`, `reports/metrics.json` | куда сохраняется загруженная модель и где лежат метрики (в compose модель в `/app/storage/model.pkl`) |
| `BUNDLED_MODEL_PATH` | `models/model.pkl` | поставляемая модель: используется, если по `MODEL_PATH` файла ещё нет |
| `MODEL_UPLOAD_TOKEN` | пусто | токен для `/upload-model` (заголовок `X-Upload-Token`); пусто — загрузка открыта |
| `AUTOLOAD_MODEL` | `true` | загружать модель с диска при старте |
| `MAX_UPLOAD_MB` | `50` | лимит размера загружаемых файлов |
| `LOG_LEVEL` | `INFO` | уровень логирования |

## База данных

Шесть таблиц: `patients`, `doctors`, `appointments`, `diagnoses`, `appointment_diagnoses` (многие-ко-многим) и `examinations`.
Подробная схема, ограничения и индексы — в [docs/erd.md](docs/erd.md).

```mermaid
erDiagram
    patients ||--o{ appointments : ""
    doctors ||--o{ appointments : ""
    patients ||--o{ examinations : ""
    appointments ||--o{ examinations : ""
    appointments ||--o{ appointment_diagnoses : ""
    diagnoses ||--o{ appointment_diagnoses : ""
```

Схема создаётся и меняется только через Alembic. Миграция обратима:

```bash
alembic upgrade head
alembic downgrade base
alembic check                    # убедиться, что модели и миграции совпадают
```

## Бизнес-правила

Вся логика лежит в `app/services/`, а не в обработчиках эндпоинтов.

1. **Запись на приём** (`appointments.book_appointment`).
   - Только на будущее время и только в часы работы клиники (в `CLINIC_TIMEZONE`); приём должен целиком попасть в рабочий день.
   - Врач должен быть активен.
   - Врач и пациент не могут иметь пересекающиеся приёмы (приём, который заканчивается ровно в момент начала следующего, допустим).
   - Нарушения: 422 (время), 409 (занятость, неактивный врач), 404 (нет пациента или врача).
   - Строка врача блокируется на время записи (`SELECT … FOR UPDATE`), а частичный уникальный индекс в БД
     не даст двум параллельным запросам занять один слот.
2. **Жизненный цикл приёма.**
   - Статус меняется только из `scheduled`.
   - Отменить можно не позднее чем за `MIN_CANCEL_HOURS` до начала.
   - Неявку можно отметить только после окончания времени приёма.
   - Завершить приём можно только после его начала.
   - Повторная смена статуса даёт 409.
3. **Высокий риск требует диагноза.** Если последний осмотр пациента показал высокий риск, приём нельзя завершить без диагноза (422).
4. **Осмотр сохраняется только с оценкой риска.** Риск считает ML-модель, а уровень определяют пороги: low < 0.4 ≤ medium < 0.7 ≤ high.
   Без загруженной модели осмотр отклоняется (503). Модель оценивает только пациентов от 18 лет, а дата осмотра не может быть в будущем.
5. **Целостность истории.** Пациента с приёмами удалить нельзя (409). Отменённый приём освобождает слот.

## ETL

Импорт пациентов и осмотров из `cardio_train.csv` (70 000 записей) в БД: `app/etl/import_data.py`.

```bash
python -m app.etl.import_data --source data/raw/cardio_train.csv [--limit 5000] [--score] \
    [--measured-on 2025-06-01] [--rejected-out rejected.csv] [--database-url ...]
```

| Этап | Что делает |
|---|---|
| Extract | Читает CSV как строки (разделитель определяется сам); проверяет, что все нужные колонки на месте |
| Validate / clean | Отклоняет строки с пропусками, нечисловыми и дробными значениями в целых колонках, значениями вне допустимых диапазонов (давление 16020, рост 55 см, возраст < 18 лет), нижним давлением выше верхнего, повторами `id` и повторами содержимого |
| Transform | Колонки датасета → таблицы `patients` и `examinations`; дата рождения = дата осмотра − возраст в днях |
| Load | Пачками по 5000 строк, каждая пачка в одной транзакции; `--score` сразу считает риск моделью |

- **Идемпотентность.** Пациент определяется по `external_id` (колонка `id` датасета), и уже загруженные записи пропускаются.
  Повторный запуск ничего не дублирует, а прерванный можно просто запустить заново.
- **Логирование.** В конце печатается сводка, а причины отклонений логируются и (с `--rejected-out`) сохраняются в файл.

Пример на полном датасете:

```
прочитано 70000, отклонено 1423 (diastolic_above_systolic=101, duplicate_record=41, out_of_range=1281),
загружено 68577, уже было в БД 0, оценено моделью 68577, время 3.7 с
```

Повторный запуск: `загружено 0, уже было в БД 68577`.

## API

28 эндпоинтов, полная документация с примерами и кодами ответов — в Swagger (`/docs`). Все ошибки приходят в одном формате `{"status": "error", "detail": ...}`.

| Группа | Эндпоинты |
|---|---|
| Пациенты | `POST/GET /patients`, `GET/PATCH/DELETE /patients/{id}` |
| Осмотры | `POST/GET /patients/{id}/examinations` |
| Врачи и диагнозы | `POST/GET /doctors`, `GET/PATCH /doctors/{id}`, `POST/GET /diagnoses` |
| Приёмы | `POST/GET /appointments`, `GET /appointments/{id}`, `POST /appointments/{id}/cancel`, `/complete`, `/no-show` |
| Аналитика | `GET /analytics/doctor-workload`, `/risk-dynamics`, `/top-diagnoses`, `/risk-followup` |
| ML | `POST /upload-model`, `/predict`, `/predict-from-csv`, `GET /model-info`, `/health` |

Списки (`/patients`, `/doctors`, `/appointments`, `/diagnoses`) поддерживают пагинацию (`limit`, `offset`);
пациенты и приёмы — ещё фильтры и сортировку (`sort_by`, `order`). Все даты и время в API — UTC.

### Примеры

Создать пациента (201):

```bash
curl -X POST localhost:8000/patients -H "Content-Type: application/json" \
  -d '{"full_name": "Иванов Иван Иванович", "birth_date": "1975-04-12", "gender": "M", "phone": "+79991234567"}'
```
```json
{"id": 1, "external_id": null, "full_name": "Иванов Иван Иванович", "birth_date": "1975-04-12",
 "gender": "M", "phone": "+79991234567", "created_at": "2026-11-08T18:24:21"}
```

Записать на приём (201), затем занять то же время (409):

```bash
curl -X POST localhost:8000/appointments -H "Content-Type: application/json" \
  -d '{"patient_id": 1, "doctor_id": 1, "scheduled_at": "2026-12-01T10:00:00Z", "duration_minutes": 30}'
```
```json
{"id": 1, "patient_id": 1, "doctor_id": 1, "scheduled_at": "2026-12-01T10:00:00", "ends_at": "2026-12-01T10:30:00",
 "status": "scheduled", "reason": "Контроль давления", "notes": null, "diagnoses": [], "created_at": "2026-11-08T18:24:21"}
```
```json
{"status": "error", "detail": "Врач занят в это время"}
```

Завершить приём до его начала (422):

```json
{"status": "error", "detail": "Нельзя завершить приём до его начала"}
```

Осмотр с оценкой риска:

```bash
curl -X POST localhost:8000/patients/1/examinations -H "Content-Type: application/json" \
  -d '{"height": 172, "weight": 84, "ap_hi": 145, "ap_lo": 92, "cholesterol": 2, "gluc": 1}'
# {"id": 1, "patient_id": 1, ..., "risk_probability": 0.8226, "risk_level": "high"}
```

Поиск и пагинация: `GET /patients?search=Иванов&gender=M&sort_by=birth_date&order=desc&limit=20&offset=0`

```json
{"items": [{"id": 1, "full_name": "Иванов Иван Иванович", "...": "..."}], "total": 1, "limit": 20, "offset": 0}
```

Аналитика:

```bash
curl "localhost:8000/analytics/doctor-workload?date_from=2026-11-01"
curl "localhost:8000/analytics/risk-dynamics?period=month"      # day | month | year
curl "localhost:8000/analytics/top-diagnoses?limit=5"
curl "localhost:8000/analytics/risk-followup?limit=20"
```

## Интерфейс

- **`/clinic.html`**: список пациентов с поиском и пагинацией, создание и редактирование, удаление; запись на приём (ключевая бизнес-операция) с понятными сообщениями об ошибках;
  список приёмов с фильтром и кнопками «Отменить / Завершить / Неявка»; ввод медосмотра с оценкой риска; блок аналитики.
- **`/`**: ML-часть: форма оценки риска, пакетная оценка CSV, загрузка модели, график качества моделей.

Время в форме вводится в часовом поясе браузера, а часы работы проверяются в часовом поясе клиники (`CLINIC_TIMEZONE`),
поэтому для корректной работы они должны совпадать.

## Безопасность и ограничения

- **Аутентификации нет.** API и интерфейс открыты всем, кто достучится до сервера; в системе медицинские данные.
  Для учебного проекта это сознательное упрощение. Перед реальным использованием нужны авторизация и разграничение ролей.
- **Модель в репозитории.** `models/model.pkl` — обязательный по заданию артефакт и получен нашей же командой `python -m ml.train`
  (фиксированный `random_state`, данные лежат в `data/raw/`). Чужие pickle в репозиторий не добавляются.
- **Загрузка модели выполняет код.** Распаковка pickle запускает произвольный код из файла. Поэтому для любого сервера,
  доступного не только вам, задайте `MODEL_UPLOAD_TOKEN`: без верного заголовка `X-Upload-Token` загрузка вернёт 401.
  Если токен не задан, при старте в лог пишется предупреждение.
- **CORS открыт для всех источников** (`allow_origins=["*"]`), без передачи учётных данных.
- **Пароли PostgreSQL в `.env.example` и compose демонстрационные** (`clinic`); для реального развёртывания задайте свои.
- **Гонки при записи.** Строка врача блокируется на время записи, а двойную запись одного слота дополнительно не пускает
  индекс в БД. Пересечение приёмов одного пациента у двух разных врачей при одновременных запросах отдельно не блокируется.
- **Поиск и фильтры по датам.** `date_from` и `date_to` режут сутки по UTC, а не по часовому поясу клиники.

## Тесты и линтинг

```bash
ruff check . && ruff format --check .
pytest --cov=app --cov=ml --cov-report=term-missing --cov-report=html     # отчёт: htmlcov/index.html

cd frontend && npm ci && npm run lint && npm test
```

- **154 теста pytest**, покрытие ~97% (порог в CI — 90%, задание требует не меньше 70%).
- Интеграционные тесты идут через `TestClient`; для каждого теста создаётся своя БД SQLite в памяти, поэтому откат между тестами не нужен.
  Время подменяется управляемыми часами.
- Unit-тесты сервисов (`test_clinic_services.py`), ограничений БД, ETL-очистки (`test_etl.py`), миграций (`test_migrations.py`).
- Тесты фронтенда: 26 тестов на `node:test`.

> **Ограничение тестовой БД.** SQLite сравнивает регистр без учёта кириллицы, поэтому поиск пациентов по ФИО
> без учёта регистра проверяется только на латинице и совпадающем регистре. В PostgreSQL `ILIKE` работает для любых букв.

## CI

`.github/workflows/ci.yml` запускается при каждом push и pull request.

| Задание | Что делает |
|---|---|
| `backend` | `ruff check`, `ruff format --check`, pytest с покрытием (порог 90%), отчёт `coverage.xml` как артефакт |
| `migrations` | на настоящем PostgreSQL: `upgrade → downgrade → upgrade`, `alembic check`, seed, ETL дважды |
| `frontend` | `npm ci`, ESLint + Prettier, `node:test` |
| `docker` | сборка образа |

Слияние в `main` при красном CI запрещается настройкой branch protection в репозитории (Settings → Branches).
Для лабораторной №10 сохранён и `.sourcecraft/ci.yaml`.

## Структура

```
├── app/
│   ├── api/            # роутеры: patients, doctors, appointments, analytics, routes (ML)
│   ├── core/           # настройки, БД, ошибки, часы, логирование
│   ├── models/         # SQLAlchemy-модели
│   ├── schemas/        # Pydantic-схемы (Create / Update / Read)
│   ├── services/       # бизнес-логика
│   ├── etl/            # импорт данных из CSV
│   ├── seed.py         # демонстрационные данные
│   └── main.py
├── ml/                 # обучение модели
├── migrations/         # Alembic
├── frontend/public/    # clinic.html, index.html, js/, css/
├── tests/  docs/  data/raw/  models/  reports/
├── Dockerfile, docker-compose.yml, alembic.ini
└── PROMPTS.md          # промпты, по которым сгенерирован код
```

## Команда

| Участник | Роли | Зона ответственности |
|---|---|---|
| Павел Битковский | Backend / база данных, ML / данные, Frontend / DevOps | весь проект: `app/`, `migrations/`, `ml/`, `frontend/`, `tests/`, Docker, CI |
