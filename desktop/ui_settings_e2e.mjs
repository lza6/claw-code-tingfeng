// 桌面端 UI 功能 E2E — 设置面板 / 插件市场 / 版本信息 / 检查更新
// 用法: node ui_settings_e2e.mjs   （在 desktop/ 下跑）
// 断言全部基于真实 DOM 状态与真实 Host API，不做任何桩替换。
import { chromium } from 'playwright';
import { spawn } from 'child_process';
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const PORT_FILE = path.join(ROOT, '.clawd_host_port');
const OUT_DIR = path.join(ROOT, 'desktop', 'screenshots');
const PLUGIN_DIR = path.join(ROOT, '.clawd', 'plugins', 'e2e-demo-plugin');
fs.mkdirSync(OUT_DIR, { recursive: true });

const log = (m) => console.log(`[ui-e2e] ${m}`);
const results = [];
function check(name, ok, detail = '') {
  results.push({ name, ok, detail });
  log(`${ok ? 'PASS' : 'FAIL'} — ${name}${detail ? ' :: ' + detail : ''}`);
}

async function waitForPortFile(timeoutMs = 40000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const d = JSON.parse(fs.readFileSync(PORT_FILE, 'utf-8'));
      if (d.port && d.token) return d;
    } catch (_) { /* 还没写出来 */ }
    await new Promise((r) => setTimeout(r, 300));
  }
  throw new Error('等待 .clawd_host_port 超时');
}

// 准备一个真实用户插件（验证 UI 承诺"放进 .clawd/plugins/ 即可出现"）
fs.mkdirSync(PLUGIN_DIR, { recursive: true });
fs.writeFileSync(
  path.join(PLUGIN_DIR, 'pyproject.toml'),
  '[tool.clawd.plugin]\nname = "e2e-demo-plugin"\nentry = "e2e_demo:setup"\n' +
  'version = "9.9.9"\ndescription = "E2E 演示插件（由测试创建）"\nprovides_tools = true\n',
  'utf-8',
);

const host = spawn(
  path.join(ROOT, 'venv', 'Scripts', 'python.exe'),
  ['-m', 'src', 'serve'],
  { cwd: ROOT, stdio: ['ignore', 'pipe', 'pipe'] },
);
host.stdout.on('data', (d) => log(`host: ${String(d).trimEnd().slice(0, 120)}`));

let exitCode = 0;
let browser = null;
try {
  const info = await waitForPortFile();
  log(`Host 就绪 port=${info.port}`);
  const url = `http://127.0.0.1:${info.port}/?token=${info.token}`;

  browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1360, height: 900 } });
  await page.goto(url, { waitUntil: 'networkidle' });
  await page.waitForTimeout(1200);

  // —— 1. 版本信息（此前 UI 完全没有） ——
  const verText = (await page.textContent('#verLine')) || '';
  check('版本信息显示', /^v\d+\.\d+\.\d+/.test(verText.trim()), `verLine="${verText.trim()}"`);

  const connText = (await page.textContent('#connText')) || '';
  check('WS 已认证连接', connText.includes('已连接'), `connText="${connText}"`);

  // —— 2. 设置按钮是真面板（此前是假按钮） ——
  await page.click('#btnSettings');
  await page.waitForTimeout(1200);
  const overlayShown = await page.evaluate(
    () => document.getElementById('settingsOverlay').classList.contains('show'));
  check('点击设置打开真面板', overlayShown);

  const setVersion = (await page.textContent('#setVersion')) || '';
  const setPython = (await page.textContent('#setPython')) || '';
  const setWorkdir = (await page.textContent('#setWorkdir')) || '';
  const setApiKey = (await page.textContent('#setApiKey')) || '';
  check('设置面板读到版本', /v?\d+\.\d+\.\d+/.test(setVersion), setVersion);
  check('设置面板读到 Python 版本', /^3\.\d+/.test(setPython.trim()), setPython);
  check('设置面板读到工作目录', setWorkdir.trim().length > 3, setWorkdir);
  check('API Key 状态已脱敏（不回显密钥）',
    setApiKey.includes('已配置') || setApiKey.includes('未配置'), setApiKey);

  const providerVal = await page.inputValue('#setProvider');
  const modelVal = await page.inputValue('#setModel');
  check('provider/model 已回填', providerVal.length > 0 && modelVal.length > 0,
    `${providerVal} / ${modelVal}`);

  await page.screenshot({ path: path.join(OUT_DIR, 'e2e-settings-open.png') });

  // —— 3. 保存设置真实生效 ——
  const newModel = 'e2e-model-probe';
  await page.fill('#setModel', newModel);
  await page.click('#setSave');
  await page.waitForTimeout(1500);
  const note = (await page.textContent('#setNote')) || '';
  check('保存设置返回成功提示', note.includes('已保存'), note);

  const persisted = path.join(ROOT, '.clawd', 'ui_settings.json');
  let savedModel = '';
  try {
    savedModel = JSON.parse(fs.readFileSync(persisted, 'utf-8')).model || '';
  } catch (_) { /* 文件可能尚未写出 */ }
  check('设置已持久化到 .clawd/ui_settings.json', savedModel === newModel, savedModel);

  // 重新读取，确认 UI 与服务端一致
  await page.click('#setReload');
  await page.waitForTimeout(1000);
  const reloadedModel = await page.inputValue('#setModel');
  check('重新读取后与保存值一致', reloadedModel === newModel, reloadedModel);

  await page.screenshot({ path: path.join(OUT_DIR, 'e2e-settings-saved.png') });
  await page.click('#settingsClose');
  await page.waitForTimeout(500);

  // —— 4. 插件市场（用户插件 + 内置包都应在） ——
  await page.click('#btnMarket');
  await page.waitForTimeout(1800);
  const marketShown = await page.evaluate(
    () => document.getElementById('marketOverlay').classList.contains('show'));
  check('插件市场打开', marketShown);

  const marketText = (await page.textContent('#marketGrid')) || '';
  check('市场列出用户插件（.clawd/plugins）', marketText.includes('e2e-demo-plugin'),
    marketText.slice(0, 120).replace(/\s+/g, ' '));
  check('市场列出内置能力包', marketText.includes('逆向工具集') || marketText.includes('MCP 桥接'));
  check('市场显示插件版本号', marketText.includes('9.9.9'));
  await page.screenshot({ path: path.join(OUT_DIR, 'e2e-market.png') });

  // 搜索过滤
  await page.fill('#marketSearch', 'e2e');
  await page.waitForTimeout(500);
  const filtered = (await page.textContent('#marketGrid')) || '';
  check('市场搜索可用', filtered.includes('e2e-demo-plugin')
    && (await page.locator('#marketGrid .market-card').count()) === 1);
  await page.fill('#marketSearch', '');
  await page.click('#marketClose');
  await page.waitForTimeout(400);

  // —— 5. 检查更新（浏览器模式应诚实告知无更新通道，而不是静默无反应） ——
  await page.click('#btnCheckUpdate');
  await page.waitForTimeout(600);
  const upd = (await page.textContent('#updateLine')) || '';
  check('检查更新有真实反馈（浏览器模式）', upd.trim().length > 0, upd);

  await page.screenshot({ path: path.join(OUT_DIR, 'e2e-final.png') });
  await browser.close();
  browser = null;
} catch (e) {
  log(`异常: ${e && e.stack ? e.stack : e}`);
  exitCode = 1;
} finally {
  if (browser) { try { await browser.close(); } catch (_) {} }
  try { host.kill(); } catch (_) {}
  try { fs.rmSync(PLUGIN_DIR, { recursive: true, force: true }); } catch (_) {}
}

const passed = results.filter((r) => r.ok).length;
log(`合计 ${results.length} 项，通过 ${passed}，失败 ${results.length - passed}`);
for (const r of results.filter((x) => !x.ok)) log(`  未通过: ${r.name} :: ${r.detail}`);
if (passed !== results.length) exitCode = 1;
process.exit(exitCode);
