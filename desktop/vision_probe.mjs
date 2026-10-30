// 视觉强试：CLAWD_VISION=1 强制把图片当 image_url 内容块发出去，看 provider 怎么回
// 目的：把 v0.87.0 的「真实视觉对话待验证」变成有证据的结论（支持 / 不支持 / 报错回退）
import { chromium } from 'playwright';
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const DESKTOP = path.dirname(fileURLToPath(import.meta.url));
const info = JSON.parse(fs.readFileSync(path.join(DESKTOP, '..', '.clawd_host_port'), 'utf-8'));
const log = (m) => console.log('[vision]', m);

const b = await chromium.launch();
const p = await b.newPage({ viewport: { width: 1360, height: 860 } });
const errors = [];
p.on('pageerror', (e) => errors.push(String(e).slice(0, 200)));
await p.goto(`http://127.0.0.1:${info.port}/?token=${info.token}`, { waitUntil: 'networkidle' });
await p.waitForTimeout(1500);

// 造一张 2x2 纯红 PNG（能答"红色"就说明真看图了）
const pasted = await p.evaluate(async () => {
  const b64 = 'iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAYAAABytg0kAAAAFElEQVR4nGP8z8DAwMDAxMDAwMDAAAANHQEDasKb6QAAAABJRU5ErkJggg==';
  const bytes = Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
  const file = new File([bytes], 'red.png', { type: 'image/png' });
  const dt = new DataTransfer();
  dt.items.add(file);
  document.querySelector('#input').dispatchEvent(new ClipboardEvent('paste', { clipboardData: dt, bubbles: true, cancelable: true }));
  await new Promise((r) => setTimeout(r, 500));
  return document.querySelectorAll('#attachBar .attach-chip').length;
});
log(`附件 chip 数=${pasted}`);

await p.fill('#input', '这张图片是什么颜色？只回答颜色。');
await p.click('#send');

const deadline = Date.now() + 120000;
let done = false;
while (Date.now() < deadline) {
  await p.waitForTimeout(1500);
  const busy = await p.$eval('#send', (btn) => btn.classList.contains('stop-mode'));
  if (!busy) { done = true; break; }
}
await p.waitForTimeout(2500);

const out = await p.evaluate(() => {
  const bodies = Array.from(document.querySelectorAll('.msg-assistant .body'));
  const errs = Array.from(document.querySelectorAll('.msg-err'));
  return {
    reply: bodies.length ? (bodies[bodies.length - 1].textContent || '').slice(0, 300) : '',
    err: errs.length ? (errs[errs.length - 1].textContent || '').slice(0, 300) : '',
  };
});
log('完成=' + done);
log('回复: ' + JSON.stringify(out.reply));
log('错误: ' + JSON.stringify(out.err));
log('页面异常: ' + JSON.stringify(errors.slice(0, 2)));

const said = (out.reply + out.err).toLowerCase();
const verdict = said.includes('red') || said.includes('红') ? 'LOOKS_AT_IMAGE'
  : (out.err ? 'ERROR_PATH' : 'NO_VISION');
log('判定: ' + verdict);
fs.writeFileSync(path.join(DESKTOP, 'screenshots', 'vision-probe.json'), JSON.stringify({ verdict, ...out, errors }, null, 2), 'utf-8');
await b.close();
