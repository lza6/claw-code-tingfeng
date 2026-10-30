# Clawd Desktop 发布与自动更新指南

## 产物形态

| 产物 | 文件 | 用途 |
|------|------|------|
| NSIS 安装程序 | `dist/Clawd Desktop Setup <版本>.exe` | 标准安装（开始菜单/桌面快捷方式/卸载器/自动更新） |
| Portable 免安装 | `dist/ClawdDesktop-Portable-<版本>.exe` | 单文件双击即用（无注册表项，自动更新跳过） |

## 构建步骤

```powershell
# 1. 准备 host bundle（内嵌 Python + 精简依赖 + 源码，约 3-6 分钟）
#    必须看到 [5/5] 自检全过（用打包后的解释器真实 import + `-m src --help`）
#    缺依赖会自动从 venv 补齐，补不齐会中断 —— 这一步不过就别打包
venv/Scripts/python.exe scripts/prepare_host_bundle.py

# 2. 打包（NSIS + portable 双产物；建议用签名脚本，本地验证用 -SelfSigned）
pwsh -NoProfile -File scripts/build_desktop_signed.ps1 -SelfSigned
```

产物在 `desktop/dist/`。

> **为什么第 1 步的自检不能跳过**：bundle 里少一个包或一个 DLL，源码、单测、
> `node --check`、静态检查**全是绿的**，只有装到机器上双击才发现。本项目一天内踩过三次：
> `annotated_doc`（typer 的间接依赖没进白名单）、`exceptiongroup`（venv 里 anyio 的 METADATA
> 没有 Requires-Dist）、`python3.dll`（手写 DLL 清单漏项导致 C 扩展加载失败）。
>
> **出包后必须做的终验**：`pwsh -File %TEMP%\clawd-install-e2e.ps1` ——
> 静默安装 → 27 项浏览器断言 → 重启后 provider 仍在 → 卸载 → 残留清理（STEP5 会先留证）。

## 自动更新机制（仅 NSIS 安装版）

- 启动时静默检查更新源 → 发现新版本自动后台下载 → 提示"立即重启安装 / 稍后"
- 托盘右键 →「检查更新」手动触发
- 更新源配置在 `desktop/package.json` 的 `build.publish`：
  ```json
  { "provider": "generic", "url": "https://updates.clawd.cn/desktop/" }
  ```

## 发布新版本（有更新服务器后）

1. 改 `desktop/package.json` 的 `version`
2. `npm run dist`
3. 把 `dist/` 下这些文件上传到更新源 URL：
   - `Clawd Desktop Setup <版本>.exe`
   - `latest.yml`（electron-updater 自动生成的元数据，**必须**）
4. 老用户启动即自动收到更新提示

> 更换更新源：把 `provider` 改成 `"github"`（用 GitHub Releases）或自建 generic HTTPS 静态目录即可。

## 已知限制

- portable 版不含自动更新（electron-updater 依赖安装注册表信息）
- 首次安装包体积较大（内嵌 Python 运行时 + 依赖，约 150-250MB 压缩后）
- 更新源域名 `updates.clawd.cn` 是占位——上线前改成真实可访问的 HTTPS 静态目录/对象存储
