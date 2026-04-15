import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import type { GuidanceSurfaceContract } from '../prompt-guidance-contract.js';

const __dirname = dirname(fileURLToPath(import.meta.url));
const repoRoot = join(__dirname, '../../../');

export function loadSurface(path: string): string {
  return readFileSync(join(repoRoot, path), 'utf-8');
}

export function assertContractSurface(contract: GuidanceSurfaceContract): void {
  const content = loadSurface(contract.path);
  for (const pattern of contract.requiredPatterns) {
    assert.match(content, pattern, `${contract.id} missing required pattern: ${pattern}`);
  }
}
