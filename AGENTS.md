# «Ядро» — компактный обязательный контракт

`AGENTS.md` содержит только неизменяемые границы. Процедуры и карта проверок — [documents/operating-context.md](documents/operating-context.md), inheritance/context pack/execution card — [documents/structured-memory.md](documents/structured-memory.md), актуальный статус — [documents/roadmap.md](documents/roadmap.md). Нижний scope не ослабляет запреты «Ядра»; approved memory выше предположений.

## Роли, scope и рабочая копия

- Strategy — единственный постоянный видимый read-only human-facing router. Он не меняет repository и передаёт утверждённую mutation-задачу одному named executor. Один change set имеет одного writer, один commit и чистый Git.
- Задача формулируется от результата: один проверяемый Result, точный scope/resources, proof или acceptance и forbidden changes. Если evidence недостаточен, следующий шаг ограничивается получением именно недостающего evidence.
- Работать только в объявленном векторе: один проверяемый Result, точные files/resources и parent-chain память. Sibling/unrelated scope не читается и не меняется без прямой зависимости. Не исправлять попутные проблемы: сообщить observation/blocker.
- Canonical workspace — `C:\MetricHit\workspace`. Writer работает только в чистом, зарегистрированном noncanonical worktree того же репозитория внутри `C:\MetricHit\worktrees`, после проверки registration, branch, HEAD, clean state и отсутствия конфликтующего lease. Никаких самостоятельных клонов, fallback к canonical или глобальных настроек.
- По умолчанию один writer/agent. Subagent или controlled parallel execution допускается только когда работа объективно выигрывает от независимости: разные worktree/branch, непересекающиеся path, SQLite и shared resources, полный handoff; максимум четыре writer-а и только последовательная integration. Core/policy/config/migration/dependency/shared runtime, central DB, memory/context-pack и integration не параллелятся.

## Запуск и продолжение

- Только точные bare-команды `Ядро старт` и `Ядро старт.` запускают полный read-only Strategy audit. Они не создают executor, mutation, restart runtime, user/sidebar-задачи или фоновые процессы.
- Обычное продолжение читает только применимый scope. Новый рабочий чат запускается scoped-командой из `copy_command`; до status executor выполняет `chat-workspace-prepare` или `chat-parallel-start` и проверяет изоляцию. После `Заверши задачу.` сначала поставляется текущий Result, затем `chat-finish` сохраняет clean checkpoint и выдаёт ровно одну scoped startup-команду в отдельном fenced `text` block. Новый чат создаёт владелец.
- Не выводить целиком и не перечитывать крупные документы без причины. Повторное чтение нужно лишь при смене scope, изменении правила или конкретном пробеле. Context pack содержит только parent chain, применимые rules и необходимые файлы.
- Обычный вопрос или узкая проверка использует минимально достаточные документы и tool calls; дополнительный поиск, чтение или действие допустимы только для недостающего evidence. Web/browser, deep research и image generation применяются, только когда они нужны объявленному Result, а не для рутины.
- Usage review выполняется только по прямому обращению владельца, read-only и с понятным отчётом: общая история расхода, наиболее затратные чаты/модели и практические действия. Scheduler, daemon, monitoring, UI, API, dependencies и скрытые процессы этим не создаются.

## Разрешения и обязательные gates

- Прямое in-scope `сделай`, `реализуй`, `доделай`, `исправь` или `делай сам` является постоянным разрешением на in-scope реализацию, проверки, обычный `git add`, один commit и последовательную integration. Executor сам ведёт внутренний handoff/lease и не просит вторую lifecycle-команду. `Заверши задачу.` означает подготовиться к переходу через CLI `chat-finish`.
- Отдельное прямое решение владельца требуется для удаления, force-операций, внешней публикации, расходов, access/permission changes, стратегии, политики памяти, глобальных/system settings и существенного расширения scope. Публичные URL — read-only, кроме явно разрешённых в operating context исключений; секреты не хранятся в repository. Не изменять Windows, RDP, Defender или KMSAutoNet.
- Память меняется только штатным идемпотентным workflow без semantic-дублей. Обычная правка не синхронизирует memory/current-context/roadmap; прямое решение владельца или значимое approved policy change синхронизируется тем же executor.

## Card, delivery и проверки

- Перед любой mutation compiler `scripts/structured-memory.mjs` создаёт полную execution card: Result, exact scope, mandatory rules, одну существующую first check, измеримые acceptance и forbidden changes. До mutation — `node scripts/delivery-preflight.mjs` и чистый активный worktree.
- Delivery требует validation по той же card, одного commit и последовательной integration. `chat-finish` не является delivery. Без validation — только точный blocker.
- Проверки пропорциональны изменению: docs-only — `git diff --check`; governance/memory — `node --test tests/decision-governance-policy.test.mjs`, затем `node scripts/check-memory.mjs`; остальное — карта в operating context. Стандартное изменение проверяет только затронутый модуль. Не запускать широкую regression, reinstall, restart или смену owner-facing порта без прямого риска или доказанной зависимости.

## Выбор модели

- Terra Medium — рекомендуемая модель для обычных Strategy и standard executor-задач. Luna/low — только полностью определённая mechanical low-risk задача с простой целевой проверкой; при её недоступности применяется Terra Medium без blocker. High/xhigh допустимы только при доказанной сложности. Sol обязательна для architecture, security/auth, schema/data integrity, shared runtime или существенной неоднозначности; при её недоступности — технический blocker. Astra — только по отдельному решению владельца.
- Модель не меняет owner-gates, один writer или необходимые проверки. Нет автоматической цепочки моделей и обязательного Luna review.

## Редакция и оркестрация

- Детальные editorial rules, publication gate, SEO/visual QA и source-overlap находятся в scoped memory и `documents/structured-memory.md`; они обязательны для относящейся card. Публикация, проверка индексации и запуск ПФ сохраняют отдельные owner-gates.
- Read-only pilot сохраняет 2–3 независимые research/audit ветки с synthesis Strategy. Orchestration v1 ограничена compiler-generated цепочкой и штатным handoff lifecycle. Первый профиль — `MetricHit → Редакция`; coordinator read-only, worker не делегирует. Platform approval запрашивает Strategy в текущем чате с владельцем. UI, daemon, scheduler, API и автономная production-редакция не разрешаются.
