import { mkdir, readFile, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";

const root = process.cwd();
const offersPath = resolve(root, "data/offers.json");
const queuePath = resolve(root, "outputs/publish-queue.json");
const reportPath = resolve(root, "outputs/offer-catalog.md");
const categories = new Set([
  "3D и Визуализация", "Архитектура и Дизайн интерьеров", "Бизнес, Продажи и Консалтинг",
  "Веб-разработка и IT", "Видео, Анимация и Моушен", "Дизайн и Брендинг",
  "Иллюстрация и Цифровое искусство", "Инженерия и Проектирование", "Искусственный интеллект",
  "Маркетинг и Продвижение", "Музыка и Звук", "Обучение и Наставничество",
  "Тексты и Переводы", "Фото и Контент"
]);

const offers = JSON.parse(await readFile(offersPath, "utf8"));
const seen = new Set();
for (const offer of offers) {
  const fingerprint = `${offer.category}|${offer.title}`.toLocaleLowerCase("ru");
  if (seen.has(fingerprint)) throw new Error(`Повтор услуги: ${offer.title}`);
  seen.add(fingerprint);
  if (!categories.has(offer.category)) throw new Error(`Неизвестная категория: ${offer.category}`);
  if (offer.title.length < 5 || offer.title.length > 80) throw new Error(`Некорректная длина названия: ${offer.id}`);
  if (!Number.isInteger(offer.priceRub) || offer.priceRub <= 0) throw new Error(`Некорректная цена: ${offer.id}`);
  if (!Number.isInteger(offer.deliveryDays) || offer.deliveryDays <= 0) throw new Error(`Некорректный срок: ${offer.id}`);
  if (offer.description.length < 5 || offer.description.length > 1500) throw new Error(`Некорректное описание: ${offer.id}`);
  if (!Array.isArray(offer.keywords) || offer.keywords.length === 0) throw new Error(`Нет ключевых слов: ${offer.id}`);
}

const queue = offers.map((offer, index) => ({
  sequence: index + 1,
  ...offer,
  status: offer.status ?? "ready",
  publishedUrl: offer.publishedUrl ?? null,
  publishedAt: offer.publishedAt ?? null,
  error: null
}));
const catalog = [
  "# Очередь услуг Freelance.ru", "",
  "| № | Услуга | Цена | Срок | Статус |", "| --- | --- | ---: | ---: | --- |",
  ...queue.map((item) => `| ${item.sequence} | ${item.title} | ${item.priceRub.toLocaleString("ru-RU")} ₽ | ${item.deliveryDays} дн. | ${item.status} |`),
  ""
].join("\n");

await mkdir(dirname(queuePath), { recursive: true });
await writeFile(queuePath, `${JSON.stringify(queue, null, 2)}\n`, "utf8");
await writeFile(reportPath, catalog, "utf8");
console.log(`Очередь из ${queue.length} услуг готова: ${queuePath}`);
