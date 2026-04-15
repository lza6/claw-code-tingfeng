import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { mkdir, mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { existsSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { readTeamConfig, saveTeamConfig } from '../state.js';
import { shutdownTeam, startTeam, type TeamRuntime } from '../runtime.js';

async function initRepo(): Promise<string> {
  const cwd = await mkdtemp(join(tmpdir(), 'omx-shutdown-fallback-'));
  execFileSync('git', ['init'], { cwd, stdio: 'ignore' });
  execFileSync('git', ['config', 'user.email', 'test@example.com'], { cwd, stdio: 'ignore' });
  execFileSync('git', ['config', 'user.name', 'Test User'], { cwd, stdio: 'ignore' });
  await writeFile(join(cwd, 'README.md'), 'hello\n', 'utf-8');
  execFileSync('git', ['add', 'README.md'], { cwd, stdio: 'ignore' });
  execFileSync('git', ['commit', '-m', 'init'], { cwd, stdio: 'ignore' });
  return cwd;
}

function withoutTeamWorkerEnv<T>(fn: () => Promise<T>): Promise<T> {
  const prev = process.env.OMX_TEAM_WORKER;
  delete process.env.OMX_TEAM_WORKER;
  return fn().finally(() => {
    if (typeof prev === 'string') process.env.OMX_TEAM_WORKER = prev;
    else delete process.env.OMX_TEAM_WORKER;
  });
}

describe('shutdown fallback worktree reports', () => {
  it('shutdownTeam checkpoints dirty detached worker worktrees, merges them, and writes a report', async () => {
    const repo = await initRepo();
    const binDir = await mkdtemp(join(tmpdir(), 'omx-shutdown-fallback-bin-'));
    const fakeCodexPath = join(binDir, 'codex');
    await writeFile(
      fakeCodexPath,
      `#!/usr/bin/env node
process.stdin.resume();
setInterval(() => {}, 1000);
process.on('SIGTERM', () => process.exit(0));
`,
      { mode: 0o755 },
    );

    const prevPath = process.env.PATH;
    const prevTmux = process.env.TMUX;
    const prevLaunchMode = process.env.OMX_TEAM_WORKER_LAUNCH_MODE;
    const prevWorkerCli = process.env.OMX_TEAM_WORKER_CLI;

    process.env.PATH = `${binDir}:${prevPath ?? ''}`;
    delete process.env.TMUX;
    process.env.OMX_TEAM_WORKER_LAUNCH_MODE = 'prompt';
    process.env.OMX_TEAM_WORKER_CLI = 'codex';

    let runtime: TeamRuntime | null = null;
    let preservedWorktreePath: string | null = null;
    try {
      runtime = await withoutTeamWorkerEnv(() =>
        startTeam(
          'team-shutdown-fallback-report',
          'shutdown fallback merge report',
          'executor',
          1,
          [],
          repo,
          { worktreeMode: { enabled: true, detached: true, name: null } },
        ));

      const worktreePath = runtime.config.workers[0]?.worktree_path;
      assert.ok(worktreePath, 'worker worktree path should be present');
      preservedWorktreePath = worktreePath ?? null;
      await writeFile(join(worktreePath as string, 'worker-note.txt'), 'from worker\n', 'utf-8');

      const config = await readTeamConfig(runtime.teamName, repo);
      assert.ok(config, 'team config should be readable before shutdown');
      if (!config) throw new Error('missing config');
      config.workers[0].worktree_created = false;
      await saveTeamConfig(config, repo);

      await shutdownTeam(runtime.teamName, repo);
      runtime = null;

      assert.equal(await readFile(join(repo, 'worker-note.txt'), 'utf-8'), 'from worker\n');
      assert.ok(preservedWorktreePath, 'preserved worktree path should be captured');
      assert.equal(existsSync(preservedWorktreePath as string), true);

      const reportPath = join(preservedWorktreePath as string, '.omx', 'diff.md');
      assert.equal(existsSync(reportPath), true);
      const report = await readFile(reportPath, 'utf-8');
      assert.match(report, /merge_outcome: merged/);
      assert.doesNotMatch(report, /synthetic_commit: none/);
      assert.match(report, /worker-note\.txt/);
    } finally {
      if (runtime) {
        await shutdownTeam(runtime.teamName, repo, { force: true }).catch(() => {});
      }
      if (typeof prevPath === 'string') process.env.PATH = prevPath;
      else delete process.env.PATH;
      if (typeof prevTmux === 'string') process.env.TMUX = prevTmux;
      else delete process.env.TMUX;
      if (typeof prevLaunchMode === 'string') process.env.OMX_TEAM_WORKER_LAUNCH_MODE = prevLaunchMode;
      else delete process.env.OMX_TEAM_WORKER_LAUNCH_MODE;
      if (typeof prevWorkerCli === 'string') process.env.OMX_TEAM_WORKER_CLI = prevWorkerCli;
      else delete process.env.OMX_TEAM_WORKER_CLI;
      await rm(binDir, { recursive: true, force: true }).catch(() => {});
      if (preservedWorktreePath) {
        await rm(preservedWorktreePath, { recursive: true, force: true }).catch(() => {});
      }
      await rm(repo, { recursive: true, force: true });
    }
  });
});
