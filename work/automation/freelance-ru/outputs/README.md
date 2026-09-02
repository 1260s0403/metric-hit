# Конвейер публикации услуг Freelance.ru

## Что готово

- `data/offers.json` — каталог пяти уникальных услуг.
- `scripts/build-offer-queue.mjs` — проверяет карточки и собирает очередь.
- `scripts/save-freelance-session.mjs` — по прямой команде владельца сохраняет сессию в DPAPI-хранилище вне repository.
- `scripts/publish-offers.mjs` — заполняет карточки, загружает обложки и публикует услуги.
- `outputs/covers/` — обложки для всех пяти услуг.

## Запуск

```powershell
npm run build:queue
node scripts/save-freelance-session.mjs --owner-command
node scripts/publish-offers.mjs --owner-command --submit --limit=5
```

Сессия хранится только локально в `C:\\ProgramData\\MetricHit\\automation-secrets\\freelance-ru\\freelance-session.dpapi`, зашифрована Windows DPAPI и не добавляется в Git. Пароли не сохраняются. Запуск возможен только по прямой команде владельца; расписания нет. Без `--submit` издатель только готовит карточки и не создаёт объявления.
