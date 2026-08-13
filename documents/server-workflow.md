# Серверный рабочий процесс MetricHit

## Рабочая среда

Сервер и `C:\MetricHit\workspace` являются основной рабочей средой и основной версией материалов MetricHit. Новые файлы сначала помещают в `work/inbox/`, затем разбирают по контурам. Оригиналы не перезаписывают; файлы называют понятно, при необходимости добавляя дату.

Лендинг, статьи и SMM ведутся раздельно. Черновики и подтверждённо опубликованные материалы хранятся отдельно. В `work/` нельзя помещать клиентские данные, секреты или токены. `mtrhit.ru` не подключают. Внешние публикации выполняются только после подтверждения владельца.

## Новый чат Codex и память

В начале нового чата откройте `AGENTS.md` и `knowledge/approved/current-context.md`, затем проверьте `work/inbox/`. Для read-only проверки памяти используйте:

```powershell
node scripts/check-memory.mjs
node scripts/memory-cli.mjs summary
node scripts/memory-cli.mjs pending
node scripts/memory-cli.mjs conflicts
```

После важного решения предложите владельцу внести его в память. После завершения этапа обновите рабочий статус и предложите резервное копирование.

## Резервное копирование и восстановление

Создать локальную резервную копию:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\backup-metrichit.ps1
```

Проверить восстановление последней копии:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\test-restore-metrichit.ps1
```

Для продолжения предыдущего чата Codex используйте сохранённый идентификатор сессии:

```powershell
codex.cmd resume <session-id>
```

Не вводите в командную строку и не сохраняйте в репозитории токены или API-ключи.
