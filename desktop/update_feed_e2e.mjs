// 更新检测 E2E — 真实 Electron + 真实 electron-updater + 本地 HTTP feed
//
// 验证「检查更新」的真实数据通路：App 启动 → electron-updater 请求 feed →
// 解析 latest.yml → 识别出更高版本 → 状态回传。
// 不验证真实下载与静默安装（需要已签名安装包与真实发布环境）。
//
// 用法: node update_feed_e2e.mjs   （在 desktop/ 下跑）
import http from 'http';
import fs from 'fs';
import path from 'path';
import { spawn } from 'child_process';
import { fileURLToPath } from 'url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const DESKTOP = path.join(ROOT, 'desktop');
const SHELL_LOG = path.join(DESKTOP, 'shell.log');
const log = (m) => console.log(`[update-e2e] ${m}`);
const results = [];
function check(name, ok, detail = '') {
  results.push({ name, ok, detail });
  log(`${ok ? 'PASS' : 'FAIL'} — ${name}${detail ? ' :: ' + detail : ''}`);
}

const FAKE_VERSION = '9.9.9';
const latestYml = `version: ${FAKE_VERSION}
files:
  - url: ClawdDesktop-Setup-${FAKE_VERSION}.exe
    sha512: AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA==
    size: 12345
path: ClawdDesktop-Setup-${FAKE_VERSION}.exe
sha512: AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA==
releaseDate: '2026-10-28T00:00:00.000Z'
`;

const feedHits = [];
const server = http.createServer((req, res) => {
  feedHits.push(req.url);
  if (req.url.includes('latest.yml')) {
    res.writeHead(200, { 'Content-Type': 'text/yaml' });
    res.end(latestYml);
  } else {
    res.writeHead(200, { 'Content-Type': 'application/octet-stream' });
    res.end(Buffer.alloc(12345));
  }
});
await new Promise((r) => server.listen(0, '127.0.0.1', r));
const feedUrl = `http://127.0.0.1:${server.address().port}/`;
log(`本地更新源: ${feedUrl}`);

try { fs.writeFileSync(SHELL_LOG, '', 'utf-8'); } catch (_) {}
try { fs.unlinkSync(path.join(ROOT, '.clawd_host_port')); } catch (_) {}

const electronBin = path.join(DESKTOP, 'node_modules', 'electron', 'dist', 'electron.exe');
if (!fs.existsSync(electronBin)) {
  log('electron 未安装，跳过');
  server.close();
  process.exit(2);
}

const child = spawn(electronBin, ['.', '--dev'], {
  cwd: DESKTOP,
  env: { ...process.env, CLAWD_UPDATE_URL: feedUrl },
  stdio: ['ignore', 'pipe', 'pipe'],
});
child.stdout.on('data', (d) => log(`shell: ${String(d).trimEnd().slice(0, 140)}`));

await new Promise((r) => setTimeout(r, 25000));
try { child.kill(); } catch (_) {}
try { spawn('taskkill', ['/IM', 'electron.exe', '/F'], { windowsHide: true }); } catch (_) {}
server.close();

const shellLog = fs.existsSync(SHELL_LOG) ? fs.readFileSync(SHELL_LOG, 'utf-8') : '';
check('electron-updater 真实请求了更新源', feedHits.some((u) => u.includes('latest.yml')),
  `hits=${JSON.stringify(feedHits.slice(0, 5))}`);
check('从 feed 认出更高版本 9.9.9',
  shellLog.includes('9.9.9') || shellLog.includes('downloading'),
  (shellLog.match(/\[updater\][^\n]*/g) || []).slice(0, 3).join(' | ') || '(无 updater 日志)');
check('更新状态被上报', /\[updater\] status=|downloading/.test(shellLog),
  (shellLog.match(/\[updater\][^\n]*/g) || []).slice(0, 3).join(' | '));
check('使用了 CLAWD_UPDATE_URL 覆盖（非占位域名）',
  shellLog.includes('更新源: ' + feedUrl) || shellLog.includes(feedUrl),
  (shellLog.match(/更新源[^\n]*/g) || []).join(' | '));

const passed = results.filter((r) => r.ok).length;
log(`合计 ${results.length} 项，通过 ${passed}，失败 ${results.length - passed}`);
process.exit(passed === results.length ? 0 : 1);
