/**
 * 补环境安装模板（JS 层 NativeProtect 保护）
 *
 * 设计原则：
 *   1. NativeProtect：使用 JS 级 toString/descriptor/原型链保护覆盖检测
 *   2. Node 泄露阻断：process/Buffer/require/module/global 必须为 undefined
 *   3. fixture 回放：指纹 API（Canvas/WebGL/Audio）值从 fixture 回放，不调用真实算法
 *
 * 使用方式：
 *   const { installEnv } = require('./env/install-env');
 *   const env = installEnv({
 *     fixtures: require('./env/fixtures'),
 *     userAgent: 'Mozilla/5.0 ...',
 *     cookie: 'name=value; ...',
 *   });
 *   // 在 vm 中使用 env.global
 */

/**
 * ⚠️ 限制说明:
 * 本模板是"快速验证用"的简化版补环境,使用普通对象字面量。
 * 正式交付时,门禁要求(check_code_quality.js / check_fingerprint_fixture.js / check_final_artifact.js):
 *   - NativeProtect 保护证据
 *   - 原型链和构造函数
 *   - document.all 的 HTMLDDA 近似处理
 * 正式交付时需完善原型链和构造函数（参考 references/env/env-native-protection.md 保护策略）
 *
 * ⚠️ 本模板使用简化版 NativeProtect，不包含 DataCloneError / Object.prototype.toString /
 * structuredClone / MessagePort.postMessage 保护。正式交付必须替换为
 * `assets/env-patch-snippets/native-protect.js` 规范版（require 后用
 * `NativeProtect.getInstance().setNativeFunc(fn, name)` / `setObjFunc(obj, name)` API）。
 * 详见 references/env/env-native-protection.md。
 */

'use strict';

const { createSandbox } = require('./vm-context');
const { webcrypto } = require('crypto');

// ============================================================
// NativeProtect（JS 级 toString/descriptor 保护）
// ============================================================
const NativeProtect = {
  /**
   * 伪装 native function toString
   */
  nativeFunction(fn, name = '') {
    const wrapped = function (...args) { return fn.apply(this, args); };
    Object.defineProperty(wrapped, 'name', { value: name || fn.name, configurable: true });
    Object.defineProperty(wrapped, 'toString', {
      value: () => `function ${name || fn.name}() { [native code] }`,
      configurable: true, writable: true,
    });
    Object.defineProperty(wrapped.toString, 'toString', {
      value: () => 'function toString() { [native code] }',
    });
    return wrapped;
  },

  /**
   * 伪装 getter（descriptor 保护）
   */
  nativeGetter(getter) {
    return { get: this.nativeFunction(getter, 'get'), configurable: true, enumerable: true };
  },

  /**
   * 伪装 setter
   */
  nativeSetter(setter) {
    return { set: this.nativeFunction(setter, 'set'), configurable: true, enumerable: true };
  },

  /**
   * 创建类似原生对象（带原型链）
   */
  nativeObject(protoName, props = {}) {
    const proto = Object.create(null);
    Object.defineProperty(proto, Symbol.toStringTag, { value: protoName, configurable: true });
    const obj = Object.create(proto);
    for (const [k, v] of Object.entries(props)) {
      Object.defineProperty(obj, k, { value: v, writable: true, configurable: true, enumerable: true });
    }
    return obj;
  },
};

// ============================================================
// 补环境子模块：各 API 独立安装函数
// ============================================================

/**
 * 安装 navigator
 */
function installNavigator(protect, fixtures, userAgent, language, platform) {
  const navigator = {};
  const navProps = {
    userAgent,
    appVersion: userAgent.replace('Mozilla/', ''),
    appName: 'Netscape',
    appCodeName: 'Mozilla',
    platform,
    language,
    languages: [language, 'zh', 'en'],
    vendor: 'Google Inc.',
    vendorSub: '',
    productSub: '20030107',
    hardwareConcurrency: 8,
    deviceMemory: 8,
    maxTouchPoints: 0,
    onLine: true,
    cookieEnabled: true,
    webdriver: false,
    pdfViewerEnabled: true,
    doNotTrack: null,
  };

  for (const [k, v] of Object.entries(navProps)) {
    Object.defineProperty(navigator, k, NativeProtect.nativeGetter(() => v));
  }

  // navigator.plugins / mimeTypes
  if (fixtures.plugins) {
    Object.defineProperty(navigator, 'plugins', NativeProtect.nativeGetter(() => fixtures.plugins.plugins));
    Object.defineProperty(navigator, 'mimeTypes', NativeProtect.nativeGetter(() => fixtures.plugins.mimeTypes));
  }

  return navigator;
}

/**
 * 安装 document
 */
function installDocument(protect, fixtures, cookie) {
  let cookieStore = cookie;
  const document = {
    createElement: protect.nativeFunction((tag) => createFakeElement(tag, protect, fixtures), 'createElement'),
    getElementById: protect.nativeFunction(() => null, 'getElementById'),
    querySelector: protect.nativeFunction(() => null, 'querySelector'),
    querySelectorAll: protect.nativeFunction(() => [], 'querySelectorAll'),
    addEventListener: protect.nativeFunction(() => {}, 'addEventListener'),
    removeEventListener: protect.nativeFunction(() => {}, 'removeEventListener'),
    readyState: 'complete',
    characterSet: 'UTF-8',
    contentType: 'text/html',
    location: null,  // 后续由 installLocation 填充
    referrer: '',
    title: '',
    domain: '',
    URL: '',
  };

  // document.all（JS 层只能近似：typeof document.all 返回 'undefined' 但 document.all === undefined 仍为 true，
  // 真实浏览器为 false；如需精确 HTMLDDA 行为需用 sdenv，参考 references/env/env-native-protection.md）
  Object.defineProperty(document, 'all', {
    value: undefined,
    enumerable: false,
    configurable: true,
  });

  // document.cookie（getter/setter）
  Object.defineProperty(document, 'cookie', {
    get: protect.nativeFunction(() => cookieStore, 'get'),
    set: protect.nativeFunction((v) => {
      // 简易 cookie 写入
      const pair = String(v).split(';')[0];
      if (cookieStore) cookieStore += '; ' + pair;
      else cookieStore = pair;
    }, 'set'),
    configurable: true,
  });

  return document;
}

/**
 * 安装 location
 */
function installLocation(protect) {
  const location = {
    href: 'https://example.com/',
    protocol: 'https:',
    host: 'example.com',
    hostname: 'example.com',
    port: '',
    pathname: '/',
    search: '',
    hash: '',
    origin: 'https://example.com',
    assign: protect.nativeFunction(() => {}, 'assign'),
    replace: protect.nativeFunction(() => {}, 'replace'),
    reload: protect.nativeFunction(() => {}, 'reload'),
  };
  return location;
}

/**
 * 安装 screen
 */
function installScreen() {
  return {
    width: 1920, height: 1080,
    availWidth: 1920, availHeight: 1040,
    colorDepth: 24, pixelDepth: 24,
    orientation: { type: 'landscape-primary', angle: 0 },
  };
}

/**
 * 安装 storage（localStorage / sessionStorage）
 */
function installStorage() {
  return createFakeStorage();
}

/**
 * 安装 performance
 */
function installPerformance(protect) {
  const startTime = Date.now();
  return {
    now: protect.nativeFunction(() => Date.now() - startTime + Math.random(), 'now'),
    timeOrigin: startTime,
    getEntries: protect.nativeFunction(() => [], 'getEntries'),
    getEntriesByName: protect.nativeFunction(() => [], 'getEntriesByName'),
    getEntriesByType: protect.nativeFunction(() => [], 'getEntriesByType'),
    mark: protect.nativeFunction(() => {}, 'mark'),
    measure: protect.nativeFunction(() => {}, 'measure'),
  };
}

/**
 * 安装 crypto
 */
function installCrypto(protect) {
  return {
    getRandomValues: protect.nativeFunction((arr) => {
      try {
        if (arr && typeof arr === 'object' && 'length' in arr) webcrypto.getRandomValues(arr);
      } catch (e) {
        for (let i = 0; i < (arr && arr.length) || 0; i++) arr[i] = Math.floor(Math.random() * 256);
      }
      return arr;
    }, 'getRandomValues'),
    randomUUID: protect.nativeFunction(() => webcrypto.randomUUID(), 'randomUUID'),
    subtle: {
      digest: protect.nativeFunction(async (algorithm, data) => {
        const input = typeof data === 'string' ? new TextEncoder().encode(data) : data;
        return await webcrypto.subtle.digest(algorithm, input);
      }, 'digest'),
    },
  };
}

/**
 * 安装 Canvas / WebGL（fixture 回放）
 * HTMLCanvasElement / CanvasRenderingContext2D / WebGLRenderingContext 仅在 fixture 存在时注册
 * canvas 元素的 getContext() 由 createFakeElement() 内部分发到 createFake2DContext / createFakeWebGLContext
 * @returns {Object|null} canvas/webgl 构造器集合，无 fixture 时返回 null
 */
function installCanvasWebgl(protect, fixtures) {
  if (!fixtures.canvas && !fixtures.webgl) return null;
  return {
    HTMLCanvasElement: protect.nativeFunction(function () {}, 'HTMLCanvasElement'),
    CanvasRenderingContext2D: protect.nativeObject('CanvasRenderingContext2D'),
    WebGLRenderingContext: protect.nativeObject('WebGLRenderingContext'),
  };
}

// ============================================================
// 补环境主函数
// ============================================================
/**
 * 安装补环境
 * @param {Object} options
 * @param {Object} options.fixtures          指纹 fixture（canvas/webgl/plugins/navigator）
 * @param {string} options.userAgent         UA
 * @param {string} [options.cookie]          document.cookie 初始值
 * @param {string} [options.language='zh-CN'] 语言
 * @param {string} [options.platform='Win32'] navigator.platform
 * @returns {{ global: Object, nativeProtect: Object, navigator: Object, document: Object, location: Object, storage: Object, performance: Object, crypto: Object }}
 */
function installEnv(options = {}) {
  const {
    fixtures = {},
    userAgent = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36',
    cookie = '',
    language = 'zh-CN',
    platform = 'Win32',
  } = options;

  const protect = NativeProtect;

  // ----- 1. navigator -----
  const navigator = installNavigator(protect, fixtures, userAgent, language, platform);

  // ----- 2. document -----
  const document = installDocument(protect, fixtures, cookie);

  // ----- 3. location -----
  const location = installLocation(protect);
  document.location = location;

  // ----- 4. window / globalThis -----
  const win = {};
  Object.defineProperty(win, 'navigator', { value: navigator, configurable: true, enumerable: true });
  Object.defineProperty(win, 'document', { value: document, configurable: true, enumerable: true });
  Object.defineProperty(win, 'location', { value: location, configurable: true, enumerable: true });
  Object.defineProperty(win, 'self', { get: () => win, configurable: true });
  Object.defineProperty(win, 'top', { get: () => win, configurable: true });
  Object.defineProperty(win, 'parent', { get: () => win, configurable: true });
  Object.defineProperty(win, 'frames', { get: () => win, configurable: true });
  Object.defineProperty(win, 'window', { get: () => win, configurable: true });
  Object.defineProperty(win, 'globalThis', { get: () => win, configurable: true });

  // ----- 5. screen -----
  const screen = installScreen();
  Object.defineProperty(win, 'screen', { value: screen, configurable: true });

  // window 常用属性
  Object.defineProperty(win, 'innerWidth', { get: () => 1920, configurable: true });
  Object.defineProperty(win, 'innerHeight', { get: () => 937, configurable: true });
  Object.defineProperty(win, 'outerWidth', { get: () => 1920, configurable: true });
  Object.defineProperty(win, 'outerHeight', { get: () => 1080, configurable: true });
  Object.defineProperty(win, 'devicePixelRatio', { get: () => 1, configurable: true });
  Object.defineProperty(win, 'scrollX', { get: () => 0, configurable: true });
  Object.defineProperty(win, 'scrollY', { get: () => 0, configurable: true });

  // ----- 6. storage -----
  const storage = installStorage();
  Object.defineProperty(win, 'localStorage', { value: storage, configurable: true });
  Object.defineProperty(win, 'sessionStorage', { value: installStorage(), configurable: true });

  // ----- 7. performance -----
  const performance = installPerformance(protect);
  Object.defineProperty(win, 'performance', { value: performance, configurable: true });

  // ----- 8. crypto -----
  const crypto = installCrypto(protect);
  Object.defineProperty(win, 'crypto', { value: crypto, configurable: true });

  // ----- 9. Canvas / WebGL（fixture 回放）-----
  const canvasWebgl = installCanvasWebgl(protect, fixtures);
  if (canvasWebgl) {
    Object.defineProperty(win, 'HTMLCanvasElement', { value: canvasWebgl.HTMLCanvasElement, configurable: true });
    Object.defineProperty(win, 'CanvasRenderingContext2D', { value: canvasWebgl.CanvasRenderingContext2D, configurable: true });
    Object.defineProperty(win, 'WebGLRenderingContext', { value: canvasWebgl.WebGLRenderingContext, configurable: true });
  }

  // ----- 10. Node 泄露阻断 + vm 沙箱隔离 -----
  // 以 win 作为 vm 上下文全局对象；createSandbox 会删除宿主全局
  //（process/Buffer/require/module/global/fetch/...）并在上下文内应用 NativeProtect，
  // 真正阻断 Node 能力泄露（而非仅文档声明）。
  let sandbox = null;
  try {
    sandbox = createSandbox(win, { name: 'js-reverse-env', timeout: 5000 });
  } catch (err) {
    sandbox = null;
  }

  return {
    global: win,
    context: sandbox ? sandbox.context : win,
    run: sandbox ? sandbox.run : null,
    nativeProtect: NativeProtect,
    navigator,
    document,
    location,
    storage,
    performance,
    crypto,
    // 环境来源标识：用于 final.js 调试输出和门禁校验
    source: sandbox ? 'install-env.js (vm-sandbox, node-leak-blocked)' : 'install-env.js (quick-verify, NO vm-sandbox)',
  };
}

// ============================================================
// 辅助：fake element
// ============================================================
function createFakeElement(tag, protect, fixtures) {
  const el = {
    tagName: String(tag).toUpperCase(),
    style: {},
    children: [],
    childNodes: [],
    attributes: {},
    classList: { add: () => {}, remove: () => {}, contains: () => false },
    setAttribute: protect.nativeFunction((k, v) => { el.attributes[k] = v; }, 'setAttribute'),
    getAttribute: protect.nativeFunction((k) => el.attributes[k] ?? null, 'getAttribute'),
    removeAttribute: protect.nativeFunction((k) => { delete el.attributes[k]; }, 'removeAttribute'),
    appendChild: protect.nativeFunction((child) => { el.children.push(child); return child; }, 'appendChild'),
    removeChild: protect.nativeFunction((child) => {
      const i = el.children.indexOf(child);
      if (i >= 0) el.children.splice(i, 1);
      return child;
    }, 'removeChild'),
    addEventListener: protect.nativeFunction(() => {}, 'addEventListener'),
    removeEventListener: protect.nativeFunction(() => {}, 'removeEventListener'),
    getContext: protect.nativeFunction((type) => {
      if (type === '2d') return createFake2DContext(protect, fixtures);
      if (type === 'webgl' || type === 'webgl2' || type === 'experimental-webgl') {
        return createFakeWebGLContext(protect, fixtures);
      }
      return null;
    }, 'getContext'),
    toDataURL: protect.nativeFunction(() => fixtures.canvas?.dataUrl || 'data:image/png;base64,', 'toDataURL'),
    toBlob: protect.nativeFunction((cb) => cb(new ArrayBuffer(0)), 'toBlob'),
    getBoundingClientRect: protect.nativeFunction(() => ({
      x: 0, y: 0, top: 0, left: 0, right: 0, bottom: 0, width: 0, height: 0,
    }), 'getBoundingClientRect'),
  };
  return el;
}

function createFake2DContext(protect, fixtures) {
  const ctx = {
    canvas: null,
    fillStyle: '#000000',
    strokeStyle: '#000000',
    font: '10px sans-serif',
    fillRect: protect.nativeFunction(() => {}, 'fillRect'),
    strokeRect: protect.nativeFunction(() => {}, 'strokeRect'),
    clearRect: protect.nativeFunction(() => {}, 'clearRect'),
    fillText: protect.nativeFunction(() => {}, 'fillText'),
    strokeText: protect.nativeFunction(() => {}, 'strokeText'),
    measureText: protect.nativeFunction(() => ({ width: 0 }), 'measureText'),
    beginPath: protect.nativeFunction(() => {}, 'beginPath'),
    closePath: protect.nativeFunction(() => {}, 'closePath'),
    moveTo: protect.nativeFunction(() => {}, 'moveTo'),
    lineTo: protect.nativeFunction(() => {}, 'lineTo'),
    arc: protect.nativeFunction(() => {}, 'arc'),
    fill: protect.nativeFunction(() => {}, 'fill'),
    stroke: protect.nativeFunction(() => {}, 'stroke'),
    getImageData: protect.nativeFunction(() => ({ data: new Uint8ClampedArray(0) }), 'getImageData'),
    putImageData: protect.nativeFunction(() => {}, 'putImageData'),
    drawImage: protect.nativeFunction(() => {}, 'drawImage'),
    save: protect.nativeFunction(() => {}, 'save'),
    restore: protect.nativeFunction(() => {}, 'restore'),
    translate: protect.nativeFunction(() => {}, 'translate'),
    rotate: protect.nativeFunction(() => {}, 'rotate'),
    scale: protect.nativeFunction(() => {}, 'scale'),
  };
  return ctx;
}

function createFakeWebGLContext(protect, fixtures) {
  const ctx = {
    canvas: null,
    getParameter: protect.nativeFunction((p) => fixtures.webgl?.params?.[p] ?? null, 'getParameter'),
    getExtension: protect.nativeFunction((name) => {
      if (fixtures.webgl?.extensions?.includes(name)) {
        return protect.nativeObject('WebGLExtension');
      }
      return null;
    }, 'getExtension'),
    getSupportedExtensions: protect.nativeFunction(() => fixtures.webgl?.extensions || [], 'getSupportedExtensions'),
    getShaderPrecisionFormat: protect.nativeFunction(() => ({
      rangeMin: 127, rangeMax: 127, precision: 23,
    }), 'getShaderPrecisionFormat'),
    createBuffer: protect.nativeFunction(() => ({}), 'createBuffer'),
    bindBuffer: protect.nativeFunction(() => {}, 'bindBuffer'),
    bufferData: protect.nativeFunction(() => {}, 'bufferData'),
    createShader: protect.nativeFunction(() => ({}), 'createShader'),
    shaderSource: protect.nativeFunction(() => {}, 'shaderSource'),
    compileShader: protect.nativeFunction(() => {}, 'compileShader'),
    createProgram: protect.nativeFunction(() => ({}), 'createProgram'),
    attachShader: protect.nativeFunction(() => {}, 'attachShader'),
    linkProgram: protect.nativeFunction(() => {}, 'linkProgram'),
    useProgram: protect.nativeFunction(() => {}, 'useProgram'),
  };
  return ctx;
}

// ============================================================
// 辅助：fake storage
// ============================================================
function createFakeStorage() {
  const map = new Map();
  return {
    getItem: NativeProtect.nativeFunction((k) => (map.has(k) ? map.get(k) : null), 'getItem'),
    setItem: NativeProtect.nativeFunction((k, v) => { map.set(k, String(v)); }, 'setItem'),
    removeItem: NativeProtect.nativeFunction((k) => { map.delete(k); }, 'removeItem'),
    clear: NativeProtect.nativeFunction(() => { map.clear(); }, 'clear'),
    key: NativeProtect.nativeFunction((i) => Array.from(map.keys())[i] ?? null, 'key'),
    get length() { return map.size; },
  };
}

module.exports = { installEnv, NativeProtect };
