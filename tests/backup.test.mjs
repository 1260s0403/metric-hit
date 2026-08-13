import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { spawnSync } from 'node:child_process';
import test from 'node:test';
import { fileURLToPath } from 'node:url';

const repositoryRoot = dirname(dirname(fileURLToPath(import.meta.url)));
const powershell = process.platform === 'win32' ? 'powershell.exe' : 'pwsh';
const scripts = [
  'backup-common.ps1',
  'backup-metrichit.ps1',
  'test-restore-metrichit.ps1',
  'install-backup-task.ps1',
];

function runPowerShell(source) {
  const result = spawnSync(powershell, ['-NoProfile', '-Command', source], {
    cwd: repositoryRoot,
    encoding: 'utf8',
  });
  assert.equal(result.status, 0, result.stderr || result.stdout);
  return result.stdout;
}

test('backup PowerShell scripts parse without syntax errors', () => {
  const paths = scripts.map((name) => join(repositoryRoot, 'scripts', name));
  const quotedPaths = paths.map((path) => `'${path.replaceAll("'", "''")}'`).join(',');
  runPowerShell(`
    $failed = $false
    foreach ($path in @(${quotedPaths})) {
      $tokens = $null
      $errors = $null
      [System.Management.Automation.Language.Parser]::ParseFile($path, [ref]$tokens, [ref]$errors) | Out-Null
      if ($errors.Count) { $failed = $true; $errors | ForEach-Object { Write-Error $_.Message } }
    }
    if ($failed) { exit 1 }
  `);
});

test('backup path policy blocks secrets and transient trees without blocking work materials', () => {
  const library = join(repositoryRoot, 'scripts', 'backup-common.ps1').replaceAll("'", "''");
  runPowerShell(`
    . '${library}'
    $blocked = @('.env', 'nested/.env.local', 'secrets/key.txt', '.codex/auth.json', 'logs/run.log', 'tmp/stage.bin', 'backups/old.zip', 'private.pem', 'api-token.txt')
    $allowed = @('work/landing/index.html', 'work/archive/migration-packages/2026-08-13/source.zip', 'backups/.gitkeep', 'logs/.gitkeep', '.gitignore', 'documents/backup-and-restore.md')
    foreach ($path in $blocked) { if (-not (Test-BackupPathProhibited $path)) { throw "Allowed prohibited path: $path" } }
    foreach ($path in $allowed) { if (Test-BackupPathProhibited $path) { throw "Blocked safe path: $path" } }
  `);
});

test('backup content policy detects representative secret formats', () => {
  const library = join(repositoryRoot, 'scripts', 'backup-common.ps1').replaceAll("'", "''");
  runPowerShell(`
    . '${library}'
    $testRoot = Join-Path ([IO.Path]::GetTempPath()) ('MetricHitSecretPolicy-' + [guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $testRoot | Out-Null
    try {
      $safe = Join-Path $testRoot 'safe.txt'
      $unsafe = Join-Path $testRoot 'neutral.txt'
      Set-Content -LiteralPath $safe -Value 'Documentation mentions passwords without storing one.'
      $secretName = 'client_' + 'secret'
      Set-Content -LiteralPath $unsafe -Value ($secretName + ' = ' + 'abcdefghijklmnop')
      if (Test-BackupFileContainsSecret $safe) { throw 'Safe documentation was rejected.' }
      if (-not (Test-BackupFileContainsSecret $unsafe)) { throw 'Representative secret was not detected.' }
    } finally {
      Remove-Item -LiteralPath $testRoot -Recurse -Force
    }
  `);
});

test('backup content policy scans quoted UTF-16 and large text values', () => {
  const library = join(repositoryRoot, 'scripts', 'backup-common.ps1').replaceAll("'", "''");
  runPowerShell(`
    . '${library}'
    $testRoot = Join-Path ([IO.Path]::GetTempPath()) ('MetricHitSecretEncoding-' + [guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $testRoot | Out-Null
    try {
      $name = 'pass' + 'word'
      $utf16 = Join-Path $testRoot 'utf16.txt'
      $large = Join-Path $testRoot 'large.txt'
      [IO.File]::WriteAllText($utf16, ($name + ' = "abcdefghijklmnop"'), [Text.Encoding]::Unicode)
      [IO.File]::WriteAllText($large, (('x' * 11000000) + [Environment]::NewLine + $name + '=abcdefghijklmnop'), [Text.Encoding]::UTF8)
      if (-not (Test-BackupFileContainsSecret $utf16)) { throw 'Quoted UTF-16 secret was not detected.' }
      if (-not (Test-BackupFileContainsSecret $large)) { throw 'Large-file secret was not detected.' }
    } finally {
      Remove-Item -LiteralPath $testRoot -Recurse -Force
    }
  `);
});

test('backup and restore scripts retain the required recovery contract', () => {
  const backup = readFileSync(join(repositoryRoot, 'scripts', 'backup-metrichit.ps1'), 'utf8');
  const restore = readFileSync(join(repositoryRoot, 'scripts', 'test-restore-metrichit.ps1'), 'utf8');
  const task = readFileSync(join(repositoryRoot, 'scripts', 'install-backup-task.ps1'), 'utf8');

  for (const marker of ['workspace.zip', 'git.bundle', 'manifest.json', "'work'", "'tests'", 'sqlite-backup.mjs', 'bundle create']) {
    assert.ok(backup.includes(marker), `backup contract marker missing: ${marker}`);
  }
  for (const marker of ['bundle verify', 'bundle list-heads', 'git clone', "Join-Path $repoRoot 'scripts\\check-memory.mjs'", 'requiredCommits', 'requiredWorkFiles', 'Assert-BackupInventoriesEqual', 'Assert-BackupTreeHasNoSecretContent']) {
    assert.ok(restore.includes(marker), `restore contract marker missing: ${marker}`);
  }
  assert.match(task, /New-ScheduledTaskTrigger -Daily -At 3:30AM/);
  assert.match(task, /LogonType S4U/);
  assert.match(task, /backup-metrichit\.ps1/);
});
