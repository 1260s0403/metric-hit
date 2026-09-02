import { execFileSync } from "node:child_process";
import { readFile } from "node:fs/promises";
import { resolve } from "node:path";

const root = process.cwd();
execFileSync(process.execPath, ["scripts/build-offer-queue.mjs"], { cwd: root, stdio: "inherit" });
const queue = JSON.parse(await readFile(resolve(root, "outputs/publish-queue.json"), "utf8"));
const seo = queue.find((item) => item.id === "seo-starter");
if (seo.status !== "published") throw new Error("Уже опубликованная услуга вернулась в очередь");
if (seo.publishedUrl !== "https://freelance.ru/offer/kompleksnoe-seo-prodvizhenie-sajta-102062.html") {
  throw new Error("Потеряна ссылка на уже опубликованную услугу");
}
console.log("Регрессия повторной публикации предотвращена.");
