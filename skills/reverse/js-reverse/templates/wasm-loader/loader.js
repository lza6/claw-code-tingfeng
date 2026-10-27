/**
 * WASM 加载器模板
 *
 * 适用场景：
 *   - 目标加密算法使用 WebAssembly 实现
 *   - 需要在 Node.js 中加载 .wasm 文件并调用导出函数
 *
 * 设计要点：
 *   1. 优先使用 Node.js 内置 WebAssembly API
 *   2. 使用 buffer 实例化方式（WebAssembly.instantiate + fs.readFileSync）
 *      注：未使用 streaming 实例化（WebAssembly.instantiateStreaming），
 *      因 Node.js fs 不提供 application/wasm MIME type，需要额外 HTTP server 才能走 streaming
 *   3. 提供 importObject 注入（模拟浏览器环境 API）
 *   4. 支持缓存实例，避免重复实例化
 *   5. 支持 memory 管理（grow/释放）
 *
 * 使用方式：
 *   const { loadWasm } = require('./wasm-loader');
 *   const wasm = await loadWasm({
 *     wasmPath: './assets/encrypt.wasm',
 *     imports: { env: { ... } },
 *   });
 *   const result = wasm.exports.encrypt(inputPtr, len);
 */

'use strict';

const fs = require('fs');
const path = require('path');

// ============================================================
// 统一堆分配器（bump allocator）
// 供 env.malloc、_malloc、writeString/writeBytes 共用，避免多分配器指针冲突
// ============================================================
function createHeapAllocator(memory, startPtr = 4096) {
  let ptr = startPtr;
  return {
    alloc(size) {
      size = size >>> 0;
      if (size === 0) return 0;
      // 8 字节对齐
      ptr = (ptr + 7) & ~7;
      const out = ptr;
      ptr += size;
      while (ptr > memory.buffer.byteLength) {
        try {
          memory.grow(Math.max(1, Math.ceil((ptr - memory.buffer.byteLength) / 65536)));
        } catch (e) {
          return 0;
        }
      }
      return out;
    },
    reset() { ptr = startPtr; },
  };
}

// ============================================================
// 默认 importObject（模拟浏览器 env）
// ============================================================
function createDefaultImports(memory, allocator) {
  return {
    env: {
      // 内存
      memory: memory || new WebAssembly.Memory({ initial: 256, maximum: 4096 }),
      // 表
      table: new WebAssembly.Table({ initial: 0, element: 'anyfunc' }),
      tableBase: 0,
      memoryBase: 0,
      // 数学函数
      Math_fround: Math.fround,
      Math_abs: Math.abs,
      Math_min: Math.min,
      Math_max: Math.max,
      Math_floor: Math.floor,
      Math_ceil: Math.ceil,
      Math_sqrt: Math.sqrt,
      Math_pow: Math.pow,
      Math_sin: Math.sin,
      Math_cos: Math.cos,
      Math_tan: Math.tan,
      Math_log: Math.log,
      Math_exp: Math.exp,
      // 控制台
      emscripten_log: (level, fmtPtr) => { /* 静默 */ },
      console_log: (msgPtr) => { /* 静默 */ },
      // abort（Emscripten）
      abort: () => { throw new Error('WASM abort'); },
      abortStackOverflow: (what) => { throw new Error(`Stack overflow: ${what}`); },
      nullFunc_ii: (i) => { throw new Error(`nullFunc_ii(${i})`); },
      nullFunc_iii: (i) => { throw new Error(`nullFunc_iii(${i})`); },
      // 时间
      emscripten_get_now: () => Date.now(),
      clock: () => Date.now(),
      clock_gettime: (clk, tp) => 0,
      // 字符串
      strlen: (ptr) => {
        // 从 memory 读取以 null 结尾的字符串长度
        let len = 0;
        const view = new Uint8Array(memory.buffer);
        while (view[ptr + len] !== 0) len++;
        return len;
      },
      // 内存分配（Emscripten 风格：由统一堆分配器实现；模块若自带 malloc/free 会在 deepMerge 时覆盖）
      malloc: (size) => (allocator ? allocator.alloc(size) : 0),
      free: () => {}, // bump allocator 不回收；如需释放请改用模块自带 free
      // 文件 IO（通常不使用，桩函数）
      fd_write: (fd, buf, count, nwritten) => 0,
      fd_read: (fd, buf, count, nread) => 0,
      fd_close: (fd) => 0,
      fd_seek: (fd, offset, whence) => 0,
    },
    wasi_snapshot_preview1: {
      fd_write: () => 0,
      fd_read: () => 0,
      fd_close: () => 0,
      fd_seek: () => 0,
      proc_exit: (code) => { throw new Error('WASI proc_exit called with code ' + code); },
      environ_get: () => 0,
      environ_sizes_get: () => 0,
      clock_time_get: () => 0,
      random_get: (buf, len) => {
        const view = new Uint8Array(memory.buffer);
        for (let i = 0; i < len; i++) view[buf + i] = Math.floor(Math.random() * 256);
        return 0;
      },
    },
  };
}

// ============================================================
// WASM 加载器
// ============================================================
/**
 * 加载并实例化 WASM
 * @param {Object} options
 * @param {string} options.wasmPath     .wasm 文件路径
 * @param {Object} [options.imports]    importObject（覆盖默认）
 * @param {WebAssembly.Memory} [options.memory]  外部传入的 Memory
 * @param {boolean} [options.cache=true] 是否缓存实例
 * @returns {Promise<{ instance: WebAssembly.Instance, exports: Object, memory: WebAssembly.Memory }>}
 */
async function loadWasm(options = {}) {
  const {
    wasmPath,
    imports: customImports,
    memory: externalMemory,
    cache = true,
  } = options;

  if (!wasmPath) throw new Error('wasmPath 必填');
  const absPath = path.isAbsolute(wasmPath) ? wasmPath : path.resolve(wasmPath);

  // 缓存检查
  if (cache && wasmCache.has(absPath)) {
    return wasmCache.get(absPath);
  }

  // 读取 wasm 二进制
  const wasmBuffer = fs.readFileSync(absPath);

  // 创建 imports
  const memory = externalMemory || new WebAssembly.Memory({ initial: 256, maximum: 4096 });
  const allocator = createHeapAllocator(memory);
  const defaultImports = createDefaultImports(memory, allocator);
  const imports = deepMerge(defaultImports, customImports || {});

  // 实例化
  let instance;
  try {
    const result = await WebAssembly.instantiate(wasmBuffer, imports);
    instance = result.instance || result;
  } catch (e) {
    // 尝试不带 imports 实例化（部分 wasm 不需要 imports）
    try {
      const result = await WebAssembly.instantiate(wasmBuffer);
      instance = result.instance || result;
    } catch (e2) {
      throw new Error(`WASM 实例化失败: ${e.message} / ${e2.message}`);
    }
  }

  const wrapped = wrapExports(instance.exports, memory, allocator);
  const result = {
    instance,
    exports: wrapped,
    memory: instance.exports.memory || memory,
    rawExports: instance.exports,
  };

  // 调用初始化函数（Emscripten 风格）
  if (typeof instance.exports.__wasm_call_ctors === 'function') {
    instance.exports.__wasm_call_ctors();
  }
  if (typeof instance.exports._main === 'function') {
    // 通常不自动调用 _main，按需调用
  }

  if (cache) wasmCacheSet(absPath, result);
  return result;
}

// ============================================================
// 导出函数包装（提供类型转换和错误处理）
// ============================================================
function wrapExports(exports, memory, allocator) {
  const wrapped = {};

  for (const [name, value] of Object.entries(exports)) {
    if (typeof value === 'function') {
      wrapped[name] = wrapWasmFunction(value, name, memory);
    } else {
      wrapped[name] = value;
    }
  }

  // 提供内存读写辅助
  wrapped._readString = (ptr) => readCString(memory, ptr);
  wrapped._writeString = (str) => writeCString(memory, str, allocator);
  wrapped._readBytes = (ptr, len) => readBytes(memory, ptr, len);
  wrapped._writeBytes = (bytes) => writeBytes(memory, bytes, allocator);
  // 统一使用堆分配器，避免与 env.malloc / writeString 各自维护指针导致冲突
  wrapped._malloc = exports.malloc || exports._malloc || ((size) => allocator.alloc(size));
  wrapped._free = exports.free || exports._free || (() => {});

  return wrapped;
}

function wrapWasmFunction(fn, name, memory) {
  return function (...args) {
    try {
      const result = fn.apply(null, args);
      return result;
    } catch (e) {
      throw new Error(`WASM 函数 ${name} 调用失败: ${e.message}`);
    }
  };
}

// ============================================================
// 内存读写辅助
// ============================================================
function readCString(memory, ptr) {
  const view = new Uint8Array(memory.buffer);
  let end = ptr;
  while (view[end] !== 0 && end < view.length) {
    end++;
  }
  // 直接对原始字节 view 做 UTF-8 解码，避免 latin1→utf8 二次转码破坏多字节字符
  return new TextDecoder('utf8').decode(view.subarray(ptr, end));
}

function writeCString(memory, str, allocator) {
  const buf = Buffer.from(str, 'utf8');
  const ptr = allocator.alloc(buf.length + 1);
  const view = new Uint8Array(memory.buffer);
  for (let i = 0; i < buf.length; i++) view[ptr + i] = buf[i];
  view[ptr + buf.length] = 0;
  return ptr;
}

function readBytes(memory, ptr, len) {
  const view = new Uint8Array(memory.buffer);
  return Buffer.from(view.subarray(ptr, ptr + len));
}

function writeBytes(memory, bytes, allocator) {
  const buf = Buffer.from(bytes);
  const ptr = allocator.alloc(buf.length);
  const view = new Uint8Array(memory.buffer);
  for (let i = 0; i < buf.length; i++) view[ptr + i] = buf[i];
  return ptr;
}

// ============================================================
// 辅助：深合并
// ============================================================
function deepMerge(target, source) {
  const result = { ...target };
  for (const [k, v] of Object.entries(source)) {
    if (v && typeof v === 'object' && !Array.isArray(v) && !(v instanceof WebAssembly.Memory) && !(v instanceof WebAssembly.Table)) {
      result[k] = deepMerge(result[k] || {}, v);
    } else {
      result[k] = v;
    }
  }
  return result;
}

// ============================================================
// 缓存（限制容量，避免内存泄漏）
// ============================================================
const wasmCache = new Map();
const WASM_CACHE_MAX = 50;

function wasmCacheSet(key, value) {
  if (wasmCache.size >= WASM_CACHE_MAX) {
    const oldest = wasmCache.keys().next().value;
    if (oldest !== undefined) wasmCache.delete(oldest);
  }
  wasmCache.set(key, value);
}

function clearCache() {
  wasmCache.clear();
}

// ============================================================
// 使用示例
// ============================================================
//
// async function main() {
//   const wasm = await loadWasm({
//     wasmPath: './assets/encrypt.wasm',
//     imports: {
//       env: {
//         emscripten_get_now: () => performance.now(),
//       },
//     },
//   });
//
//   // 写入输入
//   const inputPtr = wasm._writeString('hello world');
//
//   // 调用加密函数
//   const outputPtr = wasm.exports.encrypt(inputPtr, 11);
//
//   // 读取输出
//   const encrypted = wasm._readString(outputPtr);
//   console.log('加密结果:', encrypted);
// }

module.exports = { loadWasm, createDefaultImports, clearCache };
