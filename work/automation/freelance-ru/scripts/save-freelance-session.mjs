import { chromium } from "playwright";
import { saveSessionState } from "./session-store.mjs";

if (!process.argv.includes("--owner-command")) {
  throw new Error("Повторная авторизация разрешена только по прямой команде владельца: добавьте --owner-command.");
}
const browser = await chromium.launch({ channel: "chrome", headless: false });
const context = await browser.newContext();
const page = await context.newPage();
await page.goto("https://freelance.ru/offer/create");
console.log("Войдите в Freelance.ru в открывшемся окне, затем нажмите Enter здесь.");
process.stdin.resume();
await new Promise((resolveInput) => process.stdin.once("data", resolveInput));
const saved = await saveSessionState(await context.storageState());
await browser.close();
console.log(`Сессия зашифрована DPAPI: ${saved.path}`);
