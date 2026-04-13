import os
import sys
import webbrowser
import uvicorn
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from typing import List, Dict, Any, Optional

from ..core.config.models import get_settings, load_settings
from ..core.config.runtime import set_runtime_config, reload_config

app = FastAPI(title="Clawd Config Center")

# --- 数据模型 ---

class ProviderConfig(BaseModel):
    id: str
    name: str
    provider: str  # openai, anthropic, openrouter, etc.
    base_url: str
    api_key: str
    models: List[str]
    weight: int = 1  # 负载均衡权重
    enabled: bool = True

class GlobalConfig(BaseModel):
    providers: List[ProviderConfig]
    strategy: str = "round-robin"  # round-robin, random, fallback
    default_model: str = "gpt-4o"
    max_retries: int = 3

# --- 模拟持久化存储 ---
# 在实际应用中，这应该写入 .clawd/config.json
CONFIG_PATH = Path.home() / ".clawd" / "providers.json"

def load_stored_config():
    if CONFIG_PATH.exists():
        import json
        return json.loads(CONFIG_PATH.read_text(encoding='utf-8'))
    return {"providers": [], "strategy": "round-robin"}

def save_stored_config(config: dict):
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    import json
    CONFIG_PATH.write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding='utf-8')
    # 触发热重载
    reload_config()

# --- API 路由 ---

@app.get("/api/config")
async def get_config():
    return load_stored_config()

@app.post("/api/config")
async def save_config(config: GlobalConfig):
    save_stored_config(config.dict())
    return {"status": "success", "message": "配置已实时生效"}

@app.get("/", response_class=HTMLResponse)
async def index():
    return """
    <!DOCTYPE html>
    <html lang="zh-CN">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Clawd 配置中心 - 中文界面</title>
        <script src="https://cdn.tailwindcss.com"></script>
        <script defer src="https://cdn.jsdelivr.net/npm/alpinejs@3.x.x/dist/cdn.min.js"></script>
        <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap" rel="stylesheet">
        <style>
            body { font-family: 'Inter', 'PingFang SC', sans-serif; }
        </style>
    </head>
    <body class="bg-gray-50 min-h-screen" x-data="configApp()">
        <div class="max-w-5xl mx-auto py-12 px-4">
            <header class="flex justify-between items-center mb-10">
                <div>
                    <h1 class="text-3xl font-bold text-gray-900">Clawd 配置中心</h1>
                    <p class="text-gray-500 mt-2 text-sm">管理多模型 Provider、负载均衡与 API 密钥</p>
                </div>
                <div class="flex space-x-3">
                    <button @click="saveConfig()" class="bg-indigo-600 text-white px-6 py-2 rounded-lg font-semibold hover:bg-indigo-700 transition">保存并应用</button>
                </div>
            </header>

            <main class="grid grid-cols-1 md:grid-cols-3 gap-8">
                <!-- 左侧：全局策略 -->
                <section class="bg-white p-6 rounded-xl shadow-sm border border-gray-100">
                    <h2 class="text-lg font-semibold mb-4 border-b pb-2">调度策略</h2>
                    <div class="space-y-4">
                        <div>
                            <label class="block text-sm font-medium text-gray-700 mb-1">负载均衡算法</label>
                            <select x-model="config.strategy" class="w-full border-gray-300 rounded-md shadow-sm focus:ring-indigo-500 focus:border-indigo-500">
                                <option value="round-robin">轮询 (Round Robin)</option>
                                <option value="random">随机 (Random)</option>
                                <option value="fallback">故障转移 (Priority Fallback)</option>
                            </select>
                        </div>
                        <div>
                            <label class="block text-sm font-medium text-gray-700 mb-1">默认模型</label>
                            <input type="text" x-model="config.default_model" class="w-full border-gray-300 rounded-md shadow-sm">
                        </div>
                        <div>
                            <label class="block text-sm font-medium text-gray-700 mb-1">最大重试次数</label>
                            <input type="number" x-model="config.max_retries" class="w-full border-gray-300 rounded-md shadow-sm">
                        </div>
                    </div>

                    <div class="mt-8">
                        <div class="p-3 bg-blue-50 text-blue-700 text-xs rounded-lg">
                            💡 修改将实时更新至 <code class="bg-blue-100 px-1">.clawd/providers.json</code>
                        </div>
                    </div>
                </section>

                <!-- 右侧：Provider 列表 -->
                <section class="md:col-span-2 space-y-6">
                    <div class="flex justify-between items-center">
                        <h2 class="text-lg font-semibold">Provider 资源池</h2>
                        <button @click="addProvider()" class="text-indigo-600 text-sm font-medium hover:underline">+ 添加新配置</button>
                    </div>

                    <template x-for="(p, index) in config.providers" :key="p.id">
                        <div class="bg-white p-6 rounded-xl shadow-sm border border-gray-100 relative group">
                            <button @click="removeProvider(index)" class="absolute top-4 right-4 text-gray-300 hover:text-red-500 opacity-0 group-hover:opacity-100 transition">
                                <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"></path></svg>
                            </button>

                            <div class="grid grid-cols-2 gap-4">
                                <div class="col-span-2">
                                    <label class="block text-xs font-semibold text-gray-400 uppercase tracking-wider mb-1">配置名称</label>
                                    <input type="text" x-model="p.name" class="w-full border-gray-200 rounded-lg text-lg font-semibold focus:border-indigo-500 focus:ring-0">
                                </div>
                                <div>
                                    <label class="block text-xs font-semibold text-gray-400 uppercase mb-1">类型</label>
                                    <select x-model="p.provider" class="w-full border-gray-200 rounded-lg text-sm">
                                        <option value="openai">OpenAI / 自定义</option>
                                        <option value="anthropic">Anthropic</option>
                                        <option value="openrouter">OpenRouter</option>
                                        <option value="deepseek">DeepSeek</option>
                                    </select>
                                </div>
                                <div>
                                    <label class="block text-xs font-semibold text-gray-400 uppercase mb-1">权重 (负载均衡)</label>
                                    <input type="number" x-model="p.weight" class="w-full border-gray-200 rounded-lg text-sm">
                                </div>
                                <div class="col-span-2">
                                    <label class="block text-xs font-semibold text-gray-400 uppercase mb-1">API Base URL (带后缀路径)</label>
                                    <input type="text" x-model="p.base_url" placeholder="https://api.openai.com/v1" class="w-full border-gray-200 rounded-lg text-sm font-mono">
                                </div>
                                <div class="col-span-2">
                                    <label class="block text-xs font-semibold text-gray-400 uppercase mb-1">API Key</label>
                                    <input type="password" x-model="p.api_key" class="w-full border-gray-200 rounded-lg text-sm font-mono">
                                </div>
                            </div>
                        </div>
                    </template>

                    <div x-show="config.providers.length === 0" class="text-center py-12 bg-gray-100 rounded-xl border-2 border-dashed border-gray-200 text-gray-400">
                        目前还没有配置，请点击右上角“添加”
                    </div>
                </section>
            </main>
        </div>

        <script>
            function configApp() {
                return {
                    config: {
                        providers: [],
                        strategy: 'round-robin',
                        default_model: 'gpt-4o',
                        max_retries: 3
                    },
                    async init() {
                        const res = await fetch('/api/config');
                        const data = await res.json();
                        if (data.providers) this.config = data;
                    },
                    addProvider() {
                        this.config.providers.push({
                            id: Date.now().toString(),
                            name: '新配置',
                            provider: 'openai',
                            base_url: '',
                            api_key: '',
                            models: [],
                            weight: 1,
                            enabled: True
                        });
                    },
                    removeProvider(index) {
                        this.config.providers.splice(index, 1);
                    },
                    async saveConfig() {
                        const res = await fetch('/api/config', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify(this.config)
                        });
                        const result = await res.json();
                        alert(result.message);
                    }
                }
            }
        </script>
    </body>
    </html>
    """

def start_web_config(port: int = 8527):
    print(f"[*] 正在启动 Clawd 配置中心...")
    print(f"[*] 访问地址: http://127.0.0.1:{port}")

    # 自动打开浏览器
    def open_browser():
        import time
        time.sleep(1.5)
        webbrowser.open(f"http://127.0.0.1:{port}")

    import threading
    threading.Thread(target=open_browser, daemon=True).start()

    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")

if __name__ == "__main__":
    start_web_config()
