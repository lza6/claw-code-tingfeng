import { safeString } from './utils.js';
import { runProcess } from './process-runner.js';
import {
  buildCapturePaneArgv,
  buildPaneInModeArgv,
  buildPaneCurrentCommandArgv,
  buildSendKeysArgv,
  isPaneRunningShell,
  paneHasActiveTask,
  paneLooksReady,
  resolveCodexPane,
} from '../tmux-hook-engine.js';

export function mapPaneInjectionReadinessReason(reason: any): any {
  return reason === 'pane_running_shell' ? 'agent_not_running' : reason;
}

export async function evaluatePaneInjectionReadiness(paneTarget: any, {
  skipIfScrolling = false,
  captureLines = 80,
  requireRunningAgent = true,
  requireReady = true,
  requireIdle = true,
} = {}): Promise<any> {
  const target = safeString(paneTarget).trim();
  if (!target) {
    return {
      ok: false,
      sent: false,
      reason: 'missing_pane_target',
      paneTarget: '',
      paneCurrentCommand: '',
      paneCapture: '',
    };
  }

  // Canonical bypass: if resolveCodexPane confirms this is a codex pane
  // (via pane_start_command), skip all readiness guards. The pane IS running
  // codex even though tmux may report cmd=sh (shell wrapper).
  try {
    if (resolveCodexPane() === target) {
      return {
        ok: true,
        sent: false,
        reason: 'ok',
        paneTarget: target,
        paneCurrentCommand: 'codex',
        paneCapture: '',
      };
    }
  } catch {
    // Non-fatal: fall through to normal readiness checks
  }

  if (skipIfScrolling) {
    try {
      const modeResult = await runProcess('tmux', buildPaneInModeArgv(target), 1000);
      if (safeString(modeResult.stdout).trim() === '1') {
        return {
          ok: false,
          sent: false,
          reason: 'scroll_active',
          paneTarget: target,
          paneCurrentCommand: '',
          paneCapture: '',
        };
      }
    } catch {
      // Non-fatal: continue with remaining preflight checks.
    }
  }

  let paneCurrentCommand = '';
  let paneRunningShell = false;
  try {
    const result = await runProcess('tmux', buildPaneCurrentCommandArgv(target), 1000);
    paneCurrentCommand = safeString(result.stdout).trim();
    paneRunningShell = requireRunningAgent && isPaneRunningShell(paneCurrentCommand);
  } catch {
    paneCurrentCommand = '';
  }

  try {
    const capture = await runProcess('tmux', buildCapturePaneArgv(target, captureLines), 1000);
    const paneCapture = safeString(capture.stdout);
    if (paneCapture.trim() !== '') {
      const paneShowsLiveAgent = paneLooksReady(paneCapture) || paneHasActiveTask(paneCapture);
      if (paneRunningShell && !paneShowsLiveAgent) {
        return {
          ok: false,
          sent: false,
          reason: 'pane_running_shell',
          paneTarget: target,
          paneCurrentCommand,
          paneCapture,
        };
      }
      if (requireIdle && paneHasActiveTask(paneCapture)) {
        return {
          ok: false,
          sent: false,
          reason: 'pane_has_active_task',
          paneTarget: target,
          paneCurrentCommand,
          paneCapture,
        };
      }
      if (requireReady && !paneLooksReady(paneCapture)) {
        return {
          ok: false,
          sent: false,
          reason: 'pane_not_ready',
          paneTarget: target,
          paneCurrentCommand,
          paneCapture,
        };
      }
    }
    if (paneRunningShell && paneCapture.trim() === '') {
      return {
        ok: false,
        sent: false,
        reason: 'pane_running_shell',
        paneTarget: target,
        paneCurrentCommand,
        paneCapture,
      };
    }
    return {
      ok: true,
      sent: false,
      reason: 'ok',
      paneTarget: target,
      paneCurrentCommand,
      paneCapture,
    };
  } catch {
    if (paneRunningShell) {
      return {
        ok: false,
        sent: false,
        reason: 'pane_running_shell',
        paneTarget: target,
        paneCurrentCommand,
        paneCapture: '',
      };
    }
    return {
      ok: true,
      sent: false,
      reason: 'ok',
      paneTarget: target,
      paneCurrentCommand,
      paneCapture: '',
    };
  }
}

export async function sendPaneInput({
  paneTarget,
  prompt,
  submitKeyPresses = 2,
  submitDelayMs = 0,
  typePrompt = true,
}: any): Promise<any> {
  const target = safeString(paneTarget).trim();
  if (!target) {
    return { ok: false, sent: false, reason: 'missing_pane_target', paneTarget: '' };
  }

  const normalizedSubmitKeyPresses = Number.isFinite(submitKeyPresses)
    ? Math.max(0, Math.floor(submitKeyPresses))
    : 2;
  const literalPrompt = safeString(prompt);
  const argv = normalizedSubmitKeyPresses === 0
    ? {
      typeArgv: ['send-keys', '-t', target, '-l', literalPrompt],
      submitArgv: [] as string[][],
    }
    : buildSendKeysArgv({
      paneTarget: target,
      prompt: literalPrompt,
      dryRun: false,
      submitKeyPresses: normalizedSubmitKeyPresses,
    });
  if (!argv) {
    return { ok: false, sent: false, reason: 'send_failed', paneTarget: target };
  }

  try {
    if (typePrompt) {
      await runProcess('tmux', argv.typeArgv, 3000);
    }
    for (const submit of argv.submitArgv) {
      if (submitDelayMs > 0) {
        await new Promise((resolve) => setTimeout(resolve, submitDelayMs));
      }
      await runProcess('tmux', submit, 3000);
    }
    return { ok: true, sent: true, reason: 'sent', paneTarget: target, argv };
  } catch (error) {
    return {
      ok: false,
      sent: false,
      reason: 'send_failed',
      paneTarget: target,
      argv,
      error: error instanceof Error ? error.message : safeString(error),
    };
  }
}

export async function checkPaneReadyForTeamSendKeys(paneTarget: any): Promise<any> {
  return evaluatePaneInjectionReadiness(paneTarget);
}
