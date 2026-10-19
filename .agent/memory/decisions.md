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

## D-05 计划文档不删除
- 决策：`下一步改进指南.md`、`死代码复核报告.md`、`参考的结果计划指南.md` 全部保留。
- 理由：均含未闭环任务或为维护依据；删除会丢失后续工作依据。
- 条件：只有全部任务闭环并归档 manifest 后才可删除。

## D-06 CI lint 分层而非全量清零
- 决策：硬错误（F821/F811/E9）阻塞；全量报告非阻塞。
- 理由：全量 1,697 条历史违规（W293/F401/I001）需独立批次清理，不能为变绿弱化检查。
- 代价：风格类问题暂不阻断。
