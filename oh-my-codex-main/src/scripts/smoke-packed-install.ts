import {
  existsSync,
  lstatSync,
  mkdtempSync,
  rmSync,
  symlinkSync,
} from 'node:fs';
import { mkdirSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { basename, dirname, join, resolve } from 'node:path';
import { spawnSync } from 'node:child_process';
import { pathToFileURL } from 'node:url';

const REQUIRED_NODE_MODULE_MARKERS = [
  join('typescript', 'package.json'),
  join('@iarna', 'toml', 'package.json'),
  join('@modelcontextprotocol', 'sdk', 'package.json'),
  join('zod', 'package.json'),
];

export const PACKED_INSTALL_SMOKE_CORE_COMMANDS = [
  ['--help'],
  ['version'],
] as const;

function usage(): string {
  return [
    'Usage: node scripts/smoke-packed-install.mjs',
    '',
    'Creates an npm tarball, installs it into an isolated prefix, and smoke tests the installed omx CLI.',
    'Release smoke stays intentionally minimal: install + boot + 1-2 core commands only.',
  ].join('\n');
}

function hasNodeModulesPath(nodeModulesPath: string): boolean {
  try {
    lstatSync(nodeModulesPath);
    return true;
  } catch {
    return false;
  }
}

export function hasUsableNodeModules(repoRoot: string): boolean {
  return REQUIRED_NODE_MODULE_MARKERS.every((marker) => existsSync(join(repoRoot, 'node_modules', marker)));
}

export function resolveGitCommonDir(cwd: string, gitRunner = spawnSync): string | null {
  const result = gitRunner('git', ['rev-parse', '--git-common-dir'], {
    cwd,
    encoding: 'utf-8',
  });
  if (result.status !== 0) {
    return null;
  }
  const value = (result.stdout || '').trim();
  if (!value) {
    return null;
  }
  return resolve(cwd, value);
}

interface EnsureRepoDepsOptions {
  gitRunner?: typeof spawnSync;
  install?: (cwd: string) => void;
  remove?: typeof rmSync;
  symlink?: typeof symlinkSync;
  log?: (message: string) => void;
  platformName?: string;
}

interface EnsureRepoDepsResult {
  strategy: string;
  nodeModulesPath: string;
  sourceNodeModulesPath?: string;
}

export function resolveReusableNodeModulesSource(repoRoot: string, gitRunner = spawnSync): string | null {
  const commonDir = resolveGitCommonDir(repoRoot, gitRunner);
  if (!commonDir || basename(commonDir) !== '.git') {
    return null;
  }

  const primaryRepoRoot = dirname(commonDir);
  if (resolve(primaryRepoRoot) === resolve(repoRoot)) {
    return null;
  }

  if (!hasUsableNodeModules(primaryRepoRoot)) {
    return null;
  }

  return join(primaryRepoRoot, 'node_modules');
}

function formatCommandFailure(cmd: string, args: string[], result: { stdout?: string; stderr?: string }): string {
  return [
    `Command failed: ${cmd} ${args.join(' ')}`,
    result.stdout?.trim() ? `stdout:\n${result.stdout.trim()}` : '',
    result.stderr?.trim() ? `stderr:\n${result.stderr.trim()}` : '',
  ].filter(Boolean).join('\n\n');
}

export function ensureRepoDependencies(repoRoot: string, options: EnsureRepoDepsOptions = {}): EnsureRepoDepsResult {
  const {
    gitRunner = spawnSync,
    install = (cwd: string) => {
      const result = spawnSync('npm', ['ci'], {
        cwd,
        encoding: 'utf-8',
        stdio: 'pipe',
      });
      if (result.status !== 0) {
        throw new Error(formatCommandFailure('npm', ['ci'], result));
      }
    },
    remove = rmSync,
    symlink = symlinkSync,
    log = () => {},
    platformName = process.platform,
  } = options;

  if (hasUsableNodeModules(repoRoot)) {
    return {
      strategy: 'existing',
      nodeModulesPath: join(repoRoot, 'node_modules'),
    };
  }

  const targetNodeModules = join(repoRoot, 'node_modules');
  if (hasNodeModulesPath(targetNodeModules)) {
    remove(targetNodeModules, { recursive: true, force: true });
  }

  const reusableNodeModules = resolveReusableNodeModulesSource(repoRoot, gitRunner);
  if (reusableNodeModules) {
    symlink(reusableNodeModules, targetNodeModules, platformName === 'win32' ? 'junction' : 'dir');
    log(`[smoke:packed-install] Reusing node_modules from ${reusableNodeModules}`);
    return {
      strategy: 'symlink',
      nodeModulesPath: targetNodeModules,
      sourceNodeModulesPath: reusableNodeModules,
    };
  }

  log('[smoke:packed-install] Installing repo dependencies with npm ci');
  install(repoRoot);
  return {
    strategy: 'installed',
    nodeModulesPath: targetNodeModules,
  };
}

function parseArgs(argv: string[]): void {
  for (const token of argv) {
    if (token === '--help' || token === '-h') {
      console.log(usage());
      process.exit(0);
    }
    throw new Error(`Unknown argument: ${token}\n${usage()}`);
  }
}

function run(cmd: string, args: readonly string[], options: Record<string, unknown> = {}): ReturnType<typeof spawnSync> {
  const result = spawnSync(cmd, [...args], {
    encoding: 'utf-8',
    stdio: 'pipe',
    ...options,
  });
  if (result.status !== 0) {
    throw new Error(formatCommandFailure(cmd, [...args], result));
  }
  return result;
}

function npmBinName(name: string): string {
  return process.platform === 'win32' ? `${name}.cmd` : name;
}

async function main(): Promise<void> {
  parseArgs(process.argv.slice(2));

  const repoRoot = process.cwd();
  const tempRoot = mkdtempSync(join(tmpdir(), 'omx-packed-install-'));
  const prefixDir = join(tempRoot, 'prefix');
  mkdirSync(prefixDir, { recursive: true });

  let tarballPath: string | undefined;
  try {
    ensureRepoDependencies(repoRoot, {
      log: (message: string) => console.log(message),
    });

    const pack = run('npm', ['pack', '--json'], { cwd: repoRoot });
    const packOutput = JSON.parse((pack.stdout as string).slice((pack.stdout as string).indexOf('['))) as Array<{ filename: string }>;
    const tarballName = packOutput[0]?.filename;
    if (!tarballName) throw new Error('npm pack did not return a tarball filename');
    tarballPath = join(repoRoot, tarballName);

    run('npm', ['install', '-g', tarballPath, '--prefix', prefixDir], { cwd: repoRoot });

    const omxPath = join(prefixDir, process.platform === 'win32' ? '' : 'bin', npmBinName('omx'));
    for (const argv of PACKED_INSTALL_SMOKE_CORE_COMMANDS) {
      run(omxPath, argv, { cwd: repoRoot });
    }

    console.log('packed install smoke: PASS');
  } finally {
    if (tarballPath) rmSync(tarballPath, { force: true });
    rmSync(tempRoot, { recursive: true, force: true });
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  main().catch((error) => {
    console.error(`packed install smoke: FAIL\n${error instanceof Error ? error.message : String(error)}`);
    process.exit(1);
  });
}
