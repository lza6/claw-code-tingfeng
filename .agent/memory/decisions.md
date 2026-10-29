# Decisions

## D-01 原生工具调用默认关闭
- 决策：`CLAWD_NATIVE_TOOLS=1` 才启用；默认走文本 `<tool>` 协议。
- 理由：流式路径无法可靠收集 tool_calls；默认关闭保持既有行为。
- 代价：默认未获得原生调用收益。
- 重新考虑：流式 provider 统一支持 tool_calls delta 后。

## D-02 `src.__version__` 以 pyproject 为优先
- 决策：源码树优先读 `pyproject.toml`，metadata 作兜底。
- 理由：editable 安装元数据会滞后，导致不同解释器版本不一致。
- 代价：打包安装（无 pyproject）时仍走 metadata，行为不变。

## D-03 文件锁可重入 + owner token
- 决策：同线程重入放行；锁目录写 pid+随机 owner；陈旧锁原子 rename 回收。
- 理由：读改写函数内部会再次调用加锁写，不可重入会自锁；owner 防止误删他人锁。
- 代价：线程级重入对 async 协程不安全（已在已知限制记录）。

## D-04 SSRF 采用请求前置校验
- 决策：httpx 手动逐跳、urllib 自定义 handler、Playwright route 拦截。
- 理由：事后校验时内网请求已发出，不是防护。
- 代价：DNS rebinding TOCTOU 仍未消除。

## D-05 计划文档不删除（**已于 2026-10-29 被 D-13 取代**）
- 原决策：`下一步改进指南.md`、`死代码复核报告.md`、`参考的结果计划指南.md` 全部保留。
- 条件：只有全部任务闭环并归档 manifest 后才可删除。

## D-13 达标计划文档按归档流程删除（2026-10-29）
- 决策：满足「全部任务闭环/已过时」+ 已复制到 `docs/archive/plans/YYYYMMDD/` +
  SHA-256 校验一致 + 生成 archive-manifest + 记录回滚方式 后，**删除原件**。
- 已执行：
  - 2026-10-28：`参考的结果计划指南.md`、`reports/plan-audit-2026-10-19.md`
  - 2026-10-29：`下一步改进指南.md`（v2，被 v3 取代）、`死代码判定-2026-10-23.md`（被 10-28 取代）、
    `死代码复核报告.md`（纯历史）
- 理由：长期保留已过时文档会让"当前该按哪份做"不可判定（本轮实测 skill 里还写着"保留"）。
- 代价：删除前必须全文 grep 引用并同步 skill/memory，否则留下悬空指引。

## D-06 CI lint 分层而非全量清零
- 决策：硬错误（F821/F811/E9）阻塞；全量报告非阻塞。
- 理由：全量 1,697 条历史违规（W293/F401/I001）需独立批次清理，不能为变绿弱化检查。
- 代价：风格类问题暂不阻断。

## 2026-10-28 v0.61.0 关键决策
1. **原生 function calling 默认开启**（原 CLAWD_NATIVE_TOOLS 默认关）：实测 step-5-preview 等现代模型无视文本 <tool> 协议并声称"没有工具"；原生 tools 协议一次通过。回退开关保留（=0）。
2. **桌面壳选 Electron**（调研推荐 Tauri 体积小 90%）：用户点名 EL 框架；壳可替换原则下日后迁移不亏。
3. **Host 同端口托管 Web UI**（websockets process_request 静态处理）：DSH 同构，壳只需 loadURL 一个地址，免 CORS。
4. **bundle 白名单复制**（AST import 扫描 + pip show 递归闭包）：venv 有 500MB+ 遗留垃圾包（bitsandbytes/cv2/cmake），黑名单法 5127MB → 白名单 269MB。
5. **内嵌 Python 用系统解释器**（非 venv python.exe）：venv 的 python.exe 是启动器硬依赖 pyvenv.cfg，不可便携。
6. **LLM 配置走 userData/.env + --env-file**：安装目录只读且不应含密钥；首次启动图形引导创建。
7. **事件广播用 run_coroutine_threadsafe**（审查发现）：publish 在引擎线程，get_running_loop 会拿到错误 loop；必须显式 threadsafe 回 WS 服务 loop。

## 2026-10-28 工程卫生批次踩坑（必须记住）

**教训：`ruff --fix --unsafe-fixes` 会删 `# noqa` 注释，进而让后续 F401 修复删除"故意保留的向后兼容 re-export"。**

- 现象：`src/cli/repl.py` 末尾 `# ─── 向后兼容导出 (测试文件和其他模块依赖这些) ───` 块被整体删除，
  导致 `tests/cli/test_repl_core.py` 收集期 `ImportError: cannot import name '_print'`。
- 根因：RUF100（unused-noqa）先删掉 `# noqa: E402, F401, I001`，F401 随后判定该块为未使用导入并清除。
- 正确做法：
  1. **禁止**对 `src/` 全量跑 `--fix --unsafe-fixes`；`--unsafe-fixes` 只用于单一规则（如 `--select W293`）。
  2. 修 ruff 严格分批：先 whitespace（W291/W292/W293）→ 再 F401（非 unsafe）→ RUF100 **不自动修**（会解除保护）。
  3. 每批后必须：`import_sweep --strict-exit` + `pytest tests/cli tests/server -q`。
- 本轮实际成果（安全口径）：src ruff 433 → 319（-114，仅空白 101 + 安全未用导入 11 + 2）；剩余 319 条
  （RUF100 39 / E402 34 / F401 31 / RUF012 23 / E741 21 / B904 20）多为 re-export 兼容块纠缠，需逐文件人工判断。

## ruff 自动修复的第二条红线（2026-10-28）

**`I001`（import 排序）在本项目会引入循环导入。** 实测：对 src/ 跑 `--select I001 --fix`（15 处）后，
`tests/server/test_auth.py` 等 4 个模块收集期报
`ImportError: cannot import name 'get_logger' from partially initialized module 'src.utils' (circular import)`。
已全量回退（工作区 0 改动，319 条 ruff 恢复原状）。

结论：本项目 ruff 可安全自动化只到「纯空白（W291/W292/W293）+ 非 unsafe 的 F401」。
**禁止自动修**：I001（顺序敏感，有循环导入）、RUF100（会解除 noqa 保护，进而让 F401 删掉兼容 re-export）、
B904/RUF012/E741（本版 ruff 无 autofix，需逐点人工判断）。

## RUF100 也不能自动修（第三条 ruff 红线，2026-10-29 实测）

`# noqa: BLE001` 在项目未启用 BLE 规则时会被 RUF100 判为"未使用 noqa"（78 处）。
看似可直接删除，**但实测踩到与前两条同类的事故**：

- 批量删 noqa 时如果把 `# noqa: F401` 也一起删，`src/cli/repl.py` 的
  "向后兼容导出"块立刻被 F401 标记 → 后续任何人跑 `ruff --fix` 又会整块删掉（历史事故重演）
- 更糟的是我第一版用"整文件正则 + 去尾随空白"批量改，直接改坏 8 个文件
  （`src/main.py` / `src/agent/engine.py` / `src/agent/factory.py` 等语法错误），
  靠 `git checkout -- src/` 全量回退才恢复

**结论（ruff 自动化边界最终版）**：
1. 只允许**纯空白**（W291/W292/W293）与**非 unsafe 的 F401**（且已跟踪文件）
2. **禁止** I001（顺序敏感，实测引发循环导入）
3. **禁止** RUF100 批量删（会解除 noqa 保护，进而让 F401 删掉兼容 re-export）
4. 任何批量改写必须**逐文件 AST 校验 + 失败即回退**，禁止整仓正则替换

本轮安全做法：解析 ruff 的 RUF100 清单 → 只删该行 noqa 指令 → AST 校验通过才写盘 →
对 `repl.py` 等兼容块**主动恢复 `# noqa: F401` 加"勿删"注释**。
结果：ruff src 410 → 374（-36，实测；清理 78 条 unused-noqa 后其余项浮出）。
