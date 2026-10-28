// Electron 壳 E2E — 验证 preload 桥、版本信息、检查更新状态链路
// 用法: node electron_bridge_e2e.mjs  （在 desktop/ 下跑）
// 通过 ELECTRON_ENABLE_LOGGING + 渲染端探针断言真实 IPC 往返，不做桩替换。
import { spawn } from 'child_process';
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const PORT_FILE = path.join(ROOT, '.clawd_host_port');
const PROBE = path.join(ROOT, '.clawd', '_electron_probe.json');
const log = (m) => console.log(`[electron-e2e] ${m}`);

const results = [];
function check(name, ok, detail = '') {
  results.push({ name, ok, detail });
  log(`${ok ? 'PASS' : 'FAIL'} — ${name}${detail ? ' :: ' + detail : ''}`);
}

// 清理旧探针
try { fs.unlinkSync(PROBE); } catch (_) {}
try { fs.unlinkSync(PORT_FILE); } catch (_) {}

const electronBin = path.join(ROOT, 'desktop', 'node_modules', 'electron', 'dist', 'electron.exe');
if (!fs.existsSync(electronBin)) {
  log('electron 未安装，跳过（安装后重跑）');
  process.exit(2);
}

// --dev：开发态（Host 用仓库 venv，而非打包后的 resources/host）
const child = spawn(electronBin, ['.', '--dev'], {
  cwd: path.join(ROOT, 'desktop'),
  env: { ...process.env, CLAWD_E2E_PROBE: PROBE, CLAWD_UPDATE_URL: '' },
  stdio: ['ignore', 'pipe', 'pipe'],
});
child.stdout.on('data', (d) => log(`shell: ${String(d).trimEnd().slice(0, 160)}`));
child.stderr.on('data', (d) => log(`shell-err: ${String(d).trimEnd().slice(0, 160)}`));

const deadline = Date.now() + 90000;
let probe = null;
while (Date.now() < deadline) {
  if (fs.existsSync(PROBE)) {
    try {
      probe = JSON.parse(fs.readFileSync(PROBE, 'utf-8'));
      if (probe.done) break;
    } catch (_) { /* 写入中 */ }
  }
  await new Promise((r) => setTimeout(r, 500));
}
try { child.kill(); } catch (_) {}

if (!probe) {
  log('FAIL — 未收到渲染端探针结果（窗口未起来或 preload 未注入）');
  process.exit(1);
}

check('preload 桥已注入 window.clawdDesktop', probe.bridge === true, String(probe.bridge));
check('appInfo() 返回版本号', /^\d+\.\d+\.\d+/.test(String(probe.appVersion || '')),
  String(probe.appVersion));
check('桌面壳版本与框架版本一致（单一版本源）',
  String(probe.appVersion) === String((probe.verLine || '').replace(/^v/, '')),
  `shell=${probe.appVersion} host=${probe.verLine}`);
check('appInfo() 报告更新支持状态', typeof probe.updateSupported === 'boolean',
  String(probe.updateSupported));
check('UI 版本栏渲染真实版本', /^v\d+\.\d+\.\d+/.test(String(probe.verLine || '')),
  String(probe.verLine));
check('检查更新按钮产生可见状态', (probe.updateLine || '').trim().length > 0,
  String(probe.updateLine));
check('未配置更新源时如实告知（unsupported 而非静默）',
  /更新源|不支持|无更新通道|最新/.test(String(probe.updateLine || '')),
  String(probe.updateLine));
check('设置面板在 Electron 内可用', probe.settingsOpened === true, String(probe.settingsOpened));
check('插件市场在 Electron 内可用', probe.marketOpened === true, String(probe.marketOpened));
check('插件市场内容在 Electron 内渲染', probe.marketHasBuiltin === true,
  String(probe.marketHasBuiltin));

const passed = results.filter((r) => r.ok).length;
log(`合计 ${results.length} 项，通过 ${passed}，失败 ${results.length - passed}`);
process.exit(passed === results.length ? 0 : 1);
