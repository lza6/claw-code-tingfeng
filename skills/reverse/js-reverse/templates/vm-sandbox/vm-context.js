'use strict';

/**
 * vm 沙箱隔离：以补环境对象为全局，创建真正阻断 Node 宿主泄露的 vm 上下文。
 *
 * 用法（在 install-env.js 或最终交付的 result/src/env/ 中）：
 *   const { createSandbox } = require('./vm-context');
 *   const sandbox = createSandbox(win, { timeout: 5000 });
 *   sandbox.run(targetCode);            // 在隔离上下文内执行目标 JS
 *
 * 设计要点：
 *   1. 用 vm.createContext 以补环境对象作为上下文全局，目标 JS 的全局作用域即补环境。
 *   2. 删除可能随 Node 版本注入的宿主全局（process/Buffer/require/module/fetch/...），
 *      即使某些 Node 版本向 vm 注入这些全局也会被显式清除。
 *   3. 在上下文内应用 NativeProtect（assets/env-patch-snippets/native-protect.js），
 *      覆盖目标 JS 自定义函数的 toString / Object.prototype.toString / structuredClone 保护。
 */

const vm = require('vm');

// NativeProtect：优先同目录的内联副本（交付物自包含，不依赖 skill 仓库），
// 其次回退到 skill 仓库路径（开发期在仓库内直接引用 assets/ 时也可用）。
let NativeProtect = null;
try {
  NativeProtect = require('./native-protect.js');
} catch (_) {
  try { NativeProtect = require('../../assets/env-patch-snippets/native-protect.js'); } catch (_) { NativeProtect = null; }
}

// 必须在 vm 上下文中删除 / 置 undefined 的宿主全局（阻断 Node 能力泄露）。
// 注意：navigator / performance / localStorage / sessionStorage / document 等是补环境桩，
// 必须保留，不能删除。只删 Node 宿主能力。
const HOST_GLOBALS = [
  'process', 'Buffer', 'require', 'module',
  '__dirname', '__filename', 'exports', 'import',
  'setTimeout', 'setInterval', 'setImmediate', 'queueMicrotask', 'clearTimeout', 'clearInterval',
  'fetch',
];

function createSandbox(globalObj, opts = {}) {
  if (!globalObj || typeof globalObj !== 'object') {
    throw new Error('createSandbox 需要一个对象作为上下文全局');
  }

  const context = vm.createContext(globalObj, { name: opts.name || 'js-reverse-sandbox' });

  // 防御性删除：部分 Node 版本会向 vm 上下文注入宿主全局
  for (const key of HOST_GLOBALS) {
    if (key in context) {
      try { delete context[key]; } catch (_) { /* 不可删则忽略 */ }
    }
  }

  // 在上下文内应用 NativeProtect（覆盖目标 JS 自定义函数）
  if (NativeProtect && typeof NativeProtect.getInstance === 'function') {
    NativeProtect.getInstance().applyToContext(context);
  }

  return {
    context,
    run(code, runOpts = {}) {
      return vm.runInContext(code, context, {
        timeout: runOpts.timeout || opts.timeout || 5000,
        filename: runOpts.filename || opts.filename || 'target.js',
      });
    },
  };
}

module.exports = { createSandbox, HOST_GLOBALS };
