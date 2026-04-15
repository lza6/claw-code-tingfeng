/**
 * Subprocess helper for notify-hook modules.
 */

import { spawn } from 'child_process';

export function runProcess(command: string, args: string[], timeoutMs = 3000): Promise<{ stdout: string; stderr: string; code: number | null }> {
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, { stdio: ['ignore', 'pipe', 'pipe'] });
    let stdout = '';
    let stderr = '';
    let finished = false;

    const timer = setTimeout(() => {
      if (finished) return;
      finished = true;
      child.kill('SIGTERM');
      reject(new Error(`timeout after ${timeoutMs}ms`));
    }, timeoutMs);

    child.stdout.on('data', (chunk: any) => {
      stdout += chunk.toString();
    });
    child.stderr.on('data', (chunk: any) => {
      stderr += chunk.toString();
    });
    child.on('error', (err: any) => {
      if (finished) return;
      finished = true;
      clearTimeout(timer);
      reject(err);
    });
    child.on('close', (code: any) => {
      if (finished) return;
      finished = true;
      clearTimeout(timer);
      if (code === 0) {
        resolve({ stdout, stderr, code });
      } else {
        reject(new Error(stderr.trim() || `${command} exited ${code}`));
      }
    });
  });
}
