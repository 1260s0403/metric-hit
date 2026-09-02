import assert from 'node:assert/strict';
import { randomUUID } from 'node:crypto';
import { existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { spawnSync } from 'node:child_process';
import test from 'node:test';
import { fileURLToPath } from 'node:url';
import { DatabaseSync } from 'node:sqlite';
import { snapshotProjectStorages, verifyProjectStorages } from '../scripts/project-storage-snapshot.mjs';

const repositoryRoot = dirname(dirname(fileURLToPath(import.meta.url)));
const powershell = process.platform === 'win32' ? 'powershell.exe' : 'pwsh';
const scripts = [
  'backup-common.ps1',
  'backup-metrichit.ps1',
  'test-restore-metrichit.ps1',
  'install-backup-task.ps1',
];

function runPowerShell(source) {
  const result = spawnSync(powershell, ['-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command', source], {
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

test('PowerShell 5.1 preserves empty and single-item project inventory arrays', () => {
  const library = join(repositoryRoot, 'scripts', 'backup-common.ps1').replaceAll("'", "''");
  runPowerShell(`
    . '${library}'
    $empty = @(ConvertFrom-BackupJsonArray -Json '[]')
    if ($empty.Count -ne 0) { throw "Empty inventory became $($empty.Count) synthetic entries." }
    $single = @(ConvertFrom-BackupJsonArray -Json '[{"projectId":"10000000-0000-4000-a000-000000000001","storageFormat":1}]')
    if ($single.Count -ne 1 -or $single[0].projectId -cne '10000000-0000-4000-a000-000000000001' -or $single[0].storageFormat -ne 1) {
      throw 'Single-project inventory changed while parsing.'
    }
  `);
});

test('backup SHA-256 works without the Get-FileHash cmdlet', () => {
  const library = join(repositoryRoot, 'scripts', 'backup-common.ps1').replaceAll("'", "''");
  runPowerShell(`
    . '${library}'
    $testFile = Join-Path ([IO.Path]::GetTempPath()) ('MetricHitHash-' + [guid]::NewGuid().ToString('N'))
    try {
      [IO.File]::WriteAllText($testFile, 'abc', [Text.UTF8Encoding]::new($false))
      function Get-FileHash { throw 'Get-FileHash must not be called.' }
      $actual = Get-BackupSha256 -Path $testFile
      if ($actual -cne 'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad') {
        throw "Unexpected SHA-256: $actual"
      }
    } finally {
      Remove-Item -LiteralPath $testFile -Force -ErrorAction SilentlyContinue
    }
  `);
});

test('backup SHA-256 can read a live SQLite-style shared file', () => {
  const library = join(repositoryRoot, 'scripts', 'backup-common.ps1').replaceAll("'", "''");
  runPowerShell(`
    . '${library}'
    $testFile = Join-Path ([IO.Path]::GetTempPath()) ('MetricHitSharedHash-' + [guid]::NewGuid().ToString('N'))
    $writer = $null
    try {
      [IO.File]::WriteAllText($testFile, 'abc', [Text.UTF8Encoding]::new($false))
      $writer = [IO.FileStream]::new($testFile, [IO.FileMode]::Open, [IO.FileAccess]::ReadWrite, [IO.FileShare]::ReadWrite)
      $actual = Get-BackupSha256 -Path $testFile
      if ($actual -cne 'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad') {
        throw "Unexpected shared-file SHA-256: $actual"
      }
    } finally {
      if ($null -ne $writer) { $writer.Dispose() }
      Remove-Item -LiteralPath $testFile -Force -ErrorAction SilentlyContinue
    }
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
      $empty = Join-Path $testRoot 'empty.txt'
      $unsafe = Join-Path $testRoot 'neutral.txt'
      Set-Content -LiteralPath $safe -Value 'Documentation mentions passwords without storing one.'
      [IO.File]::WriteAllBytes($empty, [byte[]]@())
      $secretName = 'client_' + 'secret'
      Set-Content -LiteralPath $unsafe -Value ($secretName + ' = ' + 'abcdefghijklmnop')
      if (Test-BackupFileContainsSecret $safe) { throw 'Safe documentation was rejected.' }
      if (Test-BackupFileContainsSecret $empty) { throw 'Empty file was rejected.' }
      if (Test-BackupBytesOrArchiveContainSecret -Bytes ([byte[]]@()) -Label 'empty bytes') { throw 'Empty byte array was rejected.' }
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

test('Git batch secret scan covers reachable history, empty/binary blobs, and nested ZIPs', () => {
  const library = join(repositoryRoot, 'scripts', 'backup-common.ps1').replaceAll("'", "''");
  runPowerShell(`
    . '${library}'
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $testRoot = Join-Path ([IO.Path]::GetTempPath()) ('MetricHitGitBatch-' + [guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $testRoot | Out-Null
    try {
      & git -C $testRoot init -q
      & git -C $testRoot config user.email test@example.invalid
      & git -C $testRoot config user.name Test
      [IO.File]::WriteAllBytes((Join-Path $testRoot 'empty.bin'), [byte[]]@())
      [IO.File]::WriteAllBytes((Join-Path $testRoot 'binary.bin'), [byte[]](0,255,1,254,2,253))
      Set-Content -LiteralPath (Join-Path $testRoot 'safe.txt') -Value 'safe content'
      & git -C $testRoot add .
      & git -C $testRoot commit -qm safe
      $refs = @(& git -C $testRoot for-each-ref --format='%(objectname)')
      [object[]]$safeOutput = @(Assert-GitObjectsHaveNoSecretContent -RepositoryRoot $testRoot -RefObjectIds $refs -TemporaryDirectory (Join-Path $testRoot 'scan-safe'))
      if ($safeOutput.Length -ne 1) { throw "Expected exactly one scan result; got $($safeOutput.Length)" }
      $safeResult = $safeOutput[$safeOutput.Length - 1]
      if ($safeResult.blobCount -ne 3) { throw "Expected all three reachable blobs; got $($safeResult.blobCount)" }

      $secretName = 'client_' + 'secret'
      Set-Content -LiteralPath (Join-Path $testRoot 'historical.txt') -Value ($secretName + '=abcdefghijklmnop')
      & git -C $testRoot add historical.txt
      & git -C $testRoot commit -qm historical-secret
      Set-Content -LiteralPath (Join-Path $testRoot 'historical.txt') -Value 'clean replacement'
      & git -C $testRoot add historical.txt
      & git -C $testRoot commit -qm replacement
      $refs = @(& git -C $testRoot for-each-ref --format='%(objectname)')
      try {
        Assert-GitObjectsHaveNoSecretContent -RepositoryRoot $testRoot -RefObjectIds $refs -TemporaryDirectory (Join-Path $testRoot 'scan-history') | Out-Null
        throw 'Reachable historical secret was not detected.'
      } catch {
        if ($_.Exception.Message -eq 'Reachable historical secret was not detected.') { throw }
      }

      $zipRepo = Join-Path $testRoot 'zip-repo'
      New-Item -ItemType Directory -Path $zipRepo | Out-Null
      & git -C $zipRepo init -q
      & git -C $zipRepo config user.email test@example.invalid
      & git -C $zipRepo config user.name Test
      $innerDirectory = Join-Path $zipRepo 'inner-source'
      New-Item -ItemType Directory -Path $innerDirectory | Out-Null
      Set-Content -LiteralPath (Join-Path $innerDirectory 'neutral.txt') -Value ($secretName + '=abcdefghijklmnop')
      $innerZip = Join-Path $zipRepo 'inner.zip'
      [IO.Compression.ZipFile]::CreateFromDirectory($innerDirectory, $innerZip)
      $outerDirectory = Join-Path $zipRepo 'outer-source'
      New-Item -ItemType Directory -Path $outerDirectory | Out-Null
      Copy-Item -LiteralPath $innerZip -Destination (Join-Path $outerDirectory 'payload.zip')
      $outerZip = Join-Path $zipRepo 'nested.zip'
      [IO.Compression.ZipFile]::CreateFromDirectory($outerDirectory, $outerZip)
      & git -C $zipRepo add nested.zip
      & git -C $zipRepo commit -qm nested-zip-secret
      $refs = @(& git -C $zipRepo for-each-ref --format='%(objectname)')
      try {
        Assert-GitObjectsHaveNoSecretContent -RepositoryRoot $zipRepo -RefObjectIds $refs -TemporaryDirectory (Join-Path $testRoot 'scan-zip') | Out-Null
        throw 'Nested ZIP secret was not detected.'
      } catch {
        if ($_.Exception.Message -eq 'Nested ZIP secret was not detected.') { throw }
      }
    } finally {
      Remove-Item -LiteralPath $testRoot -Recurse -Force
    }
  `);
});

test('Git batch parser fails closed on truncated or malformed protocol', () => {
  const library = join(repositoryRoot, 'scripts', 'backup-common.ps1').replaceAll("'", "''");
  runPowerShell(`
    . '${library}'
    $truncated = [IO.MemoryStream]::new([Text.Encoding]::ASCII.GetBytes(('a' * 40) + ' blob 5' + [char]10 + 'xy'))
    try {
      $header = Read-GitBatchLine -Stream $truncated
      try { Read-GitBatchBytes -Stream $truncated -Length 5 | Out-Null; throw 'Truncated protocol was accepted.' }
      catch { if ($_.Exception.Message -eq 'Truncated protocol was accepted.') { throw } }
    } finally { $truncated.Dispose() }
    $missingSeparator = [IO.MemoryStream]::new([Text.Encoding]::ASCII.GetBytes('abcdeX'))
    try {
      try { Read-GitBatchBytes -Stream $missingSeparator -Length 5 | Out-Null; throw 'Malformed protocol was accepted.' }
      catch { if ($_.Exception.Message -eq 'Malformed protocol was accepted.') { throw } }
    } finally { $missingSeparator.Dispose() }
  `);
});

test('canonical ref bundle excludes linked-worktree pseudo-refs without losing branches', () => {
  const testRoot = join(tmpdir(), `MetricHitBundleRefs-${randomUUID()}`);
  const repository = join(testRoot, 'repository');
  const linkedWorktree = join(testRoot, 'linked-worktree');
  const bundle = join(testRoot, 'canonical.bundle');
  const clone = join(testRoot, 'clone');
  try {
    mkdirSync(repository, { recursive: true });
    const git = (...args) => spawnSync('git', ['-C', repository, ...args], { encoding: 'utf8' });
    assert.equal(git('init', '-q', '-b', 'main').status, 0);
    assert.equal(git('config', 'user.email', 'test@example.invalid').status, 0);
    assert.equal(git('config', 'user.name', 'Test').status, 0);
    writeFileSync(join(repository, 'tracked.txt'), 'main\n');
    assert.equal(git('add', 'tracked.txt').status, 0);
    assert.equal(git('commit', '-qm', 'main').status, 0);
    const worktreeResult = git('worktree', 'add', '-q', '-b', 'linked', linkedWorktree);
    assert.equal(worktreeResult.status, 0, worktreeResult.stderr || worktreeResult.stdout);

    const inventoryResult = git('for-each-ref', '--format=%(refname) %(objectname)');
    assert.equal(inventoryResult.status, 0, inventoryResult.stderr);
    const inventory = inventoryResult.stdout.trim().split(/\r?\n/).sort();
    const refNames = inventory.map((line) => line.split(/\s+/, 1)[0]);
    assert.deepEqual(refNames, ['refs/heads/linked', 'refs/heads/main']);

    const createResult = git('bundle', 'create', bundle, 'HEAD', ...refNames);
    assert.equal(createResult.status, 0, createResult.stderr || createResult.stdout);
    const headsResult = git('bundle', 'list-heads', bundle);
    assert.equal(headsResult.status, 0, headsResult.stderr);
    const bundleInventory = headsResult.stdout.trim().split(/\r?\n/).filter((line) => !line.endsWith(' HEAD')).map((line) => {
      const [objectName, refName] = line.split(/\s+/, 2);
      return `${refName} ${objectName}`;
    }).sort();
    assert.deepEqual(bundleInventory, inventory);
    const cloneResult = spawnSync('git', ['clone', '--no-local', bundle, clone], { encoding: 'utf8' });
    assert.equal(cloneResult.status, 0, cloneResult.stderr || cloneResult.stdout);
    const cloneHead = spawnSync('git', ['-C', clone, 'rev-parse', 'HEAD'], { encoding: 'utf8' });
    assert.equal(cloneHead.status, 0, cloneHead.stderr);
    assert.equal(cloneHead.stdout.trim(), inventory.find((line) => line.startsWith('refs/heads/main ')).split(/\s+/, 2)[1]);
  } finally {
    rmSync(testRoot, { recursive: true, force: true, maxRetries: 5, retryDelay: 50 });
  }
});

test('project storage snapshot supports zero and two isolated online SQLite backups', async () => {
  const testRoot = join(tmpdir(), `MetricHitProjectBackup-${randomUUID()}`);
  const source = join(testRoot, 'source');
  const emptyDestination = join(testRoot, 'empty-destination');
  const destination = join(testRoot, 'destination');
  const ids = ['10000000-0000-4000-a000-000000000001', '20000000-0000-4000-a000-000000000002'];
  try {
    assert.deepEqual(await snapshotProjectStorages(source, emptyDestination), []);
    assert.deepEqual(verifyProjectStorages(emptyDestination, []), []);
    for (const id of ids) {
      const directory = join(source, id);
      mkdirSync(directory, { recursive: true });
      const database = new DatabaseSync(join(directory, 'project.sqlite'));
      database.exec('CREATE TABLE project_storage_metadata(singleton INTEGER PRIMARY KEY, project_id TEXT, storage_format INTEGER);');
      database.prepare('INSERT INTO project_storage_metadata VALUES (1, ?, 1)').run(id);
      database.exec('CREATE TABLE payload(value TEXT); INSERT INTO payload VALUES (\'owned\');');
      database.close();
    }
    const inventory = await snapshotProjectStorages(source, destination);
    assert.deepEqual(inventory.map(({ projectId }) => projectId), ids);
    assert.deepEqual(verifyProjectStorages(destination, inventory), inventory);
    assert.ok(inventory.every(({ path, sha256, integrity }) => path.startsWith('data/projects/') && sha256.length === 64 && integrity === 'ok'));

    const inventoryPath = join(testRoot, 'inventory-with-bom.json');
    writeFileSync(inventoryPath, `\uFEFF${JSON.stringify(inventory)}`, 'utf8');
    const verifyResult = spawnSync(process.execPath, [join(repositoryRoot, 'scripts', 'project-storage-snapshot.mjs'), 'verify', destination, inventoryPath], { encoding: 'utf8' });
    assert.equal(verifyResult.status, 0, verifyResult.stderr || verifyResult.stdout);
    assert.deepEqual(JSON.parse(verifyResult.stdout), inventory);

    mkdirSync(join(source, '..-escape'), { recursive: true });
    await assert.rejects(snapshotProjectStorages(source, join(testRoot, 'rejected')), /Unexpected entry/);
  } finally {
    rmSync(testRoot, { recursive: true, force: true });
  }
});

test('project storage snapshot accepts only its SQLite WAL and SHM sidecars', async () => {
  const testRoot = join(tmpdir(), `MetricHitProjectBackupWal-${randomUUID()}`);
  const source = join(testRoot, 'source');
  const destination = join(testRoot, 'destination');
  const rejected = join(testRoot, 'rejected');
  const id = '30000000-0000-4000-a000-000000000003';
  const directory = join(source, id);
  const databasePath = join(directory, 'project.sqlite');
  let database;
  try {
    mkdirSync(directory, { recursive: true });
    database = new DatabaseSync(databasePath);
    database.exec('PRAGMA journal_mode=WAL;');
    database.exec('CREATE TABLE project_storage_metadata(singleton INTEGER PRIMARY KEY, project_id TEXT, storage_format INTEGER);');
    database.prepare('INSERT INTO project_storage_metadata VALUES (1, ?, 1)').run(id);
    database.exec('CREATE TABLE payload(value TEXT); INSERT INTO payload VALUES (\'owned\');');
    assert.equal(existsSync(`${databasePath}-wal`), true);
    assert.equal(existsSync(`${databasePath}-shm`), true);

    const inventory = await snapshotProjectStorages(source, destination);
    assert.deepEqual(verifyProjectStorages(destination, inventory), inventory);

    writeFileSync(join(directory, 'foreign.txt'), 'not a SQLite sidecar');
    await assert.rejects(snapshotProjectStorages(source, rejected), /invalid layout/);
  } finally {
    database?.close();
    rmSync(testRoot, { recursive: true, force: true });
  }
});

test('backup and restore scripts retain the required recovery contract', () => {
  const backup = readFileSync(join(repositoryRoot, 'scripts', 'backup-metrichit.ps1'), 'utf8');
  const restore = readFileSync(join(repositoryRoot, 'scripts', 'test-restore-metrichit.ps1'), 'utf8');
  const task = readFileSync(join(repositoryRoot, 'scripts', 'install-backup-task.ps1'), 'utf8');

  for (const marker of ['workspace.zip', 'git.bundle', 'manifest.json', "'work'", "'tests'", 'sqlite-backup.mjs', 'project-storage-snapshot.mjs', 'bundle create']) {
    assert.ok(backup.includes(marker), `backup contract marker missing: ${marker}`);
  }
  for (const marker of ['formatVersion = 4', 'centralDatabase', 'sourceSha256', 'Central SQLite source changed during online backup']) {
    assert.ok(backup.includes(marker), `exact-source backup marker missing: ${marker}`);
  }
  for (const marker of ['bundle verify', 'bundle list-heads', 'git clone', "Join-Path $repoRoot 'scripts\\check-memory.mjs'", 'project-storage-snapshot.mjs', 'requiredCommits', 'requiredWorkFiles', 'Assert-BackupInventoriesEqual', 'Assert-BackupTreeHasNoSecretContent']) {
    assert.ok(restore.includes(marker), `restore contract marker missing: ${marker}`);
  }
  for (const marker of ['centralDatabase', 'sourceSha256', 'Restored central database SHA-256 differs from the manifest']) {
    assert.ok(restore.includes(marker), `exact-source restore marker missing: ${marker}`);
  }
  assert.match(restore, /\[Text\.UTF8Encoding\]::new\(\$false\)/);
  assert.match(task, /New-ScheduledTaskTrigger -Daily -At 3:30AM/);
  assert.match(task, /LogonType S4U/);
  assert.match(task, /backup-metrichit\.ps1/);
  const common = readFileSync(join(repositoryRoot, 'scripts', 'backup-common.ps1'), 'utf8');
  const scanner = common.slice(common.indexOf('function Assert-GitObjectsHaveNoSecretContent'), common.indexOf('function Assert-BackupInventoriesEqual'));
  assert.equal(scanner.match(/Start-Process/g)?.length, 1);
  assert.doesNotMatch(scanner, /\$objectId\.blob/);
  assert.match(scanner, /['"]cat-file['"],\s*['"]--batch['"]/);
});
