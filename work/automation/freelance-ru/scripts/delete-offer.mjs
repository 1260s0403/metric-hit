import { readFile, writeFile } from "node:fs/promises";
import { resolve } from "node:path";
import { chromium } from "playwright";
import { loadSessionState } from "./session-store.mjs";

const root = process.cwd();
const logPath = resolve(root, "outputs/publication-log.json");
const offerId = process.argv.find((arg) => arg.startsWith("--id="))?.split("=")[1];
const expectedTitle = "Комплексное SEO-продвижение сайта";

if (offerId !== "102063") throw new Error("Разрешено удалить только подтверждённый дубль №102063.");
if (!process.argv.includes("--owner-command")) {
  throw new Error("Удаление Freelance.ru разрешено только по прямой команде владельца: добавьте --owner-command.");
}

const browser = await chromium.launch({ channel: "chrome", headless: false });
const context = await browser.newContext({ storageState: await loadSessionState() });
const page = await context.newPage();

try {
  await page.goto(`https://freelance.ru/offer/kompleksnoe-seo-prodvizhenie-sajta-${offerId}.html`, { waitUntil: "domcontentloaded" });
  const title = await page.getByRole("heading", { level: 1 }).innerText();
  if (title.trim() !== expectedTitle) throw new Error(`Проверка цели не пройдена: «${title}».`);

  const deleteLink = page.getByRole("link", { name: /Удалить/ });
  const href = await deleteLink.getAttribute("href");
  if (href !== `/offer/delete/${offerId}`) throw new Error("Ссылка удаления не соответствует подтверждённому объявлению.");

  page.once("dialog", (dialog) => dialog.accept());
  await Promise.all([
    page.waitForURL((url) => !url.pathname.includes(`${offerId}.html`), { timeout: 15000 }),
    deleteLink.click()
  ]);

  const log = JSON.parse(await readFile(logPath, "utf8"));
  log.push({ at: new Date().toISOString(), event: "deleted_duplicate", offerId: "seo-starter", deletedUrl: `https://freelance.ru/offer/kompleksnoe-seo-prodvizhenie-sajta-${offerId}.html` });
  await writeFile(logPath, `${JSON.stringify(log, null, 2)}\n`, "utf8");
  console.log(`Дубль №${offerId} удалён.`);
} finally {
  await context.close();
  await browser.close();
}
