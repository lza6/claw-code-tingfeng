/**
 * Preload — 渲染进程与主进程之间的最小安全桥
 *
 * contextIsolation: true + nodeIntegration: false 下，渲染端无法直接访问 IPC；
 * 此前 main.js 里 webContents.send('update-status', ...) 没有任何接收方，
 * 导致"检查更新/在线更新/自动安装"在 UI 上完全不可见。本桥只暴露必要能力：
 *   - onUpdateStatus(cb)  订阅更新状态
 *   - checkForUpdates()   手动触发检查
 *   - appInfo()           读取版本/平台（UI 版本栏）
 *   - pickFolder()        原生目录选择
 *   - quitAndInstall()    更新就绪后立即重启安装
 */
const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('clawdDesktop', {
  onUpdateStatus(cb) {
    const handler = (_event, status, detail) => cb(status, detail);
    ipcRenderer.on('update-status', handler);
    return () => ipcRenderer.removeListener('update-status', handler);
  },
  checkForUpdates() {
    ipcRenderer.send('clawd:check-updates');
  },
  appInfo() {
    return ipcRenderer.sendSync('clawd:app-info');
  },
  pickFolder() {
    return ipcRenderer.invoke('clawd:pick-folder');
  },
  quitAndInstall() {
    return ipcRenderer.invoke('clawd:quit-and-install');
  },
});
