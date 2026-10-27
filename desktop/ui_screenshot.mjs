// UI 截图验证脚本 — 起 Host → 无头浏览器截图 → 对话交互 → 再截图
// 用法: node scripts/ui_screenshot.mjs
import { chromium } from 'playwright';
import { spawn } from 'child_process';
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const PORT_FILE = path.join(ROOT, '.clawd_host_port');
const OUT_DIR = path.join(ROOT, 'desktop', 'screenshots');
fs.mkdirSync(OUT_DIR, { recursive: true });

function log(m) { console.log(`[shot] ${m}`); }

async function waitForPortFile(timeoutMs = 30000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const data = JSON.parse(fs.readFileSync(PORT_FILE, 'utf-8'));
      if (data.port && data.token) return data;
    } catch (_) {}
    await new Promise((r) => setTimeout(r, 500));
  }
  throw new Error('端口文件超时');
}

const host = spawn(
  path.join(ROOT, 'venv', 'Scripts', 'python.exe'),
  ['-m', 'src', 'serve'],
  { cwd: ROOT, stdio: ['ignore', 'pipe', 'pipe'] },
);
host.stdout.on('data', (d) => log(`host: ${d}`.trimEnd().slice(0, 120)));
host.stderr.on('data', (d) => log(`host!: ${d}`.trimEnd().slice(0, 120)));

try {
  const info = await waitForPortFile();
  log(`Host 就绪: port=${info.port}`);
  const url = `http://127.0.0.1:${info.port}/?token=${info.token}`;

  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1360, height: 860 } });
  await page.goto(url, { waitUntil: 'networkidle' });
  await page.waitForTimeout(1500);

  // 1. 主界面（对话 tab）
  await page.screenshot({ path: path.join(OUT_DIR, '01-main.png') });
  log('截图 1: 主界面');

  // 2. 发送一条消息（会因无引擎事件流而显示错误/处理中——验证 UI 反应）
  await page.fill('#input', '你好，请介绍一下你自己');
  await page.click('#send');
  await page.waitForTimeout(2000);
  await page.screenshot({ path: path.join(OUT_DIR, '02-chat.png') });
  log('截图 2: 对话交互');

  // 3. 插件市场弹窗
  await page.click('#btnMarket');
  await page.waitForTimeout(1200);
  await page.screenshot({ path: path.join(OUT_DIR, '03-market.png') });
  log('截图 3: 插件市场');

  // 4. 轨迹 tab
  await page.click('#marketClose');
  await page.click('button[data-tab="trace"]');
  await page.waitForTimeout(400);
  await page.screenshot({ path: path.join(OUT_DIR, '04-trace.png') });
  log('截图 4: 轨迹 tab');

  await browser.close();
  log('全部截图完成 → desktop/screenshots/');
} finally {
  host.kill();
  try { fs.unlinkSync(PORT_FILE); } catch (_) {}
}
