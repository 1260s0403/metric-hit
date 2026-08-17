# Серверный рабочий процесс MetricHit

## Рабочая среда

Сервер и `C:\MetricHit\workspace` являются основной рабочей средой и основной версией материалов MetricHit. Новые файлы сначала помещают в `work/inbox/`, затем разбирают по контурам. Оригиналы не перезаписывают; файлы называют понятно, при необходимости добавляя дату.

Лендинг, статьи и SMM ведутся раздельно. Черновики и подтверждённо опубликованные материалы хранятся отдельно. В `work/` нельзя помещать клиентские данные, секреты или токены. `mtrhit.ru` не подключают. Внешние публикации выполняются только после подтверждения владельца.

## Новый Strategy-чат и память

В начале нового Strategy-чата откройте `AGENTS.md` и `knowledge/approved/current-context.md`, затем проверьте `work/inbox/`. Для read-only проверки памяти используйте:

```powershell
node scripts/check-memory.mjs
node scripts/memory-cli.mjs summary
node scripts/memory-cli.mjs pending
node scripts/memory-cli.mjs conflicts
```

После важного решения предложите владельцу внести его в память. После завершения этапа обновите рабочий статус и предложите резервное копирование.

Executor небольшой изолированной owner-approved правки использует fast path из `AGENTS.md`: проверяет Git и читает только относящиеся к scope файлы, контракты и память. Полный Strategy-контекст, repo-side handoff и дополнительная задача для такого исполнения повторно не создаются.

## Резервное копирование и восстановление

Создать локальный атомарный backup-набор (workspace ZIP, полный Git bundle и
manifest с SHA-256):

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\backup-metrichit.ps1
```

Проверить восстановление последней копии:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\test-restore-metrichit.ps1
```

Набор должен восстанавливать одновременно SQLite, весь `work/` и Git-историю.
Состав, ручное восстановление, исключения и внешнее копирование описаны в
`documents/backup-and-restore.md`.

Для продолжения предыдущего чата Codex используйте сохранённый идентификатор сессии:

```powershell
codex.cmd resume <session-id>
```

Не вводите в командную строку и не сохраняйте в репозитории токены или API-ключи.
