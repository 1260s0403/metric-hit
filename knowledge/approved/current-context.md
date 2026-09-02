# MetricHit — текущий рабочий контекст

Сформировано: 2026-09-02T11:15:42.458Z. Этот файл содержит только утверждённую память. Задачи и планы вынесены в отдельный раздел и не являются реализованными фактами.

## Основные факты о продукте

- **Полное не-навигационное семантическое ядро MetricHit:** В проекте MetricHit утверждено полное рабочее семантическое ядро из 145 не-навигационных запросов: основной коммерческий спрос, цена и бюджет, выбор и сравнение, обучение и диагностика, риски, проблемы позиций, запуск и управление, сегменты и геокандидаты. Геокандидаты применяются только после проверки спроса. Брендовые и навигационные варианты MetricHit, Metric Hit, «Метрик Хит» и mtrhit исключены.
- **SERVER как целевое primary workspace MetricHit:** Фактический серверный контекст: hostname SERVER; Windows Server 2025 Standard 64-bit, 10.0.26100; RAM 127.9 GB; C: 2047.9 GB всего и 2019.2 GB свободно; IPv4 65.109.62.241; Git 2.55.0.windows.3; Python 3.13.14.
- **Управленческое и коммерческое назначение «Ядра»:** «Ядро» помогает владельцу понимать, что происходит в бизнесе, почему это происходит, что приносит результат и какое решение сейчас важнее. Система связывает фактические данные с целями, решениями, независимыми проектами, задачами и результатами. Направления развития: измеримые результаты, реестр решений, гипотезы и эксперименты, центр решений владельца, простая экономика проектов и отделов, ежедневные и недельные сводки, объяснимое состояние работы и повторно используемые шаблоны запуска. Это направления развития, а не уже реализованные функции. Сложный Гант, корпоративный чат, видеосвязь, тяжёлый календарь и замена CRM не являются текущим приоритетом.
- **Назначение MetricHit:** MetricHit — сервис накрутки и улучшения поведенческих факторов (ПФ) для продвижения сайтов в поисковой выдаче Яндекса. Пользователь настраивает сайт, регион, поисковые запросы, дневные лимиты и расписание, а затем контролирует выполненные клики, расходы и изменение позиций в личном кабинете. MetricHit используется как инструмент усиления подготовленного сайта и не является гарантией роста позиций или заменой технического SEO, релевантности страниц и коммерческой проработки.
- **Настройка проекта MetricHit:** Пользователь создаёт проект, задаёт сайт, регион, запросы, дневные лимиты и расписание; клики, расходы и позиции контролируются в личном кабинете.
- **Канонический ответ о механике кликов MetricHit:** Механика такая:
Бот работает с поисковой выдачей: по запросу сначала открывает несколько других результатов (не задерживается на них), ваш сайт — последним, после чего в поиск не возвращается.
Для Яндекса это выглядит как завершённый успешный поиск.
Это не просто одиночный клик.
Действий внутри сайта бот не совершает.
Внутренние поведенческие факторы Яндекс не учитывает.

## Коммерческие условия

- **Модель оплаты MetricHit:** Используется предоплата и тарификация по фактически выполненным кликам без фиксированной абонентской платы; неиспользованный остаток не сгорает.
- **Бонус новому пользователю:** Новый пользователь может один раз получить 1 000 тестовых кликов после регистрации и обращения в Telegram-поддержку с логином; начисление не автоматическое и не требует пополнения.
- **Действующая тарифная сетка:** Цена клика зависит от суммы пополнения: от 1 000 ₽ — 0,50 ₽; от 10 000 ₽ — 0,40 ₽; от 50 000 ₽ — 0,30 ₽; от 100 000 ₽ — 0,25 ₽; от 150 000 ₽ — 0,20 ₽; от 200 000 ₽ — 0,15 ₽.

## Официальные ресурсы и каналы

- **Официальный Telegram-канал MetricHit:** Официальный публичный Telegram-канал MetricHit: https://t.me/mtr_hit.
- **Telegram-поддержка MetricHit:** Официальный контакт Telegram-поддержки MetricHit: https://t.me/Metric_Hit.
- **Регистрация и личный кабинет MetricHit:** Регистрация и личный кабинет MetricHit расположены по адресу https://mtrhit.ru/.
- **Официальный лендинг MetricHit:** Официальный лендинг MetricHit расположен по адресу https://go.mtrhit.ru/.

## Действующие решения

- **Политика выбора модели Codex:** Стандартные задачи выполняются внутренним executor на GPT-5.6 Terra, reasoning Medium. Fast-path задачи автоматически используют самую быструю доступную совместимую одобренную модель без отдельного вопроса владельцу; если она недоступна, executor без blocker использует Terra Medium. Маршрутизация применяется только к внутреннему executor там, где платформа позволяет выбрать модель, и не меняет owner-visible Strategy-модель. Быстрая модель не используется для архитектуры, SQLite-схем, бизнес-логики, авторизации, security, backup/restore, миграций и больших сквозных модулей. Для сложной архитектуры, security и особо ответственных задач требуется GPT-5.6 Sol; для массовой однотипной обработки — GPT-5.6 Luna. Sol и Luna используются только после подтверждения владельца; разрешение действует только для конкретной задачи либо явно непрерывного этапа и не переносится автоматически. Task-thread сверяет фактическую модель с требуемой; mismatch блокирует критические действия только для обязательных Sol/Luna. После подтверждённого переключения thread продолжает с текущего состояния без отката, нового thread или перезапуска.
- **Целевой backend «Ядра»: Python/FastAPI:** Целевой backend «Ядра» — Python 3.13 и FastAPI. Новая функциональность Node.js заморожена, а существующее Node.js-ядро остаётся эталоном совместимости. SQLite сохраняется для MVP. Удаление Node.js-ядра возможно только после функционального паритета, прохождения полного набора тестов и отдельного решения владельца. Python-зависимости устанавливаются только в проектное окружение .venv, без глобальной установки.
- **Политика контура решений MetricHit OS:** Контур решений относится к центральному ядру, а не к отделу или автономному агенту. Явно утверждённые владельцем решения могут сохраняться как approved; предложения, выводы и непринятые варианты остаются pending candidates, а потенциальные решения никогда не auto-approve. Перед сохранением проверяются semantic duplicate, evolution и conflicts. Решения могут связываться с проектом, задачей, источником и при необходимости Git-коммитом. В current context включаются только значимые approved-решения; технические мелкие правки решениями не считаются. Контур охватывает архитектуру, продукт, приоритеты, правила, бюджеты, сроки, права, ограничения и направления проектов. Канонический workflow engineering: Strategy → internal native Codex task-thread/subagent → commit/result. Strategy — единственный постоянный видимый проектный чат и read-only поток: он обсуждает и анализирует, читает approved memory, Git и документы. Только после явного утверждения владельцем конкретного изменения репозитория Strategy создаёт ровно одну внутреннюю native engineering-задачу/subagent; он никогда не создаёт user-owned/sidebar-чат и не использует create_thread. Planning, analysis, context reads, неутверждённые предложения и pending candidates не создают engineering-задачу. Strategy не изменяет файлы репозитория — включая memory, docs, config, code и tests — независимо от размера изменения; их изменяет только отдельный native task-thread. Постоянный developer-чат не требуется. Repo-side handoff хранит решение, контекст задачи и известный итог/commit hash для audit; он не конкурирует с native task-thread как очередь исполнения. Существующие handoff-next, handoff-claim и handoff-complete и lifecycle ready → in_progress → completed остаются совместимым внутренним механизмом, но не обязательны для startup или пользовательского процесса. UI, daemon, scheduler, OpenAI API и интеграция внутреннего API Codex не реализуются. Будущий UI входит в управление кандидатами памяти и должен стать основой «Центра решений владельца». Управление native Codex task-thread строго изолирует задачи: одно пользовательское engineering-решение создаёт ровно один native task-thread. До создания Strategy проверяет, нет ли уже thread для текущего пользовательского turn/решения. Повторная обработка того же turn маршрутизируется идемпотентно: если thread уже есть, Strategy сообщает его ID и status и ничего не создаёт. Каждая новая engineering-задача создаёт новый native task-thread; Strategy никогда не заменяет scope существующего или завершённого task-thread. Controlled parallel execution v1 допускает максимум два активных writer thread только через resource-aware handoff: разные неканонические Git worktree и ветки, точные path/SQLite/shared declarations и отсутствие пересечений. Третий writer, ancestor/descendant path overlap, одна SQLite, core/policy/config/migration/dependency/shared-runtime, central control-plane, memory/context-pack или integration resource блокируются fail-closed. Разные project SQLite совместимы. Интеграция получает отдельный последовательный lease и блокируется при stale base. После commit/result и чистого git status thread закрыт для новых задач. Strategy — read-only human-facing router: он назначает одного named executor-а с точным scope и сообщает только проверенный результат с чистым Git либо точный технический blocker. Он не опирается на ненаблюдаемые промежуточные контроли платформы. Частичный результат не является поставкой; заблокированная задача не передаётся и не переназначается без нового прямого указания владельца. Контролируемый multi-agent research pilot сохраняет 2–3 независимые параллельные read-only research/audit-ветки одной задачи с обязательным synthesis Strategy. Отдельно controlled parallel execution v1 разрешает до двух независимых mutation/code/data/config-задач; внутри каждого набора изменений по-прежнему один named writer/executor, одна ветка, один commit и чистый Git. Для небольшой изолированной и явно утверждённой правки действует fast path: он ограничен максимум тремя изменёнными отслеживаемыми файлами и исключает новые файлы, зависимости, runtime/configuration/system-изменения, схему данных и миграции; превышение любого предела до реализации переводит задачу в стандартный этап. Strategy передаёт одному executor-у owner approval, точный scope/acceptance, branch/HEAD/status и релевантные ссылки. До мутаций executor проверяет git status --short: при любом выводе сообщает точные грязные файлы и ждёт нового прямого решения владельца, не поглощая, восстанавливая, удаляя, коммитя или обходя их. Executor использует только существующие workflow, файлы и проверки; новые скрипты, файлы, задачи, абстракции и вспомогательные контуры запрещены, пока прямо не названы в acceptance. Он не расширяет и не переосмысливает scope: новая проблема становится отдельной задачей после прямого решения владельца. Поставка — только проверенный результат с чистым Git либо точный технический blocker. Fast path не применяется к архитектуре, SQLite-схеме/миграциям, бизнес-логике, авторизации, security, backup/restore, целостности данных, многомодульному или неясному scope, затрагивающему scope dirty worktree и расхождениям HEAD/контекста. Действующие owner-gates сохраняются. Краткая постановка задачи состоит из четырёх пунктов: Result — один проверяемый итог; Scope — точные затрагиваемые области; First check — одна существующая быстрая целевая проверка затронутого модуля; Forbidden changes — что не менять. Если такая проверка неизвестна, задача стандартная и сначала в своём scope определяет нужную существующую проверку без широкой регрессии ради поиска. Формулировки «заодно» не расширяют scope. План, отчёт, скрипт, вспомогательный файл или иной механизм допустимы только когда прямо требуются владельцем; если существующий workflow не позволяет получить результат, executor сообщает точный blocker. Обычная UI- или кодовая правка не синхронизирует память, current context, roadmap или policy: это делается только по прямому запросу владельца либо для действительно значимого утверждённого решения. Проверка начинается с одного целевого сценария, а полная регрессия выполняется только для крупного, высокорискового или сквозного изменения. Отсутствие промежуточного сообщения не является критерием остановки: контроль ведётся по финальному сроку и фактическому состоянию рабочей копии; краткое обновление допустимо только при фактическом прогрессе или blocker. Утверждённые изменения маршрутизируются по реальному риску: малое (локальные UI/CSS/текстовые правки, документация, узкие исправления и синхронизация правила памяти) исполняется одним executor-ом на самой быстрой доступной совместимой одобренной модели с fallback на Terra Medium, целевыми тестами и git diff --check; стандартное использует Terra Medium в ограниченном scope одного модуля с точным acceptance, без повторного полного context, с тестами затронутого модуля и E2E при изменении UI; крупное (архитектура, SQLite schema/migrations, security/auth, backup/restore, data integrity или сквозной многомодульный scope) требует полного startup/context, применимого подтверждения special model по действующей policy и полной регрессии/integrity-проверок. Strategy не относит UI-текст, CSS или узкое исправление к архитектуре без фактического основания. Полная регрессия нужна только для крупного, высокорискового или сквозного изменения и не запускается автоматически после каждого малого изменения. Во всех режимах сохраняются single writer/executor, один commit, чистый Git и относящийся UI E2E. Managed sandbox является внешней границей платформы: репозиторий не может предоставить Full access, отключить approval или обойти запрет на создание .git/index.lock. При таком отказе executor сразу сообщает точную заблокированную операцию и внешний blocker, использует штатный platform approval flow, если он доступен, и после разрешения продолжает в том же thread без нового executor-а, циклов повторных попыток или неподтверждённого вывода о неисправности Git, БД либо сервера. Если platform approval необходим, Strategy запрашивает его в текущем чате владельца; работа владельца с телефона не ослабляет owner-gates и не означает обход managed sandbox. Запрос владельца изменить или построить в названном scope является standing authorization на in-scope реализацию, тесты, обычный git staging и один commit; Strategy не запрашивает повторное промежуточное подтверждение. Отдельное явное решение требуется только для удаления, force-операций, внешней публикации, расходов, изменений доступов/прав, стратегии, политики памяти, настроек/глобальной системы или существенного расширения scope. Managed-sandbox prompts отменить нельзя и они сообщаются только при возникновении. Strategy — основной human-language координатор продукта, архитектуры, приоритетов и разработки: до решений он читает approved memory, current context, operating context, roadmap и фактический Git, отмечает существенные пробелы и противоречия и предлагает ближайшие MVP-шаги. Он не требует повторять известный контекст и не считает историю чата канонической истиной. Если чат стал слишком длинным, регулярно требует сжатия, теряет важные детали, путает решения или заметно расходует контекст, Strategy сам предлагает новый чат. Перед переходом он read-only сверяет approved memory, current context и roadmap на полноту значимых утверждённых решений, планов, ограничений, незавершённых задач и ближайших следующих шагов. При пробеле отдельный native task-thread синхронизирует канонический контекст; после сверки Strategy подтверждает, что новый чат продолжит работу по startup protocol без старой истории. AGENTS.md является коротким обязательным startup-контрактом, а полный постоянный контекст хранится в operating-context и roadmap без ослабления safety gates. Первая проверка выбирается из явной карты существующих команд: docs-only — git diff --check; governance/memory — целевой Node test и check-memory; Python — один относящийся pytest-файл; operator panel backend — test_operator_panel.py; UI/E2E — test_operator_panel_e2e.py; JavaScript — node --check operator-panel.js. Широкая регрессия не используется для поиска проверки. Executor переиспользует здоровые project .venv, system Edge/browser, dependency caches, running server и owner-facing port; без доказанной проблемы не переустанавливает зависимости, не перезапускает runtime и не меняет порт. Отсутствующее или сломанное окружение является точным blocker либо отдельной утверждённой environment-задачей. Структурированная память реализована как наследуемая цепочка Ядро → проект → подпроект → задача. AGENTS.md остаётся короткой конституцией Strategy, а изменяемые знания хранятся вне него. Strategy сначала определяет scope и тип задачи, читает паспорта выбранного scope и только релевантные блоки родительской цепочки; память sibling-проектов и подпроектов не загружается. Каждый scope имеет компактный паспорт. Правила наследуются сверху вниз, причём запреты Ядра нельзя отменить ниже. Память делится на постоянную, рабочую и историческую; история читается только по основанию. Активные записи имеют явные ownership, layer, type, status, source, valid_from и supersedes, а неоднозначные записи направляются в fail-closed очередь. Для исполнителя Strategy формирует временный минимальный task context pack и сохраняет audit маршрута без текста команды и внутреннего reasoning. Общие знания хранятся один раз на ближайшем общем уровне. Детерминированный context compiler собирает минимальный пакет; P0–P5 прошли acceptance на пилоте MetricHit «Редакция» и «Панель». Канонический контракт — documents/structured-memory.md, schema migration — v11, compiler — scripts/structured-memory.mjs. Orchestration v1 добавляет воспроизводимый временный coordinator между Strategy и одним writer-ом без постоянного отдела или нового сервиса. Первый active pilot profile — MetricHit → Редакция. Coordinator получает только compiler-generated цепочку Ядро → MetricHit → Редакция → задача, формирует одну дочернюю execution card, декларативно выбирает только установленные разрешённые skills и выполняет предметную приёмку. Максимальная глубина — Strategy → coordinator → worker; worker не делегирует. Lifecycle route → coordinator claim → child delegation → worker evidence → coordinator approve/reject → sequential integration → Strategy completion enforced fail-closed и сохраняется в handoff metadata без prompt/reasoning. До трёх read-only research/audit веток разрешены, writer внутри change set один, глобальный предел двух writer leases и все resource/stale-base правила сохраняются.
- **Независимые проектные контуры «Ядра»:** «Ядро» — OS и управляющий контур для нескольких независимых проектов. MetricHit — первый проект внутри «Ядра»; понятие «MetricHit OS» не используется для целевой модели. У каждого проекта должны быть собственные память, правила и бизнес-истина, независимые от «Ядра» и друг от друга. Ближайший приоритет до любой иной разработки — подготовить проектные контуры: отдельное физическое хранилище каждого проекта, безопасную миграцию существующих данных, экспорт/импорт самостоятельного проекта и изоляцию проектов в операторской панели. Реализация каждого направления начинается только после отдельного утверждения владельца; это решение не меняет схему, интерфейс или данные.
- **Техническое разделение независимых проектов завершено:** На commit acff1db909c9cf9b7b85f0c2a18b035f3d3fa2c0 завершена универсальная маршрутизация независимых проектов. Любой зарегистрированный managed project направляется по canonical project_id в собственный project.sqlite; центральная SQLite остаётся control plane. Некорректные, неизвестные, незарегистрированные проекты и проекты без хранилища отклоняются fail-closed. Federated/project store и memory routing работают для N проектов, совместимость MetricHit сохранена. Два временных проекта подтвердили взаимную изоляцию и export/import; реальный второй проект не создавался. Подтверждены Python 196 passed, 1 skipped; Node 63/63; integrity и foreign keys valid; readiness unresolved=0, ready=true. Разделение технически завершено. Следующий продуктовый шаг нужен только при появлении реального второго проекта или по отдельному решению о UI; cleanup legacy-копий требует отдельного решения владельца.
- **Прямая редакционная политика MetricHit:** MetricHit может прямо описывать накрутку и улучшение ПФ для продвижения сайтов в Яндексе. Прямая, включая жёсткую и категоричную, подача разрешена по умолчанию для Telegram, VK и Дзена, а для остальных площадок адаптируется под реальные требования и риск модерации. Неподтверждённые оценки, демонстрационные данные, категоричные тезисы и обсуждение антифрода не блокируются автоматически; решение о допустимости конкретной формулировки принимает владелец. Нельзя создавать заведомо ложное утверждение специально для намеренного введения потенциального клиента в заблуждение ради продажи. Предыдущие общие запреты на гарантии, неподтверждённые показатели и антифрод-детали заменены в противоречащей части.
- **Фокус публичных материалов MetricHit на поисковой выдаче:** В публичных статьях MetricHit не упоминать действия пользователей или ботов внутри сайта, внутренние поведенческие факторы, глубину просмотра, время, скроллы или клики и не вступать в спор об их влиянии. Материалы о сервисе фокусируются на поисковой выдаче, запросах, позициях, регионах, дневных лимитах, стоимости клика, бюджете и контроле результата.
- **Длинные статьи ведутся отдельно от SMM:** Полноформатные статьи вынесены в отдельный рабочий контур, чтобы разделить оперативный SMM и редакционную работу.
- **Редакционный контур MetricHit: завершённый фундамент и следующий research-MVP:** Внутри собственного project.sqlite MetricHit завершён редакционный контур: foundation (`39079d11`), разделение направлений articles/social (`edac95db`) и workflow материалов (`1336b461`). Текущая schema редакции — v6; в реестре есть один article-материал для Timeweb Cloud со статусом draft, а публикаций и результатов нет. Articles и social используют общую editorial-память, но получают изолированную выборку своего направления; производный social-материал связан с исходной статьёй без дублирования. Workflow: idea → plan → draft → review → published → result, с возвратом review → draft; published требует подтверждения владельца или проверяемого URL, result — подтверждённой публикации. Следующий, ещё не реализованный этап — on-demand research-MVP: реестр надёжных источников, датированные research-находки, дедупликация и оценка релевантности к семантическому ядру и editorial-реестру, краткий research-brief по запросу. Scheduled monitoring, автопубликация, UI редакции и маркетинговые skills не входят в этот этап и требуют отдельных решений владельца. Полный central backup успешно создан: `MetricHit-backup-20260831T082016Z`; штатный restore-test пройден. Имеются несвязанные UI E2E failures; они не относятся к editorial-поставкам.
- **Скорость MVP и масштабируемость редакционного контура:** «Ядро» развивается короткими сквозными MVP-этапами. Первый рабочий редакционный контур создаёт одну статью для одной выбранной площадки и производные посты Telegram/VK, после чего останавливается на согласовании. Конечная система должна поддерживать несколько статейных площадок и аккаунтов, но масштабирование добавляется после проверки первого контура. Провайдеры моделей и площадки подключаются через узкие сменные адаптеры без изменения редакционного ядра. Преждевременная универсализация запрещена.
- **Текущее состояние editorial-реестра MetricHit:** Историческая запись о пустых реестрах редакции больше не описывает текущее состояние: зарегистрирован один article-материал для Timeweb Cloud со статусом draft. Публикаций и результатов в реестре нет; внешний URL отсутствует.
- **Принцип MVP и скорости разработки:** Скорость разработки критична. Для каждой задачи реализуется минимальный законченный пользовательский сценарий. Нельзя добавлять функции и абстракции «на будущее»; сложность допустима только при доказанной необходимости. Большие задачи по возможности делятся на законченные вертикальные этапы примерно по 20–30 минут, но не так, чтобы система оставалась небезопасной, полурабочей или неконсистентной. Нельзя экономить на целостности данных, security, idempotency, критических тестах и восстановимости. Недоделанное не считается MVP.
- **Prepare the SERVER Python environment for development and tests:** Цель: Prepare the SERVER Python environment for development and tests

Scope:
- Prepare or restore the project .venv on Python 3.13 in the workspace.
- Install only dependencies from the existing requirements.lock and pyproject conventions required for FastAPI, pytest, and Playwright.
- Configure existing panel tests to use the system Microsoft Edge without changing product functionality.
- Verify FastAPI import, pytest startup, focused Python tests, and at least one existing panel E2E test on system Edge.

Ограничения:
- Do not change project functionality.
- Do not add dependencies beyond those needed for this environment.
- Do not change Windows or install a new Edge if system Edge is already available; use the existing system Edge.
- If tracked config or requirements must change, do so only if necessary and make one commit; otherwise do not change tracked files or create a commit.

Acceptance:
- .venv runs FastAPI, pytest, and Playwright for the project.
- FastAPI import succeeds.
- Focused Python tests pass.
- At least one current panel E2E test passes on system Microsoft Edge.
- git status --short is clean if tracked files did not change.

Источник решения: Direct owner approval in Strategy chat on 2026-08-16.
- **SERVER назначен primary workspace MetricHit:** Миграция проекта «Ядро» на SERVER завершена. C:\MetricHit\workspace является canonical primary workspace MetricHit. Домашний ПК сохраняется как резервная точка и не считается primary workspace.
- **Разделять лендинг и личный кабинет:** go.mtrhit.ru следует называть сайтом или лендингом; личный кабинет и регистрация находятся на mtrhit.ru.
- **Единое резервирование «Ядра» и управляемых проектов:** Штатный backup «Ядра» охватывает центральный контур и все фактически созданные физические хранилища управляемых проектов. Центральная и каждая проектная SQLite снимаются безопасным online backup; для всех включённых данных единообразно проверяются запрещённые пути, секреты, inventory, SHA-256, служебная принадлежность и целостность. Полный охват достижимой Git-истории не сокращается: объекты читаются одним пакетным процессом, обычные, пустые, бинарные, ZIP и вложенные ZIP blobs проверяются, а ошибка протокола блокирует backup. Решение не создаёт проекты, не мигрирует данные и не переключает runtime.
- **Allow Strategy and engineering tasks to access the public MetricHit landing at…:** Цель: Allow Strategy and engineering tasks to access the public MetricHit landing at go.mtrhit.ru

Scope:
- Permit read-only access to https://go.mtrhit.ru/ for landing review and development context
- Keep CRM and mtrhit.ru account or registration site prohibited
- Do not grant publication, login, form submission, account access, spending, or production-change authority

Ограничения:
- Access is limited to the exact public landing host go.mtrhit.ru
- External publication and other owner-gates remain mandatory
- No landing implementation in this policy task
- One native task-thread; synchronize AGENTS and canonical context only

Acceptance:
- Approved memory contains the exact access boundary
- AGENTS.md distinguishes permitted go.mtrhit.ru from prohibited CRM and mtrhit.ru
- Current context and operating context are synchronized as needed
- Focused memory/governance tests, check-memory, git diff --check pass
- One commit, clean status, completed handoff

Источник решения: explicit owner authorization 2026-08-16 in SERVER Strategy
- **Глобальные навыки Codex и continuity Strategy:** Установлены и проверены глобальные навыки: маркетинг (marketing-brief, positioning, customer-research, content-strategy, seo-strategy, copywriting, cro-audit, analytics-tracking, email-sequence), дизайн (frontend-design, ui-ux, image) и разработка (security-best-practices, playwright, code-review, architecture-review, debugging-and-error-recovery, gh-fix-ci). Навыки выбираются по результату и scope, не заменяют execution card, owner-gates, проверки или одного writer. Контролируемый pilot разрешает только 2–3 независимые read-only research/audit-ветки с synthesis Strategy; для mutation/code/data/config остаются один writer и один commit. Владелец работает с телефона: platform approval запрашивается в текущем чате; личные имя/email не требуются, а для commit используется локальная identity MetricHit Automation <metrichit@local.invalid> без глобального Git-конфига. Подпроект «Лендинг» активен под MetricHit: ID 2a95e640-23b0-44a6-96e5-f9f732cd41fa, отдельная scoped memory, исходники work/landing/index.html и work/landing/404.html, публичный URL https://go.mtrhit.ru/ подтвердил HTTP 200 read-only. GitHub-доступ, deploy, login и конфигурация не выполнялись; публикация возможна только после будущего доступа и отдельной команды.
- **Этап разрешения принадлежности legacy-записей завершён:** По утверждённой границе между управляющим контуром «Ядра» и managed project MetricHit все актуальные 348 unresolved legacy-записей получили проверяемую принадлежность. 92 первичных назначения с итоговым разделением 63 «Ядро» / 29 MetricHit и одна append-only коррекция распространяются на связанные source/document/version/audit/task записи; migration plan теперь содержит 0 unresolved и readyToMigrate=true. Фактический перенос, export/import, cutover, project SQLite, runtime, schema и интерфейс не изменялись и требуют отдельного решения владельца.
- **Завершён этап устранения регрессий operator panel:** На поставке 9f0ac1e оставлена единая актуальная реализация экранов, устранены дублирующиеся и устаревшие скрытые элементы управления, E2E-контракты приведены к итоговому интерфейсу, а проверка состояния рабочей области больше не зависит от фиксированного количества открытых задач. Подтверждено: Python — 167 passed, 1 skipped; Node — 51 passed; проверки синтаксиса, зависимостей и изменений прошли. Исходная быстрая проверка качества остаётся историческим основанием этапа; результат не утверждает более широкую проверку или переработку проекта.
- **Рабочий процесс SERVER, Strategy и executor:** SERVER и C:\MetricHit\workspace остаются primary workspace MetricHit. Strategy — read-only human-facing router. Controlled parallel execution v1 допускает максимум два независимых writer-а: каждый работает в отдельном неканоническом Git worktree и ветке, объявляет точные path/SQLite/shared resources и имеет один commit. Пересечения, третья задача и core/shared resources блокируются fail-closed; разные project SQLite совместимы; central control-plane, context pack, memory/policy и integration сериализованы. Read-only research pilot 2–3 веток сохраняется. Orchestration v1 активирует первый временный read-only coordinator profile MetricHit → Редакция: compiler выдаёт только цепочку Ядро → MetricHit → Редакция → задача; coordinator создаёт одну child card, выбирает skills из allowlist и принимает domain evidence одного writer-а. Максимальная глубина два перехода, до трёх read-only веток, lifecycle и sequential integration enforced через handoff metadata; UI, daemon, scheduler, API и автономная production-редакция не добавлены. Fast path, clean Git, проверки, Sol/Luna gates, owner-gates и managed sandbox сохраняются. AGENTS.md является короткой конституцией Strategy. Перед задачей Strategy определяет scope и тип, затем compiler читает только паспорта и активную память цепочки Ядро → проект → подпроект → задача. Для executor формируется минимальный временный task context pack; sibling scope и история без основания не загружаются, а audit сохраняет fingerprint и технические сигналы без текста команды и внутреннего reasoning. P0–P5 реализованы и прошли acceptance на пилоте MetricHit «Редакция» и «Панель»; контракт находится в documents/structured-memory.md, schema — migration v11.

- **Freelance.ru commands-only automation:** В отделе `MetricHit → Автоматизация` разрешён только Freelance.ru-контур: по прямой команде владельца можно открыть локальный Chrome, войти, заполнить формы, создать, отредактировать, снять или опубликовать объявления без отдельного подтверждения каждой позиции. Расписания нет. Состояние сессии хранится исключительно в `C:\ProgramData\MetricHit\automation-secrets\freelance-ru\freelance-session.dpapi`, зашифровано DPAPI и защищено ACL; пароль не хранится. FL.ru, Kwork, Avito и любые иные внешние аккаунты остаются запрещены.
- **Подтверждение работы задач и сохранение исторических записей:** Владелец подтвердил, что в живом использовании корректно работают переход задачи в открытое состояние и обратимое изменение статуса через галочку. Исторические завершённые внутренние записи о выполненных инженерных работах и аудите остаются в списке задач; их нельзя скрывать, архивировать, удалять или изменять без нового прямого решения владельца.
- **Read-only доступ к публичным веб-источникам:** Strategy и engineering-задачи могут открывать любые публично доступные URL только для read-only исследования и анализа. Запрещены login или иная авторизация, отправка форм, публикации, покупки и иные расходы, изменения аккаунтов, доступов или настроек, а также скачивание либо обработка приватных клиентских данных. CRM и сайт регистрации/личного кабинета https://mtrhit.ru/ остаются вне доступа; действующие явные owner-gates сохраняются.
- **Record MetricHit landing development as an integrated Yadro workstream and add…:** Цель: Record MetricHit landing development as an integrated Yadro workstream and add it to the owner task for 17.08

Scope:
- Record that development of the existing MetricHit landing is integrated into Yadro planning and execution
- Preserve the existing approved landing resource at https://go.mtrhit.ru/
- Append one concise action item to owner task a1023db2-32d7-4286-b635-03c27fef6a35

Ограничения:
- Do not implement or publish landing changes
- Do not access mtrhit.ru or the landing site
- Do not alter unrelated tasks, code, or configuration
- Use normal memory and task workflows
- One native task-thread, focused tests, one commit only if tracked canonical context changes

Acceptance:
- Approved memory contains the integration decision and retains the existing landing URL as a resource
- The exact owner task remains pending and includes the landing-development action item
- Approved current context is regenerated if affected
- Focused memory/task tests, check-memory, git diff --check pass
- Clean git status and completed handoff

Источник решения: owner decision 2026-08-16 in SERVER Strategy
- **Implement the complete MVP vertical for owner-managed memory candidates in the…:** Цель: Implement the complete MVP vertical for owner-managed memory candidates in the Yadro operator panel

Scope:
- Pending candidate list and candidate detail with content, semantic key, provenance, task linkage, status, and conflict warning
- Owner actions to approve or reject a candidate through the protected existing memory workflow
- Conflict resolution action that preserves audit and memory integrity
- Approval comment is optional; rejection reason is mandatory; conflict-resolution reason is mandatory
- Synchronize generated current context after approved memory changes as required by existing conventions
- Focused API, memory, policy, and Edge E2E coverage for the full vertical

Ограничения:
- MVP only: no auto-approval, bulk actions, speculative abstractions, or unrelated UI changes
- Strategy remains read-only; all repository changes are made only by this single native engineering task-thread
- Use existing SQLite schema, authorization token protection, memory workflows, project conventions, and locked dependencies
- Read the operator-panel UX contract before changing the panel
- One implementation commit and clean git status

Acceptance:
- Pending candidates can be listed and inspected in the operator panel
- Owner can approve with no comment or with an optional comment
- Reject is blocked without a reason and succeeds with a reason
- Conflict resolution is blocked without a reason and succeeds with a reason while preserving audit history
- Approved memory and generated current context remain consistent
- Focused Python tests and at least one current Playwright E2E using system Microsoft Edge pass
- Focused memory and governance policy tests pass
- check-memory and git diff --check pass
- Exactly one commit is created and git status --short is clean

Источник решения: owner decision 2026-08-16 in SERVER Strategy
- **Зафиксировать завершение unified intake v1 без аудио:** Цель: Зафиксировать завершение unified intake v1 без аудио

Scope:
- Unified intake v1 завершён и включает текст, ссылки и текстовые файлы.
- Голос в MVP не является отдельным входящим контуром: пользователь использует диктовку устройства или браузера, а в Ядро поступает уже текст.
- Ядро не принимает, не транскрибирует и не хранит аудио.
- Синхронизировать roadmap, operating context и exported current context с этим решением.

Ограничения:
- Не изменять функциональный код, API, UI, схему БД или тесты поведения.
- Не добавлять аудиофайлы, транскрибацию или аудиохранилище.
- Следующим этапом roadmap должен стать UI управления памятью.
- Создать ровно один native task-thread.

Acceptance:
- Approved memory содержит решение о scope unified intake v1.
- Roadmap переносит unified intake v1 в завершённое и делает UI управления памятью ближайшим этапом.
- Current context и operating context не утверждают, что Ядро принимает или хранит аудио.
- Пройдены focused memory/policy checks, check-memory и git diff --check; один commit и чистый status.

Источник решения: Прямое утверждение владельца в Strategy-чате 16.08.2026.
- **Скриншоты в финальном отчёте по интерфейсу:** После завершения работ с интерфейсом любого проекта, включая само «Ядро», финальный отчёт должен содержать скриншоты выполненного результата. В отчёт включается не более четырёх скриншотов. Правило относится только к интерфейсным работам и не расширяет состав иных проверок или формат отчёта.
- **Визуальное направление operator panel:** Operator panel следует референсам Codex Desktop: тёмный монохромный интерфейс на чёрном, графитовом и сером фоне с мягким off-white текстом; без синих акцентов, светящегося белого оформления и самостоятельной дизайн-системы. Макеты и скриншоты — только референсы композиции и визуального языка, не реальные данные. Завершены Projects, Tasks и Memory: icon primary nav, без повторного рендеринга проекта, с явной связью задачи с проектом/подпроектом и сгруппированными строками памяти. Проверенный результат — e3431ce52f3b81540518ede8e619b07e2b8201cd: на поставке 28 E2E и 47 Python tests; последующая независимая live-проверка подтвердила current HEAD/served assets, browser screenshots и отсутствие browser errors.
- **Утверждённые рабочие экраны operator panel:** В продолжение утверждённого Codex Desktop-like направления реализованы: универсальная локальная рабочая область подпроекта с верхним меню и обзором; «Активность» с audit-потоком, рабочими фильтрами проекта и периода и правой панелью подробностей без изменения размеров строк; глобальный «Поиск» с двухколоночной областью, фильтрами типа/проекта/статуса, сбросом, сортировкой и переходом к первоисточнику. Глобальная левая навигация сохранена, кроме переноса «Поиска» в конец списка. Проверенные поставки: f82b183, 90184ae, 8a3a2cf, 7f84099, 335e336, a20c15b.
- **Исправить пользовательский заголовок панели с Yadro на Ядро:** Цель: Исправить пользовательский заголовок панели с Yadro на Ядро

Scope:
- Заменить только видимый текст заголовка h1 в operator panel: Yadro на Ядро.
- Сохранить текущие белый цвет, выравнивание слева и чёрный фон.
- Запустить существующую focused E2E-проверку панели на Microsoft Edge.

Ограничения:
- Не менять другие тексты, стили, разметку, поведение, memory, config или тесты.
- Не создавать второй task-thread.
- Не расширять UI scope.

Acceptance:
- Панель отображает Ядро вместо Yadro.
- Существующий focused E2E и связанные focused tests проходят.
- Один commit и чистый git status.

Источник решения: Прямое утверждение владельца в Strategy-чате 16.08.2026.
- **Изменить стиль названия Yadro в операторской панели:** Цель: Изменить стиль названия Yadro в операторской панели

Scope:
- В src/metrichit_os/operator_panel.py у заголовка Yadro установить белый цвет.
- Выровнять этот заголовок по левому краю.
- Сохранить чёрный фон панели.

Ограничения:
- Не менять никакие другие тексты, стили, разметку, поведение или файлы вне необходимого UI-кода и его точечной проверки.
- Не изменять фон панели.
- Соблюсти UX-контракт operator panel и выполнить E2E-критическую проверку поведения.
- Не создавать второй task-thread.

Acceptance:
- Название Yadro белое и выровнено слева.
- Фон панели остаётся чёрным.
- Проверка подтверждает оба CSS-свойства и отсутствие изменения фона.
- Один commit; чистый git status.

Источник решения: Прямое утверждение владельца в Strategy-чате 16.08.2026.
- **Record the approved MVP UX direction for the Yadro owner workspace:** Цель: Record the approved MVP UX direction for the Yadro owner workspace

Scope:
- Keep the existing dark theme, white Yadro heading, blue action accent, and low visual noise
- Do not start a visual redesign
- After the current assessment of splitting embedded HTML CSS JS, prioritize a short owner-focused UX pass
- Separate global navigation from tabs of the active section and make active context clearer
- Make Overview prioritize: today priority, pending decisions, nearest tasks, and recent activity
- Improve spacing and typography hierarchy for faster owner orientation

Ограничения:
- No UI implementation in this task
- No speculative design system or broad redesign
- Preserve MVP and speed principle
- One native task-thread; only memory/current context/roadmap synchronization

Acceptance:
- Approved memory records the UX direction
- Current context is regenerated through the standard workflow
- Roadmap reflects the sequence: technical assessment then focused owner UX pass
- Focused memory/governance tests, check-memory, git diff --check pass
- One commit and clean status

Источник решения: owner decision 2026-08-16 in SERVER Strategy

## Редакционные правила

- **Статьи MetricHit: не раскрывать механику бота:** Никогда не описывать, как работает бот, и не раскрывать механику его действий в каждой статье MetricHit на любой площадке.
- **Статьи MetricHit: не писать об отсутствии гарантий:** Никогда не писать об отсутствии гарантий результата, позиций, трафика или лидов в каждой статье MetricHit на любой площадке.
- **Правила подготовки статей MetricHit:** Статьи MetricHit оригинальны, сохраняют подтверждённые кейсы и цифры, естественно используют утверждённые ключи и содержат не менее 9 000 знаков содержательного текста. Тарифная сетка, пороги пополнения и таблицы тарифов запрещены; допустимо контекстное упоминание «от 0,15 ₽ за клик». Служебные SEO-метки не публикуются. В статье четыре естественные ссылки на https://go.mtrhit.ru/: в начале, две внутри и в финале/CTA. Нужны две оригинальные эффектные иллюстрации, соответствующие деловой или технической площадке. Заявка на авторство описывает регулярное экспертное направление MetricHit, а не одну статью.
- **Чистый текст для копирования редакционных материалов:** Материалы MetricHit, которые готовятся для копирования на внешнюю площадку, оформляются чистым текстом: без Markdown-выделения звёздочками и без хештегов. Заголовки и подзаголовки пишутся обычными строками. Это правило не отменяет требования к естественным ссылкам, утверждённой семантике, одному интенту, CTA, оригинальности и требованиям конкретной площадки.
- **Визуальный пакет и визуальный язык редакционных материалов MetricHit:** Каждый содержательный черновик статьи по умолчанию получает визуальный пакет: обложку для целевой площадки и две оригинальные поддерживающие иллюстрации для конкретных разделов, если владелец явно не отказался от него. Исполнитель визуально проверяет все изображения до поставки и регенерирует слабые. Во всех будущих редакционных визуалах MetricHit стрелки, наконечники стрелок, шевроны и метафоры линии тренда запрещены как декоративные элементы по умолчанию. Они допустимы только когда конкретный материал напрямую и фактически раскрывает измеренное движение, динамику роста или изменения либо явно направленный процесс, и тогда должны быть уместны фактам. Обычная обложка использует нейтральную тематическую метафору. Базовый язык: глубокий графитовый или почти чёрный фон, стеклянные панели, cyan/blue и тёплые оранжевые акценты. Запрещены выдуманные доказательства, данные, кейсы, скриншоты интерфейса, логотипы и клиентские идентификаторы; референс-скриншоты не хранятся и не копируются. Отдельное согласование не требуется, кроме глобальной смены стиля, реальных фотографий или логотипов и внешней публикации. Существующие материалы и assets не меняются.
- **Целевые запросы публичных материалов только из утверждённого ядра:** Каждый новый публичный пост или статья MetricHit вне Telegram использует один основной целевой запрос и при необходимости ноль или несколько вторичных целевых запросов, выбранных дословно только из утверждённого полного не-навигационного семантического ядра MetricHit из 145 запросов. Семантика для создаваемой, написанной или уже опубликованной статьи собирается только по тексту самого материала, сохранённому в утверждённой памяти либо локальном editorial-реестре. Для подбора семантики запрещено открывать, посещать или иным образом переходить на публичную страницу уже опубликованной статьи; статус публикации не меняет источник текста и запросов. Каждый выбранный запрос берётся дословно из утверждённой базы семантики в памяти. Все целевые запросы принадлежат одному выбранному кластеру либо нескольким документированно смежным кластерам и обслуживают один пользовательский интент; переоптимизация, смешение несвязанных кластеров и повтор запросов не допускаются. Для нескольких кластеров execution card и delivery QA фиксируют полный список кластеров и обоснование их смежности. Нельзя создавать синонимы, LSI-фразы, геоварианты или другие дополнительные целевые запросы вне утверждённого списка. Обычный естественный неключевой текст разрешён, но не считается целевым поисковым запросом. Compiler и delivery validation fail-closed отклоняют ключ вне ядра, вне зафиксированных кластеров, повтор, несколько кластеров без обоснования смежности или несоответствующее card доказательство. Брендовые и навигационные варианты исключены, геокандидаты требуют предварительного подтверждения спроса. Telegram полностью исключён; цель индексации Яндекса для новых публичных материалов вне Telegram не меняется. Архив и существующие черновики не меняются.
- **Количество целевых запросов по объёму публичного материала вне Telegram:** Каждый новый публичный пост или статья MetricHit вне Telegram использует уникальные точные целевые запросы из утверждённого не-навигационного ядра из 145 запросов в зависимости от объёма основного текста: 1 800–2 800 знаков — 8–12 запросов; 2 801–5 000 — 10–16; 5 001–7 000 — 14–20; 7 001–9 000 — 18–26. Основной запрос входит в число, находится в заголовке и первом абзаце; каждый вторичный естественно присутствует в основном тексте хотя бы раз. Для текста короче 1 800 или длиннее 9 000 знаков delivery QA фиксирует обоснование количества без выдумывания порогов. Сохраняются один интент, один либо несколько документированно смежных кластеров, точные записи ядра, отсутствие повторов и keyword stuffing, запрет выдуманных синонимов/LSI/геовариантов и geo demand gate. Telegram полностью исключён; архив, существующие черновики и публикации не меняются.
- **Индексация Яндекса и post-indexation PF-target для публичных материалов вне Telegram:** Для каждого нового публичного поста или статьи MetricHit вне Telegram главная редакционная цель — попасть в индекс Яндекса по выбранным утверждённым не-навигационным запросам одного кластера либо нескольких документированно смежных кластеров при едином пользовательском интенте. Execution card фиксирует только SEO-цель индексации; до публикации и delivery не требуют и не выполняют проверку индексируемости, находимости, URL, статуса или доказательства индексации свежего материала. Только после независимой фактической проверки индексации опубликованный материал может рассматриваться для отдельной owner-approved ПФ-кампании с указанными материалом/URL, бюджетом и scope. Правило не запускает кампанию, не разрешает публикацию, расходы или доступ к аккаунту. Telegram полностью исключён из этого правила. Опубликованный архив и существующие черновики не меняются.
- **Позитивная подача ПФ в публичных материалах:** В публичных статьях, черновиках и рекламных материалах о поведенческих факторах не поднимать темы рисков, санкций, фильтров, отсутствия гарантий, «безопасности», «когда ПФ не помогут» и отрицательных ответов на вопрос о ТОП. Вместо этого материал приносит практическую пользу через выбор запросов, подготовку посадочных страниц, регион, дневные лимиты, бюджет, контроль выполненного объёма, оценку динамики и масштабирование кампании. Правило относится только к публичной редакционной подаче и не изменяет внутренние продуктовые факты.
- **Публичные материалы MetricHit: не упоминать отсутствие гарантий:** Во всех новых публичных материалах MetricHit — статьях, TenChat, VK, Telegram и других открытых каналах — никогда не упоминать формулировку «позиции не гарантируются» и её смысловые варианты: отсутствие гарантий результата, позиций, трафика или лидов. Правило регулирует только публичную редакционную подачу: оно не отменяет внутренние продуктовые факты и обязательные юридические раскрытия, а также не требует ретроспективно переписывать уже опубликованные материалы.
- **Сообщение тестового бонуса:** Во внешних рекламных материалах тестовый бонус подаётся через выгоду: 1 000 кликов на тест без пополнения баланса. Основной CTA сначала сообщает выгоду, затем действие: зарегистрироваться и отправить логин в Telegram-поддержку. Слова «один раз» и «только один раз» не повторяются в обычных рекламных CTA. Фактическое ограничение на однократное начисление сохраняется во внутреннем описании условий и при необходимости указывается в FAQ или полных правилах предложения. Базовый факт product.test_bonus не заменять и не удалять.
- **Один материал — один интент и CTA:** Одна статья должна иметь один основной интент и один CTA; материалы для разных площадок должны быть оригинальными, а не механическими копиями.
- **Скрывать клиентские идентификаторы:** Клиентские домены, запросы и иные идентифицирующие данные следует скрывать без явного разрешения на публикацию.
- **Публикация требует подтверждения:** Статью нельзя считать опубликованной без прямого подтверждения владельца или проверяемой ссылки.
- **Разделять факты и гипотезы:** В материалах необходимо разделять официальные сведения, наблюдения команды и авторские гипотезы.
- **Формат Telegram: кратко и профессионально:** Материалы Telegram должны быть короткими, профессиональными и информативными; длинный формат допустим только когда он оправдан темой.
- **Редакционное правило TenChat: объём и поисковая подача:** Для поста MetricHit в TenChat действует технический максимум 7 000 знаков, включая пробелы и пунктуацию. Рабочий целевой объём — 4 000–5 500 знаков; объём не является самоцелью, поэтому лимит не заполняется ради длины. Материал строится вокруг одного поискового интента. Основной ключ естественно присутствует в заголовке и начале текста; далее тема раскрывается через практические объяснения, примеры или кейсы и 2–4 уместные ссылки. Переоптимизация — повторение ключей, ссылочный спам или текст, написанный для роботов вместо читателя, — не допускается.
- **Практическая польза перед продуктом:** Контент должен сначала приносить практическую пользу и только затем показывать продукт.
- **Стандарт объёма и SEO-структуры новых VK-постов:** Для каждого нового публичного VK-поста MetricHit действует целевой объём основного текста 1 800–2 800 русских знаков без внутренней metadata и URL. Узкая новость или чек-лист допустимы в диапазоне 1 200–1 799 знаков только при полном решении одного интента и с зафиксированной в QA причиной; 3 000–4 000 знаков допустимы только для действительно нужного подробного практического разбора и тоже с причиной. Объём нельзя увеличивать только ради SEO; менее 1 200 и более 4 000 знаков не допускаются. Количество уникальных точных целевых запросов определяется общей нетелеграмной шкалой по фактическому объёму: для целевого диапазона это 8–12 запросов, включая основной. Разрешены один кластер либо несколько документированно смежных кластеров при едином интенте. Основной запрос естественно находится в заголовке и первом абзаце; каждый вторичный естественно присутствует в тексте хотя бы раз, без keyword stuffing. Заголовок, начало, подзаголовки или чек-лист и практический вывод раскрывают ту же задачу. Структура обязательна: ясный заголовок, ответ в начале, полезные подзаголовки или чек-лист, конкретные практические детали, практический вывод и один естественный CTA. QA отклоняет воду, повторения и неподтверждённые SEO-обещания. Правило не обещает позицию и не требует проверять индексацию свежего черновика; Telegram, статьи и TenChat не затрагиваются.

## Подтверждённые публикации и площадки

- **Пять активных объявлений Avito:** Подтверждены активные объявления для Новосибирска, Перми, Екатеринбурга, Санкт-Петербурга и Москвы.
- **Три подтверждённые статьи в Дзене:** На 13 августа 2026 года подтверждены три опубликованные статьи MetricHit в Дзене: о поведенческих факторах, популярных запросах и распределении запросов по страницам.
- **Накрутка ПФ для бизнеса: как подготовить сайт к запуску:** Владелец подтвердил публикацию на Oborot.ru 02.09.2026 статьи «Накрутка ПФ для бизнеса: как подготовить сайт к запуску». Публичный URL владельцем не предоставлен. Для этой статьи зафиксированы обложка и точный список целевых запросов для будущего отдельного рассмотрения ПФ-продвижения; данная запись не подтверждает запуск кампании или независимую индексацию.
- **Статья MetricHit опубликована на Oborot.ru:** Статья «Накрутка ПФ для интернет-магазина: как выбрать запросы, категории и дневной лимит в Яндексе» опубликована на Oborot.ru 01.09.2026. Публичная страница: https://oborot.ru/blogs/nakrutka-pf-dlya-internet-magazina-kak-vybrat-zaprosy-kategorii-i-dnevnoj-limit-v-yandekse-i277848.html.
- **Oborot.ru подключён к редакции MetricHit для ручного пакета:** Oborot.ru подключён и проверен для редакции MetricHit только в режиме manual-package. Вход владельца в существующий аккаунт подтверждён; в доступном кабинете не обнаружены официальный API или self-service механизм автоматической публикации. Публикации остаются ручными и требуют отдельного одобрения владельца. Связанная подтверждённая публикация: https://oborot.ru/blogs/nakrutka-pf-i277755.html.
- **Первая статья MetricHit опубликована в Sostav:** Статья «SEO вывело сайт в ТОП, а продажи не выросли: где ломается воронка» опубликована в блоге MetricHit на Sostav / SBlogs. Публичная страница: https://www.sostav.ru/blogs/293151/101025. На странице подтверждены заголовок, блог MetricHit, дата и время публикации 12.08.2026 17:51:40, canonical URL и разрешение index, follow.
- **Публикация «Накрутка ПФ» на Sostav / SBlogs:** Публикация «Накрутка ПФ» на Sostav / SBlogs от 29.08.2026 доступна по URL https://www.sostav.ru/blogs/293151/104675. Проверка 30.08.2026 подтвердила индексацию Яндексом точным url:-запросом: один результат с заголовком «Накрутка ПФ»; страница разрешает index, follow, canonical корректный. Индексация Google не подтверждена из-за anti-automation.
- **Навигация по каналу MetricHit:** Закреплённый пост: да.

📌 **Навигация по каналу MetricHit**

Собрали основные материалы, чтобы вы могли быстро найти нужную информацию.

**О MetricHit**

— [Кто мы и чем занимаемся](https://t.me/mtr_hit/6)
— [Тарифы без посредников и абонентской платы](https://t.me/mtr_hit/7)

**Как работают поведенческие факторы**

— [Почему коммерческому сайту сложно получать трафик без ПФ](https://t.me/mtr_hit/8)
— [Почему нельзя резко останавливать ПФ после выхода в ТОП](https://t.me/mtr_hit/10)

**Подготовка и безопасный запуск**

— [Три ошибки, которыми можно навредить сайту](https://t.me/mtr_hit/9)
— [Какие запросы добавлять в первый проект](https://t.me/mtr_hit/11)
— [Когда ПФ не помогут: что проверить до запуска](https://t.me/mtr_hit/13)

[**ТАРИФНАЯ СЕТКА**](https://t.me/mtr_hit/22)

*Навигацию будем дополнять по мере выхода новых материалов.*

🌐 [**Сайт MetricHit**](https://go.mtrhit.ru/)
⚙️ [**Регистрация**](https://mtrhit.ru/)
💬 Поддержка: **@Metric\_Hit**
- **Три обновления Яндекса, которые стоит знать:** ⚡️ **Три обновления Яндекса, которые стоит знать**

**1. Данные по запросам — теперь по часам**
В Вебмастере можно быстрее увидеть изменения показов и кликов. Но почасовые цифры предварительные — выводы лучше делать после полной обработки данных. [Подробнее](https://webmaster.yandex.ru/blog/dannye-po-chasam-v-monitoringe-zaprosov)

**2. Появилась статистика видимости в Алисе AI**
Новый отчёт показывает, упоминает ли Алиса ваш сайт и какие конкуренты чаще попадают в её ответы. Найти его можно в разделе «Эффективность».
[Подробнее](https://webmaster.yandex.ru/blog/efficiency-alice)

**3. Яндекс изменил расчёт ИКС**
Показатель мог заметно вырасти или снизиться без изменений на сайте. Паниковать не нужно: сам Яндекс подчёркивает, что ИКС напрямую не влияет на позиции.
[Подробнее](https://webmaster.yandex.ru/blog/iks-update)
- **Работа MetricHit восстановлена:** Приложение: `work/social/telegram/assets/2026-08-17-work-restored.png`.

⚡️ **Работа MetricHit восстановлена**

16 августа часть инфраструктуры ПФ-сервисов столкнулась с массовыми сбоями. Панель MetricHit оставалась доступна, но клики временно не выполнялись.

По предварительным данным, причиной стали масштабные ограничения мобильного интернета в регионах России. Подтверждений версии об обновлении антифрода Яндекса мы не нашли.

В ночь на 17 августа работа была восстановлена.

— деньги за невыполненные клики не списывались
— всем затронутым клиентам начисляем 300 компенсационных кликов (у кого были проблемы напишите в [**поддержку**](https://t.me/Metric_Hit))

Продолжаем следить за стабильностью инфраструктуры.
- **+20% к пополнению баланса:** Приложение: `work/social/telegram/assets/2026-08-19-bonus-20-percent.png`.

⚡️ +20% к пополнению балансаДо 25 августа пополняйте баланс MetricHit — мы добавим ещё 20% сверху.Больше кликов. Больше возможностей для запуска. Без дополнительных расходов.Акция действует до 25.08 включительно.➡️ Личный кабинет: [https://mtrhit.ru➡️](https://mtrhit.ru➡️) Сайт: [https://go.mtrhit.ru➡️](https://go.mtrhit.ru➡️) Поддержка: [build\_metric\_hit\_strategy\_report.py](work/articles/research/supporting/build-sources/build_metric_hit_strategy_report.py)
- **Позиции просели: что проверить до изменения ПФ:** Приложение: `work/social/telegram/assets/2026-08-20-positions-declined-checks.png`.

**⚡️ Позиции просели: что проверить до изменения ПФ**

Не увеличивайте лимиты сразу.
Сначала определите причину просадки.

1\.  Проверьте масштаб.
2\.  Упал один запрос или вся группа? Изменение одной фразы ещё ни о чём не говорит.
3\. Проверьте целевую страницу
В Вебмастере откройте «Индексирование» → [«Страницы в поиске»](https://yandex.ru/support/webmaster/ru/service/searchable). Если нужная страница исключена, увеличение кликов не поможет — сначала верните её в поиск.
Проверьте нарушения
Откройте «Оптимизация сайта» → [«Безопасность и нарушения»](https://yandex.ru/support/webmaster/ru/service/security-threats). При наличии ограничений сначала устраняется их причина.
4\. Посмотрите, какой URL ранжируется
Если вместо нужной страницы Яндекс показывает другую, не направляйте дополнительный объём на старый URL — сначала разберитесь с релевантностью страниц.

Усиливать проект стоит только тогда, когда нужная страница находится в поиске, нарушений нет, а просадка затронула всю группу запросов.
- **MetricHit расширил инфраструктуру:** Приложение: `work/social/telegram/assets/2026-08-25-infrastructure-expanded.png`.

⚡️ ** MetricHit расширил инфраструктуру**

За последние дни количество новых пользователей и активных проектов заметно выросло. В пиковые часы мы упёрлись в лимиты прежней конфигурации.

На выходных команда развернула дополнительные мощности, перераспределила нагрузку и увеличила резерв инфраструктуры.

Новая конфигурация уже работает. Теперь система может обрабатывать больше кликов одновременно и стабильнее проходить периоды высокой нагрузки.

Продолжаем следить за показателями и масштабировать инфраструктуру вслед за ростом проектов.
- **Новая тарификация применена ко всем пользователям:** Новая тарификация применена ко всем пользователям. Если вдруг у вас старая цена, то напишите в поддержку, быстро исправим.
- **Масштаб вырос. Цена за клик снизилась!:** Приложение: `work/social/telegram/assets/2026-08-27-prices-reduced.png`.

⚡️ Масштаб вырос. Цена за клик снизилась!В предыдущем посте мы рассказывали, что MetricHit расширил инфраструктуру. Новые мощности дали системе необходимый запас и позволили обрабатывать больше кликов одновременно.Но масштабирование повлияло не только на стабильность. При большем общем объёме расходы на инфраструктуру растут медленнее, чем количество обрабатываемых кликов. За счёт этого мы смогли пересчитать экономику сервиса и снизить цены.Не в рамках акции и не на несколько дней. Мы обновили всю тарифную сетку.Базовая стоимость клика снизилась с 1,50 ₽ до 0,50 ₽. При пополнении от 10 000 ₽ цена теперь составляет 0,40 ₽ — это 25 000 кликов вместо прежних 6 600 за тот же бюджет.Полная сетка:— от 1 000 ₽     — 0,50 ₽ за клик;— от 10 000 ₽   — 0,40 ₽— от 50 000 ₽   — 0,30 ₽— от 100 000 ₽ — 0,25 ₽— от 150 000 ₽ — 0,20 ₽— от 200 000 ₽ — 0,15 ₽На разных уровнях пополнения тот же бюджет теперь даёт от 1,75 до 3,75 раза больше кликов.Новые тарифы уже действуют в личном кабинете. Для агентств и крупных объёмов по-прежнему доступны индивидуальные условия.➡️ Личный кабинет: [https://mtrhit.ru➡️](https://mtrhit.ru➡️) Поддержка: [build\_metric\_hit\_strategy\_report.py](work/articles/research/supporting/build-sources/build_metric_hit_strategy_report.py)
- **Вы просили — мы услышали:** Приложение: `work/social/telegram/assets/2026-08-28-bonus-15-percent.png`.

⚡️ Вы просили — мы услышалиНе так давно мы проводили акцию с бонусом 20% к пополнению. Ей воспользовались почти 60% наших клиентов, а после завершения многие просили её продлить.Поэтому решили вернуть бонус — теперь уже на новых тарифах.До 1 сентября  включительно добавляем 15% к каждому пополнению от 20 000 ₽.Акция действует для всех пользователей MetricHit. Ограничений по максимальной сумме пополнения нет.Пополняйте баланс, запускайте новые проекты или добавляйте объём в действующие.➡️ Личный кабинет: [https://mtrhit.ru➡️](https://mtrhit.ru➡️) Поддержка: @Metric\_Hit
- **Подтверждённые публикации Telegram:** В Telegram-канале подтверждены семь первоначальных постов со ссылками и девять постов от 12–28 августа 2026. Навигация от 12.08.2026 закреплена; для шести новых постов сохранены приложенные изображения.
- **Как подготовить сайт к запуску ПФ: 5 проверок для владельца бизнеса:** Владелец подтвердил публикацию в Telegram 02.09.2026 поста «Как подготовить сайт к запуску ПФ: 5 проверок для владельца бизнеса». Публичный URL владельцем не предоставлен. Зафиксированы локальные пути исходника и обложки, а также SHA-256 обложки; эта запись основана только на подтверждении владельца и не содержит независимого внешнего подтверждения.
- **Первая публикация MetricHit в TenChat:** Первая публикация MetricHit в TenChat независимо проверена 30.08.2026: «Накрутка ПФ в Яндексе: как управлять продвижением по запросам, региону и бюджету». Публичная страница содержит согласованные заголовок, текст, обложку 4:5, ссылку «Накрутка ПФ», ссылку go.mtrhit.ru и хештеги. URL: https://tenchat.ru/media/6013324-nakrutka-pf-v-yandekse-kak-upravlyat-prodvizheniyem-po-zaprosam-regionu-i-byudzhetu.
- **Статья MetricHit опубликована в TenChat:** Статья «Накрутка ПФ для интернет-магазина: как выбрать стартовую категорию» опубликована в TenChat 01.09.2026. Публичная страница: https://tenchat.ru/media/6035722-nakrutka-pf-dlya-internetmagazina-kak-vybrat-startovuyu-kategoriyu. В публикации использована подтверждённая владельцем обложка из локального пакета TenChat.
- **Черновик Timeweb Cloud: «Сервис накрутки ПФ: как SEO-команде выстроить управляемое продвижение в Яндексе»:** Материал сохранён как article в канале articles для Timeweb Cloud. Статус: draft/unpublished; публичный URL отсутствует. Материал не публиковался и не является результатом.
- **Почему 16 августа не работали многие ПФ-сервисы:** Владелец подтвердил публикацию во VK 17.08.2026 поста «Почему 16 августа не работали многие ПФ-сервисы». В сообщении об инциденте за 16 августа указано: панель оставалась доступна, выполнение кликов было временно приостановлено; предварительно наиболее вероятной причиной названы региональные ограничения мобильного интернета. Версия о масштабном обновлении антифрода Яндекса проверялась, но публичных подтверждений не обнаружено. Работа сервиса была восстановлена в ночь на 17 августа; за невыполненные клики деньги не списывались, затронутым клиентам начислялись по 300 компенсационных кликов. Публичный URL владельцем не предоставлен; пост не закреплён. Внешнее действие в рамках этого обновления не выполнялось.
- **Накрутка ПФ для бизнеса: как запустить накрутку ПФ, когда сайт готов:** Владелец подтвердил публикацию во VK 02.09.2026 статьи «Накрутка ПФ для бизнеса: как запустить накрутку ПФ, когда сайт готов». Публичный URL владельцем не предоставлен. Для этого материала зафиксирован точный список целевых запросов для будущего отдельного рассмотрения ПФ-продвижения; данная запись не подтверждает запуск кампании или независимую индексацию.
- **Обложка сообщества MetricHit опубликована во VK:** Владелец подтвердил публикацию обложки сообщества MetricHit во VK 01.09.2026. Локальный принятый файл: work/social/vk/assets/2026-09-01-metrichit-community-cover-owner-confirmed-published.png. Статус: owner_confirmed_published; отдельное внешнее действие в рамках этого обновления не выполнялось. Handoff для нового чата: обложка завершена; остаются описание сообщества, контакты без номера телефона, дальнейшее наполнение и актуализация закреплённого поста. Автоматизация браузера VK блокируется политикой платформы, но это не препятствие для владельца.
- **Накрутка ПФ интернет-магазина: как подготовить первый запуск для категории:** Владелец подтвердил публикацию во VK 01.09.2026 поста «Накрутка ПФ интернет-магазина: как подготовить первый запуск для категории». Публичный URL не предоставлен. Финальная обложка — owner-confirmed asset без логотипа, текста и стрелок; отдельное внешнее действие в рамках этого обновления не выполнялось.
- **MetricHit — продвижение сайтов в Яндексе с помощью поведенческих факторов:** Владелец подтвердил публикацию во VK 12.08.2026 поста «MetricHit — продвижение сайтов в Яндексе с помощью поведенческих факторов». Это действующий продуктовый пост, а не приветственный и не закреплённый: он описывает настройку сайта, региона, запросов, лимитов кликов и расписания, отслеживание позиций, статистики и расходов, оплату только за выполненные клики без фиксированной абонентской платы, а также 1 000 тестовых кликов после регистрации и обращения в поддержку. В посте отдельно указано, что ПФ не заменяют SEO и не исправляют слабый сайт. Публичный URL владельцем не предоставлен. Внешнее действие в рамках этого обновления не выполнялось.
- **7 вещей, которые нужно проверить на сайте до запуска ПФ:** Владелец подтвердил публикацию во VK 12.08.2026 поста «7 вещей, которые нужно проверить на сайте до запуска ПФ». В нём приведён чек-лист из семи пунктов: техническая доступность и ошибки, соответствие запроса посадочной странице, скорость и мобильная версия, доступные контакты, элементы доверия, старт с запросов в зоне видимости, Яндекс Метрика и цели ключевых действий. ПФ усиливают подготовленные страницы, но не заменяют SEO и не исправляют слабый сайт. Публичный URL владельцем не предоставлен; пост не закреплён. Внешнее действие в рамках этого обновления не выполнялось.
- **Услуга MetricHit «Накрутка ПФ в Яндекс» обновлена во VK:** Владелец подтвердил актуальное состояние услуги MetricHit «Накрутка ПФ в Яндекс» во VK 01.09.2026. Публичная страница: https://vk.ru/market/product/prodvizhenie-saytov-v-yandekse-240809922-13528771?ref=community_showcase&ref_source=link. Указана цена от 1 000 ₽; в карточке установлена новая квадратная обложка и отображается описание услуги. Внешнее действие в рамках этого обновления не выполнялось.
- **Услуга MetricHit «Накрутка в Яндекс Картах» опубликована во VK:** Владелец подтвердил публикацию услуги MetricHit «Накрутка в Яндекс Картах» во VK 01.09.2026. Цена от 5 000 ₽. В карточке установлена вертикальная обложка с текстом «НАКРУТКА В ЯНДЕКС КАРТАХ». Опубликованное описание: «Накрутка в Яндекс Картах для бизнеса, которому важно усилить присутствие в локальной выдаче. Работаем с карточкой организации и спросом в нужном регионе. Перед стартом уточняем задачу, город и текущую ситуацию по карточке. Стоимость — от 5 000 ₽. Итоговый объём подбирается под вашу задачу. Напишите в сообщения сообщества, чтобы обсудить запуск.» Публичный URL владельцем не предоставлен; внешний адрес не указан. Внешнее действие в рамках этого обновления не выполнялось.
- **Услуга MetricHit «Создание сайтов» опубликована во VK:** Владелец подтвердил публикацию услуги MetricHit «Создание сайтов» во VK 01.09.2026. Цена от 10 000 ₽. Для карточки выбран второй визуальный вариант; имя локального файла не зафиксировано. Опубликованное описание: «Создание сайтов для бизнеса: лендинги, корпоративные сайты, каталоги и интернет-магазины. Разрабатываем структуру, дизайн и адаптивную версию под мобильные устройства. Настраиваем формы заявок, базовую SEO-подготовку, аналитику и интеграции, необходимые для работы сайта. Перед стартом уточняем задачи бизнеса, целевую аудиторию, услуги и желаемый результат. Подбираем подходящий формат сайта и согласовываем состав работ. Стоимость — от 10 000 ₽. Итоговая цена зависит от типа сайта, количества страниц, функционала и готовности материалов. Напишите в сообщения сообщества — обсудим задачу и подготовим предложение.» Публичный URL владельцем не предоставлен; внешний адрес не указан. Внешнее действие в рамках этого обновления не выполнялось.
- **Приветственный пост VK отсутствует и не закреплён:** Владелец подтвердил 01.09.2026: приветственного поста о MetricHit в сообществе VK нет; он не публиковался и не закреплялся. Предыдущий факт о публикации и закреплении был ошибочным и больше не является активной памятью.

## Открытые задачи и планы

- **Настроить UTM и registration_click без изменения mtrhit.ru:** Настроить учёт входящих UTM на лендинге и реализовать цель registration_click, не изменяя mtrhit.ru. Срок владельцем не назначен.
- **Семантическое ядро статей: 145 утверждённых запросов:** Использовать утверждённое полное не-навигационное семантическое ядро MetricHit при подготовке статей: для каждого материала выбирать компактный кластер с единым интентом. Полный исходный список сохранён в audit-истории этой задачи.
- **Статьи: добавлять LSI при использовании ключей:** При написании статей и использовании ключей добавлять LSI
- **Статьи: высокочастотные запросы в заголовке:** В заголовке указываем высокочастотные запросы( накрутка пф и т.п.)
- **ВК: увеличить подписчиков и добавить услуги:** нукрутить подписчиков ВК,  добавить больше услуг в ВК
- **ВК: добавить кейсы:** Добавить кейсы в ВК
- **ТГ:** Коли  тг премиум есть, можно уже и сторисы будет пилить от имени канала
- **Статьи: ключевые ВЧ-запросы в главном заголовке:** Еще раз проговорю про заголовки. Важно в статье использовать высокочастотные ключи. То есть накрутка PF, накрутка PF Яндекс, накрутка PF Москва. Но самые высокочастотные это накрутка PF и накрутка поведенческого фактора. Именно эти ключи важно использовать в ваш один, в главном заголовке. самое главное дальше уже используем ключи те которые я списком скидывал их раскидываем. Статьи должны быть наполнены фотографиями, кейсами и так далее. Но заголовок в любом случае накрутка ПФ, накрутка поведенческого фактора в таком формате. То есть высокочастотники именно.
- **Статьи: 2–4 ссылки на сайт в материале:** ты старайся ссылок больше добавлять на проект, на сайт. Ну не одну точнее, а 2-3-4 где-нибудь так. То есть за это ничего не будет, поэтому лучше добавлять побольше.
- **Панель: УТП на странице регистрации:** На странице регистрации (в панели) добавить небольшое УТП (на подобии как в Express)
- **Кейс:** Сделать полноценный кейс, выкатить его на пикабу!
- **Панель: несколько регионов в одном проекте:**  добавить возможность  прописывать в один проект несколько регионов
(от кл: "Как будто это не будет лишним, если ркн ниша, каждый день по 20 проектов заводить такое себе")
- **Написать пост в ТГ:** Пример поста в "Запуск" от 13 августа. Проверить пригодность
- **В меню Идеи добавить возможность редактировать идеи после того как они созданы…:** В меню Идеи добавить возможность редактировать идеи после того как они созданы уже.
- **Нельзя оставлять это, нужно писать день/через день:** Нельзя оставлять это, нужно писать день/через день
- **вопросы к Артему:** У одного из клиентов был вопрос: "Какой алгоритм?"
- **Правка панели:** Добавить в кл кабинете отображение итогового кол-ва кл/сутки по запущенным проектам
- **Настроить ПФ-продвижение опубликованной TenChat-страницы:** После отдельной команды владельца использовать сохранённый operational semantic subset из 44 запросов для настройки ПФ-продвижения опубликованной TenChat-страницы. Кампания ещё не запускалась. Эта operational continuity не заменяет стратегические этапы research-MVP и маркетинговых skills.
