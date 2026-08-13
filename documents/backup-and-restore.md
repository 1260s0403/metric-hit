# Резервное копирование и проверка восстановления

## Формат backup-набора

`scripts/backup-metrichit.ps1` создаёт в `C:\MetricHit\external-backups` один
атомарный каталог с UTC timestamp:

```text
MetricHit-backup-YYYYMMDDTHHMMSSZ/
  MetricHit-backup-YYYYMMDDTHHMMSSZ-workspace.zip
  MetricHit-backup-YYYYMMDDTHHMMSSZ-git.bundle
  MetricHit-backup-YYYYMMDDTHHMMSSZ-manifest.json
```

Компоненты сначала формируются в одноимённом `.staging`-каталоге. Готовым набор
считается только каталог без суффикса `.staging`, содержащий все три файла.
ZIP и bundle имеют SHA-256 и размер в manifest. Manifest не содержит собственный
хеш из-за циклической зависимости; его SHA-256 вычисляют при копировании набора.

## Содержимое workspace ZIP

- согласованная online-копия `data/database/metrichit.db` через `node:sqlite`;
- `data/database/migrations/` и `tests/`;
- `knowledge/`, `documents/`, `scripts/`;
- вся структура `work/`, включая игнорируемые Git исходные ZIP миграции;
- `AGENTS.md`, `README.md`, `.gitignore`, `.gitattributes`;
- `package.json` и известные package/lock-файлы, если они существуют.

Manifest содержит полный инвентарь `work/`: относительный путь, размер и SHA-256
каждого файла, общее количество и размер. Backup завершается ошибкой, если
`work/` изменился во время копирования или копия отличается от источника.

## Git bundle

`*-git.bundle` создаётся командой `git bundle create --all` и содержит все refs
и полную достижимую Git-историю. Manifest фиксирует symbolic HEAD, refs и
обязательные коммиты. Backup завершается ошибкой при detached HEAD.
Bundle не заменяет ZIP: незакоммиченные данные и игнорируемые файлы защищает ZIP,
а историю и коммиты — bundle.

## Исключения и защитные проверки

Не копируются `.git` как обычные файлы, `.codex`, `node_modules`, `logs`,
`secrets`, `temp`, `tmp`, staging, backup-каталоги, `.env`/`.env.*`, auth-файлы,
файлы токенов, credentials, паролей, приватных ключей и временные файлы.
Reparse points запрещены. Если запрещённый путь находится внутри обязательного
`work/`, backup прекращается: рабочие материалы нельзя молча исключать.

Скрипт не обращается к `C:\MetricHit\secrets` и пользовательским каталогам
Codex/ChatGPT. Перед bundle проверяются целостность Git, отсутствие запрещённых
имён путей и характерных форматов секретов во всех достижимых Git blobs. Snapshot
также сканируется офлайн. Эвристика снижает риск, но не является полноценным
secret scanner: нестандартный секрет в нейтрально названном бинарном или большом
файле может потребовать отдельной проверки и очистки Git-истории.

## Read-only аудит прежнего формата

Копия `MetricHit-backup-20260813T195051Z.zip` содержала 43 ZIP-элемента:
SQLite, knowledge, documents, scripts, migrations, AGENTS.md и README.md. В ней
не было `work/`, tests, `.gitignore`, `.gitattributes` или Git bundle. Поэтому из
неё нельзя восстановить 54 импортированных материала, коммит `966f951` или Git-
историю. Размер 165 636 B объясняется составом: 765 271 B преимущественно текста
и SQLite сжались до 156 306 B полезной нагрузки ZIP.

## Создание и автоматическая проверка

Из корня репозитория:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\backup-metrichit.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\test-restore-metrichit.ps1
```

Restore-test выбирает последний завершённый набор либо принимает путь:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\test-restore-metrichit.ps1 `
  -BackupSetPath C:\MetricHit\external-backups\MetricHit-backup-YYYYMMDDTHHMMSSZ
```

В отдельном системном временном каталоге тест:

1. сверяет размеры и SHA-256 ZIP и bundle с manifest;
2. безопасно проверяет пути ZIP, распаковывает его и повторяет офлайн-проверку
   содержимого на характерные форматы секретов;
3. проверяет SQLite только для чтения, `integrity_check` и миграции;
4. сверяет каждый восстановленный файл `work/` с manifest;
5. выполняет `git bundle verify` и сверяет все refs с manifest;
6. клонирует bundle и проверяет Git integrity, HEAD и обязательные коммиты;
7. подтверждает, что активный workspace не изменился;
8. использует доверенный `check-memory.mjs` из активного workspace и никогда не
   исполняет код из проверяемой копии;
9. всегда удаляет временный каталог, в том числе при ошибке.

## Ручное восстановление на чистом компьютере

Нужны Windows PowerShell, Git и совместимая версия Node.js с `node:sqlite`.

1. Скопировать целиком один каталог backup-набора на новый компьютер. Не смешивать
   компоненты с разными timestamp.
2. Сверить имена, размеры и SHA-256 ZIP и bundle с manifest; отдельно записать и
   сверить SHA-256 самого manifest с источником внешней копии.
3. Выполнить `git bundle verify` в пустом bare-репозитории и клонировать bundle:

   ```powershell
   git init --bare C:\Temp\metrichit-verify.git
   git -C C:\Temp\metrichit-verify.git bundle verify <путь-к-bundle>
   git clone <путь-к-bundle> C:\MetricHit\workspace
   ```

4. Распаковать workspace ZIP во временный каталог. Внутри будет один каталог
   `*-workspace` без `.git`.
5. Скопировать всё содержимое этого каталога, включая скрытые корневые файлы, в
   `C:\MetricHit\workspace` поверх checkout. Не применять зеркальное удаление:
   созданный clone-каталог `.git` должен сохраниться.
6. Выполнить проверки:

   ```powershell
   node C:\MetricHit\workspace\scripts\check-memory.mjs
   git -C C:\MetricHit\workspace fsck --full
   git -C C:\MetricHit\workspace status
   ```

ZIP восстанавливает точный файловый snapshot, включая ignored-файлы; bundle
восстанавливает историю. Если ZIP был сделан при незакоммиченных изменениях,
после наложения snapshot они корректно появятся в `git status`.

## Scheduled Task и хранение

`MetricHit-Daily-Backup` продолжает запускать тот же скрипт без параметров в
03:30 по локальному времени, с S4U и без активного RDP-сеанса. Установщик задачи,
расписание, principal и Windows-настройки не изменяются.

Срок локального хранения — 14 дней. Cleanup действует только внутри
`C:\MetricHit\external-backups`: новый набор удаляется целиком как каталог.
Legacy ZIP и его `.sha256` группируются по timestamp и удаляются вместе. Срок
хранения не меняется.

Локальная копия на том же сервере не защищает от потери сервера, тома или общей
компрометации. После успешного restore-test весь каталог набора следует копировать
во внешнее хранилище как единое целое, затем повторно сверять SHA-256 всех трёх
файлов. Наличие внешней копии подтверждается только фактом такой сверки.
