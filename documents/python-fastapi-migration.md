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
