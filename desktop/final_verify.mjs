// 安装版最终验证截图 — 连接已装应用托管的 Host
import { chromium } from 'playwright';
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
// 已安装版的端口文件在 resources/host 下
const PORT_FILE = path.join(process.env.LOCALAPPDATA, 'Programs', 'clawd desktop', 'resources', 'host', '.clawd_host_port');
const OUT_DIR = path.join(ROOT, 'desktop', 'screenshots');
fs.mkdirSync(OUT_DIR, { recursive: true });
const log = (m) => console.log(`[final] ${m}`);

const info = JSON.parse(fs.readFileSync(PORT_FILE, 'utf-8'));
log(`连接已安装版 Host: port=${info.port}`);

(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1360, height: 860 } });
  await page.goto(`http://127.0.0.1:${info.port}/?token=${info.token}`, { waitUntil: 'networkidle' });
  await page.waitForTimeout(2000);

  const conn = await page.textContent('#connText');
  log(`连接状态: ${conn}`);

  // 真实对话（带 LLM）
  fs.writeFileSync(path.join(process.env.LOCALAPPDATA, 'Programs', 'clawd desktop', 'resources', 'host', 'final_probe.txt'), 'ZQ7A9527', 'utf-8');
  await page.fill('#input', '请用 FileReadTool 读取文件 final_probe.txt，只回复文件中的完整字符串。');
  await page.click('#send');

  const deadline = Date.now() + 120000;
  let finalText = '';
  while (Date.now() < deadline) {
    await page.waitForTimeout(3000);
    finalText = await page.evaluate(() => {
      const msgs = document.querySelectorAll('.msg-assistant');
      return msgs.length ? msgs[msgs.length - 1].textContent : '';
    });
    const disabled = await page.$eval('#send', (b) => b.disabled);
    if (finalText && !disabled) break;
  }
  log(`最终回复: ${finalText.slice(0, 150)}`);
  log('期望令牌: ZQ7A9527（写在 final_probe.txt 里）');
  const pass = finalText.includes('ZQ7A9527');
  log(pass ? 'PASS ✔ 安装版真实对话+工具调用全链路' : 'FAIL');

  await page.screenshot({ path: path.join(OUT_DIR, '07-installed-final.png') });
  log('截图: 07-installed-final.png');

  await browser.close();
  try { fs.unlinkSync(path.join(process.env.LOCALAPPDATA, 'Programs', 'clawd desktop', 'resources', 'host', 'final_probe.txt')); } catch (_) {}
  process.exit(pass ? 0 : 1);
})();
