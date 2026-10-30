// 真实对话 UI E2E — 发消息 → 等真实 LLM 回复 → 截图
// 用法: node ui_e2e_real.mjs  （在 desktop/ 下跑）
import { chromium } from 'playwright';
import { spawn } from 'child_process';
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const PORT_FILE = path.join(ROOT, '.clawd_host_port');
const OUT_DIR = path.join(ROOT, 'desktop', 'screenshots');
fs.mkdirSync(OUT_DIR, { recursive: true });
const log = (m) => console.log(`[e2e] ${m}`);

async function waitForPortFile(timeoutMs = 30000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const d = JSON.parse(fs.readFileSync(PORT_FILE, 'utf-8'));
      if (d.port && d.token) return d;
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
host.stdout.on('data', (d) => log(`host: ${d}`.trimEnd().slice(0, 130)));

let exitCode = 0;
try {
  const info = await waitForPortFile();
  log(`Host 就绪 port=${info.port}`);
  const url = `http://127.0.0.1:${info.port}/?token=${info.token}`;
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1360, height: 860 } });
  await page.goto(url, { waitUntil: 'networkidle' });
  await page.waitForTimeout(1500);

  // 检查连接状态翻转（上一轮的 bug）
  const connText = await page.textContent('#connText');
  log(`连接状态: ${connText}`);
  if (!connText.includes('已连接')) {
    log('FAIL: 连接状态未翻转');
    exitCode = 1;
  }

  // 真实对话：要求模型调用工具读文件（文件先写好）
  fs.writeFileSync(path.join(ROOT, 'e2e_probe.txt'), 'CLAWD_UI_E2E_OK_2026', 'utf-8');
  await page.fill('#input', '请用 FileReadTool 读取文件 e2e_probe.txt，然后只回复文件中的完整字符串。');
  await page.click('#send');

  // 轮询等待最终回复（最长 90s）
  const deadline = Date.now() + 90000;
  let finalText = '';
  while (Date.now() < deadline) {
    await page.waitForTimeout(2500);
    finalText = await page.evaluate(() => {
      const msgs = document.querySelectorAll('.msg-assistant');
      return msgs.length ? msgs[msgs.length - 1].textContent : '';
    });
    if (finalText && !finalText.includes('处理中')) break;
    const sendDisabled = await page.$eval('#send', (b) => b.classList.contains('stop-mode'));
    if (!sendDisabled && finalText) break;
  }
  log(`最终回复: ${finalText.slice(0, 200)}`);
  const pass = finalText.includes('CLAWD_UI_E2E_OK_2026');
  log(pass ? 'PASS: 真实工具调用链路在 UI 中打通' : 'FAIL: 未看到正确回复');

  // 截图: 对话完成态 + 工具事件
  await page.screenshot({ path: path.join(OUT_DIR, '05-real-chat.png') });
  log('截图 5: 真实对话');

  // 市场截图（连接正常态重截）
  await page.click('#btnMarket');
  await page.waitForTimeout(1000);
  await page.screenshot({ path: path.join(OUT_DIR, '06-market-ok.png') });
  log('截图 6: 市场正常态');

  await browser.close();
  if (!pass) exitCode = 1;
} catch (e) {
  log(`ERROR: ${e.message}`);
  exitCode = 1;
} finally {
  host.kill();
  try { fs.unlinkSync(PORT_FILE); } catch (_) {}
  try { fs.unlinkSync(path.join(ROOT, 'e2e_probe.txt')); } catch (_) {}
}
process.exit(exitCode);
