import { execFile, spawn } from "node:child_process";
import { access, mkdir, readFile, rm, stat, writeFile } from "node:fs/promises";
import { constants } from "node:fs";
import { promisify } from "node:util";
import { join } from "node:path";

const execFileAsync = promisify(execFile);
export const sessionDirectory = "C:\\ProgramData\\MetricHit\\automation-secrets\\freelance-ru";
export const sessionPath = join(sessionDirectory, "freelance-session.dpapi");

const icacls = process.env.SystemRoot ? join(process.env.SystemRoot, "System32", "icacls.exe") : "icacls.exe";
const csc = process.env.SystemRoot
  ? join(process.env.SystemRoot, "Microsoft.NET", "Framework64", "v4.0.30319", "csc.exe")
  : "csc.exe";
const helperSourcePath = join(import.meta.dirname, "dpapi-helper.cs");
const helperPath = join(sessionDirectory, "dpapi-helper.exe");

async function currentIdentity() {
  const { stdout } = await execFileAsync("whoami", [], { windowsHide: true });
  const identity = stdout.trim();
  if (!identity) throw new Error("Unable to resolve the current Windows identity");
  return identity;
}

async function invokeIcacls(args) {
  return execFileAsync(icacls, args, { windowsHide: true });
}

export async function ensureSecureSessionDirectory() {
  await mkdir(sessionDirectory, { recursive: true });
  const identity = await currentIdentity();
  await invokeIcacls([sessionDirectory, "/reset"]);
  await invokeIcacls([sessionDirectory, "/inheritance:r"]);
  await invokeIcacls([
    sessionDirectory, "/grant:r",
    `${identity}:(OI)(CI)F`,
    "*S-1-5-18:(OI)(CI)F",
    "*S-1-5-32-544:(OI)(CI)F",
  ]);
  return verifySecureSessionDirectory();
}

export async function verifySecureSessionDirectory() {
  const [{ stdout }, verification] = await Promise.all([
    invokeIcacls([sessionDirectory]),
    invokeIcacls([sessionDirectory, "/verify"]),
  ]);
  const verificationOutput = `${verification.stdout}\n${verification.stderr}`;
  // icacls uses the Windows console code page and can emit its localized success
  // message on either stream. execFile rejects a non-zero exit, so a non-empty
  // combined successful response is the portable verification signal here.
  if (!verificationOutput.trim()) {
    throw new Error("icacls verification failed for the Freelance.ru session directory");
  }
  if (/\(I\)/.test(stdout)) throw new Error("ACL inheritance is enabled");
  const principals = stdout.split(/\r?\n/)
    .filter((line) => /\(F\)/.test(line))
    .map((line) => line.trim().replace(/^.*?\s{2,}/, "").replace(/:\(F\).*$/, ""));
  if (principals.length !== 3) throw new Error(`Unexpected full-control ACL entries: ${principals.join(", ")}`);
  return { protected: true, principals };
}

async function ensureDpapiHelper() {
  try {
    const [source, helper] = await Promise.all([stat(helperSourcePath), stat(helperPath)]);
    if (helper.mtimeMs >= source.mtimeMs) return;
  } catch {
    // Compile the reviewed P/Invoke helper into the already restricted session directory.
  }
  await execFileAsync(csc, ["/nologo", "/target:exe", `/out:${helperPath}`, helperSourcePath], { windowsHide: true });
}

async function dpapi(mode, base64) {
  await ensureDpapiHelper();
  return new Promise((resolve, reject) => {
    const child = spawn(helperPath, [mode], { windowsHide: true, stdio: ["pipe", "pipe", "pipe"] });
    let stdout = "";
    let stderr = "";
    child.stdout.setEncoding("utf8");
    child.stderr.setEncoding("utf8");
    child.stdout.on("data", (chunk) => { stdout += chunk; });
    child.stderr.on("data", (chunk) => { stderr += chunk; });
    child.once("error", reject);
    child.once("close", (code) => {
      if (code === 0) resolve(stdout.trim());
      else reject(new Error(`Native DPAPI helper failed (${code}): ${stderr.trim()}`));
    });
    child.stdin.end(`${base64.trim()}\n`);
  });
}

async function protect(plainText) {
  return dpapi("protect", Buffer.from(plainText, "utf8").toString("base64"));
}

async function unprotect(cipherText) {
  return Buffer.from(await dpapi("unprotect", cipherText), "base64").toString("utf8");
}

export async function saveSessionState(storageState) {
  await ensureSecureSessionDirectory();
  const serialized = JSON.stringify(storageState);
  await writeFile(sessionPath, `${await protect(serialized)}\n`, { encoding: "utf8", mode: 0o600 });
  return { path: sessionPath, ...(await verifySecureSessionDirectory()) };
}

export async function loadSessionState() {
  try { await access(sessionPath, constants.R_OK); } catch {
    throw new Error(`Нет авторизованной сессии Freelance.ru. Выполните re-auth по прямой команде владельца: ${sessionPath}`);
  }
  return JSON.parse(await unprotect(await readFile(sessionPath, "utf8")));
}

export async function selfTestSessionStore() {
  await ensureSecureSessionDirectory();
  const testPath = join(sessionDirectory, "dpapi-self-test.dpapi");
  const marker = { test: "dpapi-round-trip", at: "non-secret" };
  await writeFile(testPath, `${await protect(JSON.stringify(marker))}\n`, { encoding: "utf8", mode: 0o600 });
  const restored = JSON.parse(await unprotect(await readFile(testPath, "utf8")));
  await rm(testPath, { force: true });
  if (JSON.stringify(restored) !== JSON.stringify(marker)) throw new Error("DPAPI round-trip failed");
  return { roundTrip: true, path: sessionPath, ...(await verifySecureSessionDirectory()) };
}
