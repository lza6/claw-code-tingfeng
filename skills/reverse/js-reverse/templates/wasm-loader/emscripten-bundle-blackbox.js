/**
 * 整包 Emscripten bundle 黑盒执行 harness 模板
 *
 * 适用场景（env-wasm-advanced.md「整包 Emscripten bundle 黑盒执行」）：
 *   - 目标不是「干净 .wasm + 明确导出函数」，而是压缩 webpack bundle 内嵌 WASM base64
 *     + 异步 Emscripten glue + 内部 fetch（典型：风控 / 验证码握手 SDK，如 handshake 类接口）。
 *   - 确认加密逻辑落在 WASM 后，先整包黑盒执行，禁止先反编译 WASM / 逐字节解析 body。
 *
 * 设计要点：
 *   1. Node vm 加载原版 bundle（不格式化、不反混淆）
 *   2. sandbox 按需 mock window/document/navigator/第三方 SDK/fetch
 *   3. hook 内部 fetch 抓 body，与取证样本逐字段比对
 *   4. 跨 realm instanceof 失效已内置规避（宿主 WebAssembly + TypeError/Error/RangeError 一致注入）；
 *      Asyncify ccall 不触发等运行时坑按文末检查清单处理
 *
 * 使用方式：
 *   node emscripten-bundle-blackbox.js --bundle case/js/original/app.min.js \
 *     --sample case/forensic/target-hits.json --markdown
 *   （--sample 为取证抓到的真实请求体样本，用于比对结构一致性）
 *
 * 注意：
 *   - 交付时把 mock 裁剪到 trace 证明必需的最小集合，保留本次 fetch hook 抓到的 body 契约。
 *   - Node v24 下 WebAssembly.Table 的 funcref/anyfunc 不兼容：表由 bundle 内 glue 自建时
 *     不要手动 new WebAssembly.Table 传给 imports，按 imports() 声明给足即可。
 */

'use strict';

const fs = require('fs');
const path = require('path');
const vm = require('vm');

// ============================================================
// 参数解析
// ============================================================
function parseArgs(argv) {
  const args = { bundle: '', sample: '', markdown: false, json: false, help: false };
  for (let i = 2; i < argv.length; i++) {
    const a = argv[i];
    const next = () => (i + 1 < argv.length && !argv[i + 1].startsWith('-')) ? argv[++i] : '';
    if (a === '--bundle') args.bundle = next();
    else if (a === '--sample') args.sample = next();
    else if (a === '--markdown') args.markdown = true;
    else if (a === '--json') args.json = true;
    else if (a === '--help' || a === '-h') args.help = true;
    else throw new Error(`未知参数：${a}`);
  }
  if (!args.json && !args.markdown) args.markdown = true;
  return args;
}

function usage() {
  return `用法：
  node emscripten-bundle-blackbox.js --bundle case/js/original/app.min.js --sample case/forensic/target-hits.json --markdown`;
}

// ============================================================
// 默认 sandbox：按需 mock 的最少集合
// ============================================================
function bodyToHexOrString(body) {
  if (body == null) return null;
  if (typeof body === 'string') return body;
  // 二进制 body 通常是跨 vm realm 的 TypedArray，不能用 instanceof 判断；
  // 用 ArrayBuffer.isView 兜住 Uint8Array / DataView 等，转成宿主 Uint8Array 再 hex 化。
  if (ArrayBuffer.isView(body)) {
    const bytes = Uint8Array.from(body);
    return Buffer.from(bytes).toString('hex');
  }
  if (typeof body.text === 'function') return String(body);
  try { return JSON.stringify(body); } catch (e) { return String(body); }
}

function buildSandbox({ onFetch = () => {}, log = () => {} } = {}) {
  // 记录内部 fetch 调用点：URL / body / headers，与取证样本比对。
  // body 统一走 bodyToHexOrString：二进制 Uint8Array 转 hex，字符串原样，避免 JSON.stringify
  // 把二进制 body 变成 {"0":3,"1":4,...} 而丢失真实字节。
  const sandboxFetch = (url, init = {}) => {
    const body = bodyToHexOrString(init.body);
    onFetch({ url: String(url), method: (init.method || 'GET').toUpperCase(), body, headers: init.headers || {} });
    // mock Response：让 glue 内部请求走通（ok/json/text 都要有）
    return Promise.resolve({
      ok: true,
      status: 200,
      json: () => Promise.resolve({}),
      text: () => Promise.resolve(''),
      arrayBuffer: () => Promise.resolve(new ArrayBuffer(0)),
      headers: new Map(),
    });
  };

  // 第三方验证码 SDK mock：按回调生命周期补齐（onVerify / onStatusChange / R.show()）
  const CaptchaSDK = {
    init: () => Promise.resolve(),
    show: () => null,
    render: () => ({}),
    onVerify: null,
    onStatusChange: null,
    verify: (payload) => {
      if (CaptchaSDK.onVerify) CaptchaSDK.onVerify({ ticket: 'mock-ticket', result: true });
      return Promise.resolve({ ticket: 'mock-ticket', result: true });
    },
  };

  // window / self / top / parent 用同一个自引用对象，避免 webpack bundle 里的
  // window.document / window.navigator / window.location / window.addEventListener 为 undefined。
  const document = {
    currentScript: null, // webpack 有时读它定位 chunk
    createElement: () => ({ getContext: () => null, style: {}, setAttribute() {}, appendChild() {} }),
    getElementById: () => null,
    querySelector: () => null,
    querySelectorAll: () => [],
    addEventListener() {},
    removeEventListener() {},
    documentElement: { style: {} },
    body: { appendChild() {} },
    readyState: 'complete',
  };
  const navigator = { userAgent: 'Mozilla/5.0', platform: 'Win32', language: 'zh-CN' };
  const location = { href: '', protocol: 'https:', host: '', hostname: '', pathname: '/', search: '', hash: '' };
  const crypto = { getRandomValues: (arr) => { for (let i = 0; i < arr.length; i++) arr[i] = Math.floor(Math.random() * 256); return arr; } };
  const performance = { now: () => Date.now() };

  const window = {
    document,
    navigator,
    location,
    crypto,
    performance,
    addEventListener() {},
    removeEventListener() {},
    dispatchEvent: () => false,
    atob: (s) => Buffer.from(String(s), 'base64').toString('latin1'),
    btoa: (s) => Buffer.from(String(s), 'latin1').toString('base64'),
  };
  window.window = window;
  window.self = window;
  window.top = window;
  window.parent = window;

  const sandbox = {
    window,
    self: window,
    top: window,
    parent: window,
    document,
    navigator,
    location,
    crypto,
    performance,
    atob: window.atob,
    btoa: window.btoa,
    fetch: sandboxFetch,
    XMLHttpRequest: function () {
      const inst = { open() {}, send() {}, setRequestHeader() {}, readyState: 4, status: 200, responseText: '' };
      return inst;
    },
    // 跨 realm 一致性：注入宿主 WebAssembly 的同时，把 TypeError/Error/RangeError 也注入为
    // 宿主 intrinsics。Emscripten glue 的 addFunction 用 `g instanceof TypeError` 捕获宿主
    // WebAssembly.Table.set 抛出的错误；若这里漏掉 TypeError（或让 vm 用自己的 TypeError），
    // 这个判定会失败，表写入报错。
    WebAssembly,
    TypeError: globalThis.TypeError,
    Error: globalThis.Error,
    RangeError: globalThis.RangeError,
    console: { log, error: log, warn: log, info: log, debug: log },
    setTimeout,
    clearTimeout,
    setInterval: () => 0,
    clearInterval: () => {},
    queueMicrotask,
    URL,
    URLSearchParams,
    TextEncoder,
    TextDecoder,
    CaptchaSDK,
    // 可选：按 WebAssembly.Module.imports() 读到的依赖继续补全
  };
  sandbox.globalThis = sandbox;
  return sandbox;
}

// ============================================================
// 黑盒执行
// ============================================================
function runBundle(bundlePath, sandbox) {
  const code = fs.readFileSync(bundlePath, 'utf8');
  const ctx = vm.createContext(sandbox);
  vm.runInContext(code, ctx, { filename: path.basename(bundlePath) });
  return ctx;
}

// ============================================================
// 结构比对：blackbox 抓到的 body vs 取证样本
// ============================================================
function compareBody(actualBody, sampleBody) {
  const a = bodyToHexOrString(actualBody) || '';
  const s = bodyToHexOrString(sampleBody) || '';
  return {
    byteEqual: a === s,
    actualLen: a.length,
    sampleLen: s.length,
    actualPrefix: a.slice(0, 120),
    samplePrefix: s.slice(0, 120),
  };
}

// ============================================================
// 主流程
// ============================================================
function main() {
  const args = parseArgs(process.argv);
  if (args.help || !args.bundle) {
    console.log(usage());
    process.exit(args.help ? 0 : 1);
  }

  const calls = [];
  const sandbox = buildSandbox({
    onFetch: (c) => calls.push(c),
    log: (msg) => { if (args.markdown) process.stderr.write(`[bundle] ${msg}\n`); },
  });

  const ctx = runBundle(args.bundle, sandbox);
  const captured = calls.length ? calls : (ctx.__lastFetchCalls || []);

  const lines = ['# 整包 Emscripten bundle 黑盒执行结果', ''];
  lines.push(`- bundle：${args.bundle}`);
  lines.push(`- 内部 fetch 调用数：${captured.length}`);
  lines.push(`- 顶层导出：${Object.keys(ctx).filter((k) => typeof ctx[k] === 'function').slice(0, 10).join('、') || '无（加密在 glue 内部回调中触发）'}`);
  lines.push('');

  if (!captured.length) {
    lines.push('⚠️ 未捕获内部 fetch。检查：');
    lines.push('1. sandbox.fetch 是否被 bundle 闭包捕获到（必要时在 bundle 加载前改写全局）；');
    lines.push('2. 是否需要在 sandbox 里主动触发初始化（如调导出函数 / 等 onRuntimeInitialized）；');
    lines.push('3. Asyncify 下 ccall 不触发时，hook 回调 / CI.currData 取中间值。');
  }

  for (let i = 0; i < captured.length; i++) {
    const c = captured[i];
    lines.push(`## 调用 ${i + 1}：${c.method} ${c.url}`);
    lines.push('```');
    lines.push((c.body || '').slice(0, 1000));
    lines.push('```');
    if (args.sample) {
      let sampleBody = null;
      try { sampleBody = JSON.parse(fs.readFileSync(args.sample, 'utf8')); } catch (e) { sampleBody = fs.readFileSync(args.sample, 'utf8'); }
      const target = Array.isArray(sampleBody) ? sampleBody.find((r) => String(r.url || '').includes(c.url) || (r.method || '').toUpperCase() === c.method) : sampleBody;
      const sampleText = target ? (typeof target.request_body === 'string' ? target.request_body : JSON.stringify(target.request_body)) : null;
      if (sampleText != null) {
        const cmp = compareBody(c.body, sampleText);
        lines.push(`- 字节一致：${cmp.byteEqual ? '是' : '否'}（黑盒 ${cmp.actualLen} 字节 vs 样本 ${cmp.sampleLen} 字节）`);
        lines.push(`- 黑盒前缀：${cmp.actualPrefix}`);
        lines.push(`- 样本前缀：${cmp.samplePrefix}`);
        lines.push(`- 说明：随机化加密体（nonce/密钥/签名每次不同）字节必然不同，应以「长度、前缀、字段结构」比对，勿以整串相等判断；样本请求体若为 base64，需先解码再比对。`);
      }
    }
    lines.push('');
  }

  const out = lines.join('\n');
  if (args.json) console.log(JSON.stringify({ ok: true, calls: captured }, null, 2));
  else process.stdout.write(out + '\n');
}

try { main(); } catch (err) {
  console.error(err.stack || err.message || String(err));
  console.error(usage());
  process.exit(1);
}
