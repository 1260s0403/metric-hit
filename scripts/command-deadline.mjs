import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';

export function runWithDeadline(seconds, command, args) {
  if (!Number.isFinite(seconds) || seconds <= 0 || !command) throw new Error('Usage: command-deadline <seconds> -- <command> [args...]');
  const child = spawn(command, args, { stdio: 'inherit', shell: false });
  let timedOut = false;
  const timer = setTimeout(() => { timedOut = true; child.kill(); }, seconds * 1000);
  child.once('exit', (code, signal) => { clearTimeout(timer); process.exitCode = timedOut || signal ? 124 : (code ?? 1); });
  child.once('error', (error) => { clearTimeout(timer); console.error(error.message); process.exitCode = 1; });
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  if (process.argv[3] !== '--') throw new Error('Usage: command-deadline <seconds> -- <command> [args...]');
  runWithDeadline(Number(process.argv[2]), process.argv[4], process.argv.slice(5));
}
