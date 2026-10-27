/**
 * Clawd Desktop — Electron 主进程（参考 DSH Desktop 架构）
 *
 * 壳的职责（仅此四件）:
 *   1. spawn/停止 Python Host 进程（venv python -m src serve）
 *   2. 读端口文件发现服务（.clawd_host_port: port + token）
 *   3. 托盘 + 单实例锁
 *   4. BrowserWindow loadURL(Host 的 Web UI)
 *
 * 硬规则: 壳内不造 IPC bridge、不做业务逻辑——一切能力来自 Host。
 */
const { app, BrowserWindow, Tray, Menu, nativeImage } = require('electron');
const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');

const IS_DEV = process.argv.includes('--dev');
// dev 模式: 本文件在 <项目>/desktop/electron/，项目根在两级之上
// 打包后: HOST_DIR = resources/host（内嵌 Python + src 所在），用户数据走 userData
const HOST_DIR = IS_DEV
  ? path.resolve(__dirname, '..', '..')
  : path.join(process.resourcesPath || '', 'host');
const WORKDIR = HOST_DIR; // Host 的 cwd（src 模块与 .clawd_host_port 都在这里解析）
const PORT_FILE = path.join(HOST_DIR, '.clawd_host_port');
const HOST_URL_BASE = 'http://127.0.0.1';
// 文件日志（Windows GUI 子系统下 console 不可见）；打包版写 userData 防安装目录无写权限
const LOG_FILE = IS_DEV
  ? path.join(HOST_DIR, 'desktop', 'shell.log')
  : path.join(app.getPath('userData'), 'shell.log');
function slog(msg) {
  try { fs.appendFileSync(LOG_FILE, `${new Date().toISOString()} ${msg}\n`); } catch (_) {}
}

let mainWindow = null;
let tray = null;
let hostProc = null;
let quitting = false;

// ---------- Host 进程管理 ----------

function findPython() {
  // 打包后: resources/host/python/python.exe（内嵌运行时）
  // 开发: 项目 venv
  const bundled = path.join(HOST_DIR, 'python', 'python.exe');
  if (fs.existsSync(bundled)) return bundled;
  const venvPy = path.join(HOST_DIR, 'venv', 'Scripts', 'python.exe');
  if (fs.existsSync(venvPy)) return venvPy;
  return 'python'; // 兜底 PATH
}

// ---------- 首次配置引导（LLM API Key） ----------

function ensureUserEnv(userEnv) {
  // 无 .env：弹窗引导用户输入 API 配置，跳过则无 LLM 模式运行（下次启动再问）
  const { BrowserWindow, dialog } = require('electron');
  // 需要主窗口存在后才能弹；此处同步创建一个临时输入窗
  const win = new BrowserWindow({
    width: 560, height: 460, resizable: false,
    title: 'Clawd Desktop 首次配置',
    webPreferences: { contextIsolation: true, nodeIntegration: false },
  });
  win.loadURL('data:text/html;charset=utf-8,' + encodeURIComponent(`<!DOCTYPE html>
<html><head><meta charset="utf-8"><style>
body{font-family:"Segoe UI","Microsoft YaHei";background:#181818;color:#ededed;padding:24px;font-size:13px}
h2{margin:0 0 6px}p{color:#b0b0b0;margin:0 0 16px}
input{width:100%;box-sizing:border-box;padding:9px 12px;border-radius:8px;border:1px solid #383838;background:#232323;color:#ededed;margin-bottom:12px;outline:none}
input:focus{border-color:#536dfe}
label{display:block;font-size:12px;color:#8a8a8a;margin-bottom:4px}
button{background:#536dfe;color:#fff;border:none;border-radius:8px;padding:9px 22px;cursor:pointer;font-size:13px}
button:hover{filter:brightness(1.1)}
.hint{font-size:11px;color:#8a8a8a;margin-top:14px}
</style></head><body>
<h2>🚀 欢迎使用 Clawd Desktop</h2>
<p>首次使用需要配置 LLM API（OpenAI 兼容格式）。也可以点"跳过"，之后在配置文件中填写。</p>
<label>API Base URL</label>
<input id="base" placeholder="https://api.example.com/v1">
<label>API Key</label>
<input id="key" type="password" placeholder="sk-...">
<label>模型名称</label>
<input id="model" placeholder="deepseek-chat / gpt-4o / ...">
<button id="btnSave">保存并启动</button>
<button id="btnSkip" style="background:#2a2a2a;margin-left:8px">跳过</button>
<div class="hint">配置保存在本机 userData/.env，不会上传。</div>
<script>
document.getElementById('btnSave').onclick = function(){
  const b=document.getElementById('base').value.trim();
  const k=document.getElementById('key').value.trim();
  const m=document.getElementById('model').value.trim()||'gpt-4o-mini';
  if(!b||!k){alert('Base URL 和 API Key 必填');return null}
  window.__result = 'LLM_PROVIDER=openai\\nOPENAI_API_KEY='+k+'\\nOPENAI_BASE_URL='+b+'\\nOPENAI_MODEL='+m+'\\n';
  document.title='__SAVED__';
};
document.getElementById('btnSkip').onclick = function(){
  window.__result = '';
  document.title='__SAVED__';
};
</script></body></html>`));
  return new Promise((resolve) => {
    const poll = setInterval(async () => {
      try {
        const title = await win.webContents.executeJavaScript('document.title');
        if (title === '__SAVED__') {
          clearInterval(poll);
          const content = await win.webContents.executeJavaScript('window.__result || ""').catch(() => "");
          try {
            if (content) fs.writeFileSync(userEnv, content, 'utf-8');
          } catch (_) {}
          win.close();
          resolve();
        }
      } catch (_) { /* 窗口已关 */ clearInterval(poll); resolve(); }
    }, 500);
  });
}

function startHost() {
  const py = findPython();
  const args = ['-m', 'src', 'serve'];
  // 打包版: LLM 配置走 userData/.env（安装目录只读）；无配置时引导创建
  const userEnv = path.join(app.getPath('userData'), '.env');
  if (!IS_DEV) {
    try {
      if (!fs.existsSync(userEnv)) {
        ensureUserEnv(userEnv).catch(() => {});
      }
    } catch (_) {}
    if (fs.existsSync(userEnv)) args.push('--env-file', userEnv);
  }
  slog(`[clawd-shell] 启动 Host: ${py} ${args.join(' ')}`);
  hostProc = spawn(py, args, {
    cwd: HOST_DIR,
    stdio: ['ignore', 'pipe', 'pipe'],
    windowsHide: true,
  });
  hostProc.stdout.on('data', (d) => slog(`[host] ${d}`.trimEnd()));
  hostProc.stderr.on('data', (d) => slog(`[host!] ${d}`.trimEnd()));
  hostProc.on('exit', (code) => {
    slog(`[clawd-shell] Host 退出 (code=${code})`);
    hostProc = null;
    if (!quitting) {
      // 意外退出：3 秒后重启（崩溃自愈）
      setTimeout(startHost, 3000);
    }
  });
}

function stopHost() {
  if (hostProc) {
    // Windows 下要杀进程树（python -m src serve 可能有子进程）
    if (process.platform === 'win32') {
      spawn('taskkill', ['/pid', String(hostProc.pid), '/T', '/F'], { windowsHide: true });
    } else {
      hostProc.kill('SIGTERM');
    }
    hostProc = null;
  }
}

// ---------- 服务发现（端口文件轮询） ----------

function readPortFile() {
  try {
    const raw = fs.readFileSync(PORT_FILE, 'utf-8');
    const data = JSON.parse(raw);
    if (data && typeof data.port === 'number' && data.token) return data;
  } catch (_) { /* 尚未就绪或损坏，继续轮询 */ }
  return null;
}

async function waitForHost(timeoutMs = 30000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const info = readPortFile();
    if (info) {
      // 端口文件就绪后再探测一下 TCP 可连
      const ok = await new Promise((resolve) => {
        const net = require('net');
        const s = net.connect(info.port, '127.0.0.1', () => { s.end(); resolve(true); });
        s.on('error', () => resolve(false));
        s.setTimeout(2000, () => { s.destroy(); resolve(false); });
      });
      if (ok) return info;
    }
    await new Promise((r) => setTimeout(r, 500));
  }
  return null;
}

// ---------- 窗口 ----------

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1280,
    height: 860,
    title: 'Clawd Desktop',
    icon: path.join(__dirname, 'tray.png'),
    // 沙箱化加载 loopback 页面（与 DSH 同构）
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });

  // 拦截导航到外部站点（Host 托管之外的一律开系统浏览器）
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    require('electron').shell.openExternal(url);
    return { action: 'deny' };
  });

  mainWindow.loadURL(`${HOST_URL_BASE}:${readPortFile()?.port ?? ''}`);
}

function showMainWindow() {
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.show();
    mainWindow.focus();
  } else {
    createWindow();
  }
}

// ---------- 托盘 ----------

function createTray() {
  const img = nativeImage.createFromPath(path.join(__dirname, 'tray.png'));
  tray = new Tray(img);
  tray.setToolTip('Clawd Desktop');
  tray.setContextMenu(Menu.buildFromTemplate([
    { label: '打开主窗口', click: showMainWindow },
    { type: 'separator' },
    {
      label: '重启 Host 服务',
      click: () => { stopHost(); startHost(); },
    },
    {
      label: '检查更新',
      click: () => checkForUpdates(true),
    },
    { type: 'separator' },
    {
      label: '退出',
      click: () => { quitting = true; app.quit(); },
    },
  ]));
  tray.on('double-click', showMainWindow);
}

// ---------- 自动更新（electron-updater） ----------
// 更新源由 publish 配置决定（GitHub Releases / generic server）。
// 无网络/无发布源时静默跳过，不影响使用。

let autoUpdater = null;
function initUpdater() {
  // 仅安装版支持自动更新（portable 无注册表卸载信息）
  if (process.env.PORTABLE_EXECUTABLE_DIR) {
    slog('[updater] portable 版，跳过自动更新');
    return;
  }
  try {
    const _au = require('electron-updater');
    autoUpdater = _au.autoUpdater;
    autoUpdater.autoDownload = true;      // 发现新版本自动下载
    autoUpdater.autoInstallOnAppQuit = true; // 退出时安装
    autoUpdater.on('update-available', (r) => {
      slog(`[updater] 发现新版本: ${r.version}，后台下载中…`);
      if (mainWindow) mainWindow.webContents.send('update-status', 'downloading');
    });
    autoUpdater.on('update-not-available', () => slog('[updater] 已是最新版本'));
    autoUpdater.on('error', (e) => slog(`[updater] 错误: ${e}`));
    autoUpdater.on('update-downloaded', (r) => {
      slog(`[updater] 下载完成: ${r.version}，退出时自动安装`);
      if (mainWindow) {
        const { dialog } = require('electron');
        dialog.showMessageBox(mainWindow, {
          type: 'info',
          title: '更新就绪',
          message: `新版本 ${r.version} 已下载完成，退出应用后自动安装。`,
          buttons: ['立即重启安装', '稍后'],
        }).then(({ response }) => {
          if (response === 0) {
            quitting = true;
            autoUpdater.quitAndInstall();
          }
        });
      }
    });
    checkForUpdates(false);
  } catch (e) {
    slog(`[updater] 初始化失败（不影响使用）: ${e}`);
  }
}

function checkForUpdates(manual) {
  if (!autoUpdater) {
    if (manual) {
      const { dialog } = require('electron');
      dialog.showMessageBox({
        type: 'info',
        title: '更新',
        message: '当前为免安装版或更新器不可用，请从发布页获取最新版本。',
      });
    }
    return;
  }
  autoUpdater.checkForUpdates().catch((e) => slog(`[updater] 检查失败: ${e}`));
}

// ---------- 生命周期 ----------

if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on('second-instance', showMainWindow);

  app.whenReady().then(async () => {
    // 打包版首次启动：LLM 配置引导（写 userData/.env 后 Host 才带 LLM）
    if (!IS_DEV && !fs.existsSync(path.join(app.getPath('userData'), '.env'))) {
      await ensureUserEnv(path.join(app.getPath('userData'), '.env'));
    }
    startHost();
    const info = await waitForHost();
    if (!info) {
      const { dialog } = require('electron');
      dialog.showErrorBox(
        'Clawd Host 启动失败',
        `30 秒内未检测到 Host 服务（端口文件: ${PORT_FILE}）。\n请检查 Python 环境后重启。`
      );
      quitting = true;
      app.quit();
      return;
    }
    createTray();
    createWindow();
    initUpdater();
  });

  // 关窗=最小化到托盘（DSH/聊天类软件惯例），托盘退出才真退
  app.on('window-all-closed', () => {
    // 不退出，驻留托盘
  });

  app.on('before-quit', () => {
    quitting = true;
    stopHost();
  });
}
