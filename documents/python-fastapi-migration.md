# Переход MetricHit OS на Python/FastAPI

## Граница этапа

Первый этап создаёт только read-only слой над существующими SQLite-базами. Он не меняет схемы, данные, timestamps или journal settings и не запускает фоновый сервер.

Сохраняются без изменений:

- обе SQLite-схемы и файлы баз;
- каталог `work/` и редакционные материалы;
- утверждённая память и формат `current-context.md`;
- Node.js-ядро и его 38 тестов как эталон совместимости.

Переносятся на Python:

- безопасное разрешение путей внутри репозитория;
- read-only проверки памяти и редакционной базы;
- агрегированные статусы памяти и редакционного контура;
- чтение утверждённого текущего контекста;
- локальный FastAPI HTTP-интерфейс и CLI.

Временно остаются на Node.js:

- миграции и штатные идемпотентные workflow записи памяти;
- экспорт `current-context.md`;
- backup-инструменты;
- compatibility snapshot для автоматической проверки паритета.

## Локальный запуск

Все команды выполняются только проектным интерпретатором:

```powershell
.venv\Scripts\python.exe -m metrichit_os check-memory
.venv\Scripts\python.exe -m metrichit_os check-editorial
.venv\Scripts\python.exe -m metrichit_os memory-summary
.venv\Scripts\python.exe -m metrichit_os editorial-status
.venv\Scripts\python.exe -m metrichit_os context
.venv\Scripts\python.exe -m uvicorn metrichit_os.api:app --host 127.0.0.1 --port 8000
```

API предоставляет только `GET`:

- `/health`;
- `/api/v1/context`;
- `/api/v1/memory/summary`;
- `/api/v1/editorial/status`.

Удаление Node.js-ядра не входит в этот этап.

## Этап 2: редакционное write-core

Второй этап добавляет только локальный сервисный слой редакционного workflow. Он не добавляет FastAPI write-endpoints, сетевые адаптеры, ИИ-вызовы или фактическую публикацию.

Записывающие операции разрешены только для явно указанной базы, отличной от `data/editorial/editorial.sqlite`. Рабочая база блокируется в сервисном слое и CLI. Тесты создают базы в своих временных каталогах.

### Pending-миграция 002

Схема `001` не хранит этап workflow и результат idempotent operation, а также не запрещает изменение material versions. Поэтому контракт write-core оформлен в `data/editorial/pending-migrations/002_editorial_workflow_core.sql`.

Миграция применяется только функцией `initialize_workflow_database()` к новой явно указанной тестовой базе. Она намеренно не находится в каноническом каталоге `data/editorial/migrations/`: рабочая база остаётся на проверенной схеме `001`, а штатный Node.js checker не требует применения неразрешённой миграции. Перенос `002` в рабочий migration set потребует отдельного решения владельца.

`002` добавляет:

- этап `workflow_stage` для run;
- fingerprint и сохранённый результат idempotency key;
- platform/schedule binding для publish approval;
- ограничения переходов этапов;
- запрет UPDATE/DELETE material versions;
- защиту scope и текущей версии approvals;
- запрет publication job без точного действующего publish approval.

### Состояния

Разрешённые переходы:

```text
research -> planning | terminal
planning -> writing | terminal
writing -> review | terminal
review -> writing | approval | terminal
approval -> writing | publishing | terminal
publishing -> measurement | terminal
measurement -> terminal
```

В текущем этапе выполнение останавливается на `publishing` после создания локального `publication_job` со статусом `scheduled`. Сетевого вызова и перехода в `published` нет. `no_publish` завершает run в `terminal` как штатный исход.

Активные этапы используют статус `running`; `needs_owner` приостанавливает run на последнем корректном этапе. Терминальный этап допускает только `completed`, `failed`, `no_publish` или `cancelled` и требует `finished_at`.

Plan, content и publish approvals — отдельные записи с разными scope. Publish approval дополнительно связан с точными version hash, platform, target, scheduled time и expiry.

### Write CLI

Каждая write-команда требует `--db`. Данные передаются как JSON через `--data`, ответ также является JSON:

```powershell
.venv\Scripts\python.exe -m metrichit_os init-editorial-db --db tmp\editorial-test.sqlite
.venv\Scripts\python.exe -m metrichit_os create-run --db tmp\editorial-test.sqlite --data '{...}'
.venv\Scripts\python.exe -m metrichit_os add-research-source --db tmp\editorial-test.sqlite --data '{...}'
.venv\Scripts\python.exe -m metrichit_os add-research-item --db tmp\editorial-test.sqlite --data '{...}'
.venv\Scripts\python.exe -m metrichit_os create-topic --db tmp\editorial-test.sqlite --data '{...}'
.venv\Scripts\python.exe -m metrichit_os create-plan --db tmp\editorial-test.sqlite --data '{...}'
.venv\Scripts\python.exe -m metrichit_os create-material --db tmp\editorial-test.sqlite --data '{...}'
.venv\Scripts\python.exe -m metrichit_os add-material-version --db tmp\editorial-test.sqlite --data '{...}'
.venv\Scripts\python.exe -m metrichit_os request-approval --db tmp\editorial-test.sqlite --data '{...}'
.venv\Scripts\python.exe -m metrichit_os record-decision --db tmp\editorial-test.sqlite --data '{...}'
.venv\Scripts\python.exe -m metrichit_os prepare-publication-job --db tmp\editorial-test.sqlite --data '{...}'
.venv\Scripts\python.exe -m metrichit_os no-publish --db tmp\editorial-test.sqlite --data '{...}'
.venv\Scripts\python.exe -m metrichit_os show-run --db tmp\editorial-test.sqlite --run-id <uuid>
.venv\Scripts\python.exe -m metrichit_os next-actions --db tmp\editorial-test.sqlite --run-id <uuid>
.venv\Scripts\python.exe -m metrichit_os audit-trail --db tmp\editorial-test.sqlite --run-id <uuid>
```

Повтор с тем же idempotency key и тем же payload возвращает сохранённый результат. Тот же ключ с другим payload отклоняется. Ошибка внутри операции откатывает бизнес-запись, audit и idempotency key одной транзакцией.
