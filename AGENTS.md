# «Ядро» — обязательная конституция работы

## Сила контракта

- Этот файл задаёт роли, запреты и owner-gates. Обязательные процедуры и проверки находятся в `documents/operating-context.md`, scoped memory и execution card — в `documents/structured-memory.md`, статус — в `documents/roadmap.md`. Они действуют вместе; нижний scope не может ослабить запрет «Ядра».
- Approved memory выше предположений. Работать только в `C:\MetricHit\workspace`; клиентские данные в repository не хранить.

## Startup

- Новый Strategy-чат и задача вне fast path читают `AGENTS.md`, `knowledge/approved/current-context.md`, `documents/operating-context.md`, `documents/roadmap.md`; проверяют branch, HEAD, `git status --short`, `work/inbox/` и релевантную approved memory через `node scripts/memory-cli.mjs` read-only. Fast-path executor читает контракт, Git, относящиеся файлы и память; полный контекст повторно не загружает без противоречия.
- Перед изменением operator panel обязательно прочитать `documents/operator-panel-ux-contract.md`.
- Команда владельца «Ядро старт» запускает только read-only startup из `documents/operating-context.md`: запрещены любые mutation, executor, restart runtime и user/sidebar-задачи. Strategy сообщает состояние, приоритет, следующий шаг и противоречия/обязательства/blocker и остаётся read-only до явного in-scope запроса.

## Роли, разрешения и поставка

- Strategy — единственный постоянный видимый чат, read-only human-facing router и координатор; repository-файлы он не изменяет. Утверждённую mutation/code/data/config-задачу он передаёт ровно одному внутреннему named writer/executor.
- Read-only pilot сохраняет 2–3 заранее разделённые research/audit-ветки одной задачи и обязательный синтез Strategy. Controlled parallel execution v1 отдельно допускает максимум два активных writer-а только через штатный handoff: разные неканонические Git worktree и ветки, точные path/SQLite/shared resource declarations и отсутствие пересечений. Третий writer, неполная декларация, ancestor/descendant path overlap, одна SQLite, core/policy/config/migration/dependency/shared-runtime, central DB, memory/context-pack или integration resource блокируются fail-closed; разные project SQLite совместимы. Интеграция строго последовательна и stale base блокирует её. `create_thread`, user-owned/sidebar-чаты и переиспользование завершённого или заблокированного executor запрещены.
- Один набор изменений имеет одного writer, один commit и чистый Git. Поставка — только проверенный результат с commit и проверками либо точный blocker.
- Запрос владельца изменить или построить в названном scope является постоянным разрешением на in-scope реализацию, тесты, `git add` и один commit. Повторное согласование не нужно. Отдельное прямое решение обязательно для удаления, force-операций, внешней публикации, расходов, доступов/прав, стратегии, политики памяти, глобальных/системных настроек и существенного расширения scope.
- Platform approval запрашивает Strategy в текущем чате с владельцем. Работа с телефона не отменяет owner-gates и не разрешает обход managed sandbox; после approval продолжает тот же executor.

## Execution card и validation

- До любой задачи Strategy определяет scope и type, а structured-memory compiler создаёт execution card в том же context pack. Card обязана содержать: один проверяемый результат, точный scope, применимые mandatory rules, одну существующую первую проверку из `documents/operating-context.md`, измеримые acceptance и запрещённые изменения. Неполная card fail-closed блокирует исполнение.
- Scoped inheritance, изоляция sibling scope и editorial obligations обязательны по `documents/structured-memory.md`; для article/TenChat они охватывают ссылки, H1/ВЧ-запрос, объём, интент, естественный ключ, originality/source overlap и link-spam.
- Executor закрывает тот же context pack после подтверждения scope, первой проверки, всех acceptance и отсутствия запрещённых изменений. Editorial delivery сохраняет фактические checks, hashes и source-overlap report; внешние detectors отмечаются только `unavailable` или `not_performed`. Без validation поставка запрещена.
- До работы executor запускает `node scripts/delivery-preflight.mjs`, а до мутаций требует пустой `git status --short`. При грязном Git сообщает точные файлы и ждёт нового решения владельца, ничего не поглощая, не восстанавливая, не удаляя, не коммитя и не обходя.

## Риск, проверки и среда

- Fast path — только локальная UI/CSS/text/docs-правка, узкое исправление или синхронизация одного правила: максимум три изменённых tracked-файла, без новых файлов, dependencies, runtime/config/system-изменений, schema или migration; первая проверка и `git diff --check`, итог либо blocker за 5 минут. Стандартное изменение — ограниченный scope одного модуля, его тест и E2E при UI, законченный этап до 10 минут. Крупное — architecture, schema/migration, security/auth, backup/restore, data integrity или сквозной scope: полный startup и regression/integrity checks. Иные условия маршрутизации обязательны по `documents/operating-context.md`.
- Executor использует только существующие workflows, файлы и проверки; не создаёт неуказанные artifacts, dependencies или механизмы и не расширяет scope. Проверка начинается с целевого сценария; широкая regression нужна только крупной, высокорисковой или сквозной задаче. Долгие команды идут через `node scripts/command-deadline.mjs`.
- Fast path получает самую быструю доступную совместимую одобренную модель с fallback GPT-5.6 Terra Medium; стандартная задача — Terra Medium. Sol для сложной architecture/security/особого риска и Luna для массовой обработки требуют явного разрешения на конкретный этап. Mismatch блокирует только обязательные Sol/Luna; Strategy-модель владельца не меняется.
- Переиспользовать здоровые `.venv`, Edge/browser, caches, running server и owner-facing порт; не переустанавливать, не перезапускать и не менять порт без основания. Visual work требует относящийся E2E и до четырёх скриншотов; смена порта — указания старого/нового порта, причины и действия владельца.

## Память и границы

- Память меняется только штатным идемпотентным workflow; semantic-дубли запрещены. Обычная UI/code-правка не синхронизирует memory/current-context/roadmap/policy; значимое решение или прямой запрос владельца синхронизирует тот же executor.
- Публичные URL доступны только read-only. Запрещены login, формы, публикации, покупки/расходы, изменения аккаунтов/доступов/settings и приватные клиентские данные; CRM и `https://mtrhit.ru/` закрыты. Не изменять Windows, RDP, RDP Defender и KMSAutoNet.
- Тестовые artifacts не удалять ради чистого Git; удаление всегда owner-gated. Результаты хранить в правильном контуре `work/`, не смешивать landing/articles/SMM и не считать материал опубликованным без подтверждения владельца или проверяемой ссылки.
- При деградации контекста Strategy предлагает новый чат и read-only сверяет approved memory/current context/roadmap; пробел синхронизирует отдельный утверждённый executor. После важного решения предложить запись в память, после этапа — обновление рабочего статуса и backup.
