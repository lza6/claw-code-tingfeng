'use strict';

/**
 * NativeProtect — JS 层 toString / descriptor / 原型链 / DataCloneError 保护
 *
 * 用途：L3 补环境基础设施，在目标 JS 加载前于目标运行上下文内执行。
 * 详见 references/env/env-native-protection.md。
 *
 * 双副本同步：本文件在 assets/env-patch-snippets/ 与 templates/vm-sandbox/ 各存一份，
 * 修改任一处必须同步另一处（两份内容应始终保持一致）。
 *
 * 覆盖通道：
 *   - fn.toString() / Function.prototype.toString.call(fn) / String(fn) / fn + ""
 *   - fn.toString.toString()
 *   - Object.prototype.toString.call(obj)
 *   - structuredClone(fn) 抛出的 DataCloneError message / stack
 *   - MessagePort.prototype.postMessage(fn) 抛出的 DataCloneError message / stack
 *
 * 使用示例：
 *   const NativeProtect = require('./native-protect.js');
 *   const np = NativeProtect.getInstance();
 *   function getItem(key) { return storageMap.get(String(key)) ?? null; }
 *   np.setNativeFunc(getItem, 'getItem');
 *   Object.defineProperty(Storage.prototype, 'getItem', { value: getItem, writable: true, enumerable: true, configurable: true });
 *
 * 注意：
 *   - getInstance() 首次调用时会全局 patch Function.prototype.toString / Object.prototype.toString /
 *     structuredClone / MessagePort.postMessage。patch 对未注册函数保留原始行为，不会破坏宿主 JS
 *     正常运行；目标 JS 通过 vm context 隔离运行，全局 patch 不影响补环境逻辑的正确性。
 *   - 必须使用带 DataCloneError 改写的版本；旧版只 patch Function.prototype.toString 的不再适用。
 *   - 如果目标 JS 提前保存了原始 Function.prototype.toString，后 patch 可能失效。
 *   - 使用 vm 时要确保 patch 发生在目标 context 内。
 */

class NativeProtect {
    #map = new Map();
    #objMap = new Map();
    #clonePatched = false;

    static #instance = null;

    static getInstance() {
        if (!NativeProtect.#instance) {
            NativeProtect.#instance = new NativeProtect();

            const instance = NativeProtect.#instance;
            const _toString = Function.prototype.toString;

            const patchedToString = {
                toString() {
                    if (instance.#map.has(this)) {
                        const name = instance.#map.get(this);
                        return `function ${name || this.name}() { [native code] }`;
                    }
                    return _toString.call(this);
                }
            }.toString;

            Object.defineProperty(Function.prototype, "toString", {
                value: patchedToString,
                writable: true,
                enumerable: false,
                configurable: true,
            });

            instance.#map.set(Function.prototype.toString, "toString");

            const _objToString = Object.prototype.toString;
            const patchedObjToString = {
                toString() {
                    if (instance.#objMap.has(this)) {
                        const name = instance.#objMap.get(this);
                        return `[object ${name}]`;
                    }
                    return _objToString.call(this);
                }
            }.toString;

            Object.defineProperty(Object.prototype, "toString", {
                value: patchedObjToString,
                writable: true,
                enumerable: false,
                configurable: true,
            });

            instance.#map.set(Object.prototype.toString, "toString");
            instance.#patchCloneErrorLeak();
        }

        return NativeProtect.#instance;
    }

    constructor() {
        if (NativeProtect.#instance) {
            throw new Error("NativeProtect类只能实例化一次");
        }
    }

    setNativeFunc(func, name = "") {
        this.#map.set(func, name);
    }

    setObjFunc(obj, name = "") {
        this.#objMap.set(obj, name);
    }

    /**
     * 在给定 vm 上下文内 patch（而非污染宿主 Node.js 全局）。
     * @param {Object} context - vm.createContext 返回的上下文全局对象
     */
    applyToContext(context) {
        if (!context || !context.Function || !context.Object) return;
        const instance = this;
        const ctxFunction = context.Function;
        const ctxObject = context.Object;

        const _toString = ctxFunction.prototype.toString;
        const patchedToString = function () {
            if (instance.#map.has(this)) {
                const name = instance.#map.get(this);
                return `function ${name || this.name}() { [native code] }`;
            }
            return _toString.call(this);
        };
        Object.defineProperty(ctxFunction.prototype, "toString", {
            value: patchedToString,
            writable: true,
            enumerable: false,
            configurable: true,
        });
        instance.#map.set(ctxFunction.prototype.toString, "toString");

        const _objToString = ctxObject.prototype.toString;
        const patchedObjToString = function () {
            if (instance.#objMap.has(this)) {
                const name = instance.#objMap.get(this);
                return `[object ${name}]`;
            }
            return _objToString.call(this);
        };
        Object.defineProperty(ctxObject.prototype, "toString", {
            value: patchedObjToString,
            writable: true,
            enumerable: false,
            configurable: true,
        });
        instance.#map.set(ctxObject.prototype.toString, "toString");

        if (typeof context.structuredClone === "function") {
            const raw = context.structuredClone;
            const self = this;
            function structuredClone(value, options) {
                try {
                    return raw.apply(this, arguments);
                } catch (err) {
                    self.#rewriteDataCloneError(err, value);
                }
            }
            this.#copyFunctionMeta(structuredClone, raw, "structuredClone");
            context.structuredClone = structuredClone;
            this.setNativeFunc(structuredClone, "structuredClone");
        }

        if (context.MessagePort && context.MessagePort.prototype && typeof context.MessagePort.prototype.postMessage === "function") {
            const raw = context.MessagePort.prototype.postMessage;
            const self = this;
            function postMessage(value, transferList) {
                try {
                    return raw.apply(this, arguments);
                } catch (err) {
                    self.#rewriteDataCloneError(err, value);
                }
            }
            this.#copyFunctionMeta(postMessage, raw, "postMessage");
            context.MessagePort.prototype.postMessage = postMessage;
            this.setNativeFunc(postMessage, "postMessage");
        }
    }

    #patchCloneErrorLeak() {
        if (this.#clonePatched) return;
        this.#clonePatched = true;

        const rawStructuredClone = globalThis.structuredClone;
        const rawMessagePortPostMessage =
            typeof MessagePort !== "undefined" &&
            MessagePort.prototype &&
            MessagePort.prototype.postMessage;

        if (typeof rawStructuredClone === "function") {
            const self = this;

            function structuredClone(value, options) {
                try {
                    return rawStructuredClone.apply(this, arguments);
                } catch (err) {
                    self.#rewriteDataCloneError(err, value);
                }
            }

            this.#copyFunctionMeta(structuredClone, rawStructuredClone, "structuredClone");

            const desc =
                Object.getOwnPropertyDescriptor(globalThis, "structuredClone") || {
                    writable: true,
                    enumerable: true,
                    configurable: true,
                };

            Object.defineProperty(globalThis, "structuredClone", {
                ...desc,
                value: structuredClone,
            });

            this.setNativeFunc(structuredClone, "structuredClone");
        }

        if (typeof rawMessagePortPostMessage === "function") {
            const self = this;

            function postMessage(value, transferList) {
                try {
                    return rawMessagePortPostMessage.apply(this, arguments);
                } catch (err) {
                    self.#rewriteDataCloneError(err, value);
                }
            }

            this.#copyFunctionMeta(postMessage, rawMessagePortPostMessage, "postMessage");

            const desc =
                Object.getOwnPropertyDescriptor(MessagePort.prototype, "postMessage") || {
                    writable: true,
                    enumerable: true,
                    configurable: true,
                };

            Object.defineProperty(MessagePort.prototype, "postMessage", {
                ...desc,
                value: postMessage,
            });

            this.setNativeFunc(postMessage, "postMessage");
        }
    }

    #rewriteDataCloneError(err, value) {
        if (!err || err.name !== "DataCloneError") {
            throw err;
        }

        const fn = this.#findFunction(value);
        if (!fn) {
            throw err;
        }

        const fakeSource = this.#getFunctionSource(fn);
        const msg = `${fakeSource} could not be cloned.`;

        try {
            Object.defineProperty(err, "message", {
                value: msg,
                configurable: true,
            });
        } catch (_) {}

        try {
            if (typeof err.stack === "string") {
                const lines = err.stack.split(/\r?\n/);
                lines[0] = `${err.name}: ${msg}`;

                Object.defineProperty(err, "stack", {
                    value: lines.join("\n"),
                    configurable: true,
                });
            }
        } catch (_) {}

        throw err;
    }

    #getFunctionSource(fn) {
        try {
            return Function.prototype.toString.call(fn);
        } catch (_) {
            return "function () { [native code] }";
        }
    }

    #findFunction(value, seen = new WeakSet()) {
        if (typeof value === "function") return value;
        if (value === null || typeof value !== "object") return null;
        if (seen.has(value)) return null;
        seen.add(value);

        if (Object.prototype.toString.call(value) === '[object Map]') {
            for (const [k, v] of value) {
                const fk = this.#findFunction(k, seen);
                if (fk) return fk;

                const fv = this.#findFunction(v, seen);
                if (fv) return fv;
            }
        }

        if (Object.prototype.toString.call(value) === '[object Set]') {
            for (const v of value) {
                const fv = this.#findFunction(v, seen);
                if (fv) return fv;
            }
        }

        let keys;
        try {
            keys = Reflect.ownKeys(value);
        } catch (_) {
            return null;
        }

        for (const key of keys) {
            let desc;

            try {
                desc = Object.getOwnPropertyDescriptor(value, key);
            } catch (_) {
                continue;
            }

            if (desc && "value" in desc) {
                const f = this.#findFunction(desc.value, seen);
                if (f) return f;
            }
        }

        return null;
    }

    #copyFunctionMeta(target, source, name) {
        try {
            Object.defineProperty(target, "name", {
                value: name || source.name,
                writable: false,
                enumerable: false,
                configurable: true,
            });
        } catch (_) {}

        try {
            Object.defineProperty(target, "length", {
                value: source.length,
                writable: false,
                enumerable: false,
                configurable: true,
            });
        } catch (_) {}
    }
}

module.exports = NativeProtect;
