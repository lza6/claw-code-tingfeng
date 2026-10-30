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
const { app, BrowserWindow, Tray, Menu, nativeImage, ipcMain } = require('electron');
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

// ---------- 崩溃留痕（真实事故：重启后进程以 exit 1 静默退出，什么都没留下） ----------
// Node 15+ 默认把 unhandledRejection 当致命错误 → 主进程直接退出，用户只看到"闪退"。
// 这里至少把栈写进 shell.log，并把致命错误弹给用户看，而不是无声消失。
process.on('uncaughtException', (err) => {
  slog(`[crash] uncaughtException: ${(err && err.stack) || err}`);
  try {
    const { dialog } = require('electron');
    dialog.showErrorBox('Clawd 启动出错', `${(err && err.message) || err}\n\n日志: ${LOG_FILE}`);
  } catch (_) { /* 弹窗失败也要保证日志已写 */ }
});
process.on('unhandledRejection', (reason) => {
  slog(`[crash] unhandledRejection: ${(reason && reason.stack) || reason}`);
});

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


/** 把旧版本写在安装目录里的 .clawd 数据搬到 userData（只搬一次，不覆盖已有文件） */
function migrateLegacyData(targetDir) {
  const legacy = path.join(HOST_DIR, '.clawd');
  if (!fs.existsSync(legacy)) return;
  const marker = path.join(targetDir, '.migrated-from-legacy');
  if (fs.existsSync(marker)) return;
  try {
    fs.cpSync(legacy, targetDir, { recursive: true, force: false, errorOnExist: false });
    fs.writeFileSync(marker, new Date().toISOString(), 'utf-8');
    slog('[clawd-shell] 已把旧安装目录里的 .clawd 数据迁移到 userData');
  } catch (err) {
    slog(`[clawd-shell] 旧数据迁移失败（可忽略）: ${err && err.message}`);
  }
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
  // 数据目录必须与安装目录分离：否则升级/重装覆盖 resources/host，
  // 用户的 provider 配置 / 用量 / 会话会一起被清掉（真实事故）。
  const dataDir = path.join(app.getPath('userData'), 'data');
  try {
    fs.mkdirSync(dataDir, { recursive: true });
    migrateLegacyData(dataDir);
  } catch (err) {
    slog(`[clawd-shell] 准备数据目录失败: ${err && err.message}`);
  }
  args.push('--data-dir', dataDir);

  slog(`[clawd-shell] 启动 Host: ${py} ${args.join(' ')}`);
  hostProc = spawn(py, args, {
    cwd: HOST_DIR,
    stdio: ['ignore', 'pipe', 'pipe'],
    windowsHide: true,
    env: { ...process.env, CLAWD_DATA_DIR: dataDir },
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
      // 更新状态 / 版本信息需要一条最小 IPC 桥（此前缺失导致 UI 收不到任何更新事件）
      preload: path.join(__dirname, 'preload.js'),
    },
  });

  // 拦截导航到外部站点（Host 托管之外的一律开系统浏览器）
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    require('electron').shell.openExternal(url);
    return { action: 'deny' };
  });

  // 去掉原生菜单后，把真正会被用到的快捷键在窗口内补齐（不注册系统全局热键）
  mainWindow.webContents.on('before-input-event', (event, input) => {
    if (input.type !== 'keyDown') return;
    const ctrl = input.control || input.meta;
    const key = (input.key || '').toLowerCase();
    if (ctrl && key === 'r') { event.preventDefault(); mainWindow.webContents.reload(); return; }
    if (key === 'f5') { event.preventDefault(); mainWindow.webContents.reload(); return; }
    if (ctrl && input.shift && key === 'i') { event.preventDefault(); mainWindow.webContents.toggleDevTools(); return; }
    if (key === 'f12') { event.preventDefault(); mainWindow.webContents.toggleDevTools(); return; }
    if (ctrl && (key === 'q' || key === 'w')) { event.preventDefault(); mainWindow.close(); return; }
    if (ctrl && (key === '=' || key === '+')) { event.preventDefault(); mainWindow.webContents.setZoomLevel(mainWindow.webContents.getZoomLevel() + 0.5); return; }
    if (ctrl && key === '-') { event.preventDefault(); mainWindow.webContents.setZoomLevel(mainWindow.webContents.getZoomLevel() - 0.5); return; }
    if (ctrl && key === '0') { event.preventDefault(); mainWindow.webContents.setZoomLevel(0); return; }
  });

  mainWindow.loadURL(`${HOST_URL_BASE}:${readPortFile()?.port ?? ''}`);

  // E2E 探针（仅测试时启用）：验证 preload 桥/版本栏/设置/市场/检查更新是否真的通
  if (process.env.CLAWD_E2E_PROBE) {
    mainWindow.webContents.on('did-finish-load', async () => {
      const probePath = process.env.CLAWD_E2E_PROBE;
      // 该函数被序列化后注入渲染进程执行（因此不能用外层变量/闭包）
      const rendererProbe = async () => {
        const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
        const out = { done: true };
        try {
          await sleep(2500);
          out.bridge = !!window.clawdDesktop;
          if (out.bridge) {
            try {
              const info = window.clawdDesktop.appInfo() || {};
              out.appVersion = info.version || '';
              out.updateSupported = !!info.updateSupported;
            } catch (e) { out.appInfoError = String(e); }
          }
          out.verLine = (document.getElementById('verLine') || {}).textContent || '';

          const btnSettings = document.getElementById('btnSettings');
          if (btnSettings) {
            btnSettings.click();
            await sleep(1200);
            out.settingsOpened = document.getElementById('settingsOverlay')
              .classList.contains('show');
            const closeBtn = document.getElementById('settingsClose');
            if (closeBtn) closeBtn.click();
            await sleep(300);
          }

          const btnMarket = document.getElementById('btnMarket');
          if (btnMarket) {
            btnMarket.click();
            await sleep(1500);
            out.marketOpened = document.getElementById('marketOverlay')
              .classList.contains('show');
            const grid = document.getElementById('marketGrid');
            out.marketHasBuiltin = !!grid && grid.textContent.includes('逆向工具集');
            const marketClose = document.getElementById('marketClose');
            if (marketClose) marketClose.click();
            await sleep(300);
          }

          const btnUpd = document.getElementById('btnCheckUpdate');
          if (btnUpd) {
            btnUpd.click();
            await sleep(1800);
            out.updateLine = (document.getElementById('updateLine') || {}).textContent || '';
          }
        } catch (e) {
          out.error = String(e && e.stack ? e.stack : e);
        }
        return out;
      };

      try {
        const result = await mainWindow.webContents.executeJavaScript(
          `(${rendererProbe.toString()})()`, true
        );
        fs.writeFileSync(probePath, JSON.stringify(result, null, 2), 'utf-8');
        slog('[e2e] 探针完成');
      } catch (e) {
        try {
          fs.writeFileSync(
            probePath,
            JSON.stringify({ done: true, error: String(e) }, null, 2),
            'utf-8'
          );
        } catch (_) { /* 写不出探针文件时静默 */ }
      }
    });
  }
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

/** 默认更新源是占位域名，必须用 CLAWD_UPDATE_URL 覆盖后才真正生效 */
const DEFAULT_UPDATE_URL = 'https://updates.clawd.cn/desktop/';
let updateSourceConfigured = false;

let lastUpdateEventAt = 0;
function sendUpdateStatus(status, detail) {
  lastUpdateEventAt = Date.now();
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.webContents.send('update-status', status, detail || '');
  }
  slog(`[updater] status=${status}${detail ? ' — ' + detail : ''}`);
}

let autoUpdater = null;
function initUpdater() {
  // 仅安装版支持自动更新（portable 无注册表卸载信息）
  if (process.env.PORTABLE_EXECUTABLE_DIR) {
    slog('[updater] portable 版，跳过自动更新');
    sendUpdateStatus('unsupported', '免安装版不支持自动更新');
    return;
  }
  try {
    const _au = require('electron-updater');
    autoUpdater = _au.autoUpdater;
    // 更新源：环境变量优先；仍为占位域名时明确告知不可用，不静默失败
    const configured = process.env.CLAWD_UPDATE_URL || '';
    if (configured) {
      autoUpdater.setFeedURL({ provider: 'generic', url: configured, channel: 'latest' });
      updateSourceConfigured = true;
      slog(`[updater] 更新源: ${configured}`);
      // 未打包（开发/调试）时 electron-updater 默认拒绝联网检查，需要显式放行 +
      // 一份 dev-app-update.yml，否则 checkForUpdates() 静默不发请求，
      // UI 会永久停在"正在检查更新…"。
      if (!app.isPackaged) {
        try {
          fs.writeFileSync(
            path.join(__dirname, '..', 'dev-app-update.yml'),
            `provider: generic
url: ${configured}
channel: latest
`,
            'utf-8'
          );
          autoUpdater.forceDevUpdateConfig = true;
          slog('[updater] 开发态：已写 dev-app-update.yml 并启用 forceDevUpdateConfig');
        } catch (e) {
          slog(`[updater] 开发态更新配置写入失败: ${e}`);
        }
      }
    } else {
      const pkgUrl = (() => {
        try { return (require('../package.json').build.publish || [])[0].url; } catch (_) { return ''; }
      })();
      updateSourceConfigured = !!pkgUrl && pkgUrl !== DEFAULT_UPDATE_URL;
      if (!updateSourceConfigured) {
        slog('[updater] 更新源未配置（package.json 仍为占位地址），自动更新不可用');
        sendUpdateStatus('unsupported', '更新源未配置：请设置 CLAWD_UPDATE_URL 或修改 package.json build.publish');
        return;
      }
    }
    autoUpdater.autoDownload = true;      // 发现新版本自动下载
    autoUpdater.autoInstallOnAppQuit = true; // 退出时安装
    autoUpdater.on('update-available', (r) => {
      slog(`[updater] 发现新版本: ${r.version}，后台下载中…`);
      sendUpdateStatus('downloading', `新版本 ${r.version}`);
    });
    autoUpdater.on('update-not-available', () => sendUpdateStatus('none', '已是最新版本'));
    autoUpdater.on('error', (e) => sendUpdateStatus('error', String(e && e.message ? e.message : e)));
    autoUpdater.on('update-downloaded', (r) => {
      slog(`[updater] 下载完成: ${r.version}，退出时自动安装`);
      sendUpdateStatus('ready', `新版本 ${r.version} 已下载`);
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
  if (!autoUpdater || !updateSourceConfigured) {
    const msg = !autoUpdater
      ? '当前为免安装版或更新器不可用，请从发布页获取最新版本。'
      : '更新源未配置，无法检查更新。请设置 CLAWD_UPDATE_URL 或修改 package.json 的 build.publish。';
    sendUpdateStatus('unsupported', msg);
    if (manual) {
      const { dialog } = require('electron');
      dialog.showMessageBox({ type: 'info', title: '更新', message: msg });
    }
    return;
  }
  sendUpdateStatus('checking');
  Promise.resolve()
    .then(() => autoUpdater.checkForUpdates())
    .catch((e) => sendUpdateStatus('error', String(e && e.message ? e.message : e)))
    .finally(() => {
      // 兜底：若长时间没有任何事件（例如被 electron-updater 内部跳过），
      // 明确告知"未返回结果"，绝不让 UI 永久停在检查中。
      setTimeout(() => {
        if (!lastUpdateEventAt || Date.now() - lastUpdateEventAt > 20000) {
          sendUpdateStatus('error', '更新检查未返回结果（可能被跳过），请查看日志');
        }
      }, 20000);
    });
}

// 渲染进程（设置面板/版本栏）通过 preload 桥发起的调用
function registerIpcHandlers() {
  // 添加项目：原生文件夹选择器（渲染端拿不到绝对路径，必须走主进程）
  ipcMain.handle('clawd:pick-folder', async () => {
    const { dialog } = require('electron');
    const result = await dialog.showOpenDialog(mainWindow || undefined, {
      title: '选择项目文件夹',
      properties: ['openDirectory', 'createDirectory'],
    });
    if (result.canceled || !result.filePaths || result.filePaths.length === 0) return '';
    return result.filePaths[0];
  });

  // 注意：不要在这里再 `const { ipcMain, app } = require('electron')` ——
  // 函数内 const 会形成 TDZ，导致上方 ipcMain.handle(...) 抛
  // "Cannot access 'ipcMain' before initialization"，整个主进程在开窗前就挂掉（真实事故）。
  ipcMain.on('clawd:check-updates', () => checkForUpdates(true));
  // 更新就绪后"立即重启安装"（此前只有 autoUpdater 内部自动调用，用户点不到）
  ipcMain.handle('clawd:quit-and-install', () => {
    try {
      if (!autoUpdater) return { ok: false, reason: 'updater-unavailable' };
      setImmediate(() => { try { autoUpdater.quitAndInstall(); } catch (err) { console.error('[updater] quitAndInstall 失败:', err); } });
      return { ok: true };
    } catch (err) {
      console.error('[updater] quit-and-install 处理失败:', err);
      return { ok: false, reason: String(err && err.message ? err.message : err) };
    }
  });
  ipcMain.on('clawd:app-info', (event) => {
    event.returnValue = {
      version: app.getVersion(),
      electron: process.versions.electron,
      updateSupported: !!autoUpdater && updateSourceConfigured,
    };
  });
}

// ---------- 生命周期 ----------

if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on('second-instance', showMainWindow);

  app.whenReady().then(async () => {
    try {
    // 去掉 Electron 默认的原生菜单栏（File/Edit/View/Window/Help）——
    // 这是个聊天式应用，顶部那排 2003 年风格的菜单既不现代也没人用（用户明确反馈）。
    // 必要的快捷键在 createWindow() 里用 before-input-event 本地补齐（不占系统全局热键）。
    Menu.setApplicationMenu(null);

    registerIpcHandlers();
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
    } catch (err) {
      // 任何启动期异常都必须留痕 + 让用户看见，而不是主进程静默退出
      // （真实事故：重启应用后 exit 1，shell.log 一行都没有，只能靠猜）
      slog(`[crash] 启动流程失败: ${(err && err.stack) || err}`);
      try {
        const { dialog } = require('electron');
        dialog.showErrorBox('Clawd 启动失败', `${(err && err.message) || err}\n\n日志: ${LOG_FILE}`);
      } catch (_) { /* 弹窗失败不影响退出 */ }
      quitting = true;
      app.quit();
    }
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
