// UI 走查截图：主界面 / 会话列表 / 用量面板 / 设置面板 / 角色下拉
// 用法: node ui_snapshot.mjs [--port-file <path>]
import { chromium } from 'playwright';
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const DESKTOP = path.dirname(fileURLToPath(import.meta.url));
const argPort = process.argv.indexOf('--port-file');
const PORT_FILE = argPort > 0
  ? process.argv[argPort + 1]
  : path.join(DESKTOP, 'dist', 'win-unpacked', 'resources', 'host', '.clawd_host_port');
const OUT = path.join(DESKTOP, 'screenshots');
fs.mkdirSync(OUT, { recursive: true });

const info = JSON.parse(fs.readFileSync(PORT_FILE, 'utf-8'));
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1360, height: 860 } });
page.on('pageerror', (e) => console.log('[pageerror]', String(e).slice(0, 200)));
await page.goto(`http://127.0.0.1:${info.port}/?token=${info.token}`, { waitUntil: 'networkidle' });
await page.waitForTimeout(2500);

const shot = async (name) => {
  await page.screenshot({ path: path.join(OUT, name) });
  console.log('[shot]', name);
};

await shot('20-main-empty.png');

// 会话列表：点第一个历史会话，看看渲染效果
const hasSession = await page.evaluate(() => document.querySelectorAll('#sessionList .session-item').length);
if (hasSession > 0) {
  await page.click('#sessionList .session-item');
  await page.waitForTimeout(1200);
  await shot('21-session-loaded.png');
}

// 角色下拉展开（截图用：focus + 触发 change 之前的样子）
await page.evaluate(() => document.querySelector('#persona')?.focus());
await shot('22-composer-persona.png');

// 用量面板
await page.click('#btnUsage');
await page.waitForTimeout(1500);
await shot('23-usage.png');
await page.click('#usageClose');

// 设置面板
await page.click('#btnSettings');
await page.waitForTimeout(1200);
await shot('24-settings.png');
await page.evaluate(() => document.querySelector('#settingsOverlay')?.scrollTo(0, 400));
await page.waitForTimeout(400);
await shot('25-settings-providers.png');

await browser.close();
console.log('done');
