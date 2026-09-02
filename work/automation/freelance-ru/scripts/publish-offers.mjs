import { mkdir, readFile, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { chromium } from "playwright";
import { loadSessionState } from "./session-store.mjs";

const root = process.cwd();
const queuePath = resolve(root, "outputs/publish-queue.json");
const submit = process.argv.includes("--submit");
const limitArg = process.argv.find((arg) => arg.startsWith("--limit="));
const limit = limitArg ? Number(limitArg.split("=")[1]) : 1;
const categoryValues = {
  "3D и Визуализация": "577", "Архитектура и Дизайн интерьеров": "716", "Бизнес, Продажи и Консалтинг": "133",
  "Веб-разработка и IT": "4", "Видео, Анимация и Моушен": "565", "Дизайн и Брендинг": "40",
  "Иллюстрация и Цифровое искусство": "590", "Инженерия и Проектирование": "186", "Искусственный интеллект": "724",
  "Маркетинг и Продвижение": "117", "Музыка и Звук": "89", "Обучение и Наставничество": "663",
  "Тексты и Переводы": "29", "Фото и Контент": "98"
};

if (!process.argv.includes("--owner-command")) {
  throw new Error("Операции Freelance.ru разрешены только по прямой команде владельца: добавьте --owner-command.");
}

const queue = JSON.parse(await readFile(queuePath, "utf8"));
const targets = queue.filter((item) => item.status === "ready").slice(0, limit);
const browser = await chromium.launch({ channel: "chrome", headless: false });
const context = await browser.newContext({ storageState: await loadSessionState() });
const page = await context.newPage();

for (const offer of targets) {
  try {
    await page.goto("https://freelance.ru/offer/create", { waitUntil: "domcontentloaded" });
    if ((await page.title()).includes("Необходимо авторизоваться")) throw new Error("Сессия Freelance.ru истекла");
    await page.getByLabel("Категория").selectOption(categoryValues[offer.category]);
    await page.getByRole("textbox", { name: "Название Вашей услуги" }).fill(offer.title);
    await page.getByRole("spinbutton", { name: "Стоимость услуги" }).fill(String(offer.priceRub));
    await page.getByRole("spinbutton", { name: "Срок выполнения" }).fill(String(offer.deliveryDays));
    await page.getByRole("textbox", { name: "Описание Вашей услуги" }).fill(offer.description);
    await page.getByRole("textbox", { name: "Ключевые слова для поиска" }).fill(offer.keywords.join(", "));

    const coverPath = resolve(root, offer.cover);
    await page.getByRole("button", { name: "Выбрать файл" }).first().click();
    const dialog = page.getByRole("dialog");
    await dialog.locator('input[type="file"]').setInputFiles(coverPath);
    await dialog.getByRole("button", { name: "Отправить" }).click();
    await page.getByRole("radio", { name: "Обложка" }).check();
    if (!submit) {
      offer.status = "prepared";
      continue;
    }
    await page.getByRole("checkbox", { name: "Я соглашаюсь с правилами публикации объявления" }).check();
    await page.getByRole("button", { name: "Создать" }).click();
    await page.waitForURL(/\/offer\/after-save\//, { timeout: 20000 });
    const publicHref = await page.getByRole("link", { name: offer.title, exact: true }).first().getAttribute("href");
    offer.status = "published";
    offer.publishedUrl = publicHref ? new URL(publicHref, page.url()).href : null;
    offer.publishedAt = new Date().toISOString();
  } catch (error) {
    offer.status = "failed";
    offer.error = error instanceof Error ? error.message : String(error);
  }
  await writeFile(queuePath, `${JSON.stringify(queue, null, 2)}\n`, "utf8");
}

await context.close();
await browser.close();
console.log(`Обработано услуг: ${targets.length}. Режим: ${submit ? "публикация" : "подготовка"}.`);
