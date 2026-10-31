# 错误码排障索引

> 本页只做**索引**：文案、下一步命令、文档链接的唯一事实来源是
> `src/core/errors_catalog.py`。改文案请改那个模块，本页不重复内容（避免两处漂移）。

## 用法

```bash
clawd errors            # 列出全部错误码（中文标题 + 级别）
clawd errors E1001      # 查看单个错误码的完整说明（问题 / 下一步 / 文档）
clawd errors E1001 --json   # 机器可读（{code, zh_title, zh_message, next_step, doc_url, severity}）
```

程序内使用：

```python
from src.core.errors_catalog import coerce, render

try:
    ...
except ClawdError as exc:
    code, entry = coerce(exc)
    print(render(code, detail=exc.message))
```

未登记的错误码不会抛异常：`coerce` 返回兜底条目（`zh_title = 未登记的错误码`），
提示把该码反馈到 issue。新增 `ErrorCode` 却忘记登记文案时，测试
`tests/core/test_errors_catalog.py` 会直接变红。

## 码段

| 码段 | 类别 | 这一节讲什么 |
|:---|:---|:---|
| E0xxx | 通用错误 | 未知错误、内部缺陷、参数校验 |
| E1xxx | LLM | 提供商未配置、调用失败、限流、响应不可解析、上下文超长 |
| E2xxx | 工具执行 | 工具缺失、失败、超时、参数非法、注册/隔离/并发/审批拒绝 |
| E3xxx | 安全 | 命令注入、路径越界、认证失败、IP 封禁、危险操作 |
| E4xxx | 配置 | 缺配置、配置非法、配置文件不存在 |
| E5xxx | 工作流 | 版本不匹配、工作流文件缺失、台账读写、执行中断 |
| E6xxx | 认证与授权 | 认证失败、令牌过期/无效、权限不足、账号禁用、租户缺失 |
| E7xxx | API Key | 无效、禁用、限流、缺失、过期 |
| E8xxx | 限流 | 请求频率、token 用量、租户配额 |
| E9xxx | 状态/运行时 | 租约、调度、状态转换、邮箱、恢复、持久化、完整性校验 |

## E0xxx general

未知错误、框架内部缺陷、参数校验失败。先跑 `clawd doctor` 排除环境与配置问题；
内部错误带堆栈提 issue。

## E1xxx llm

模型侧问题。九成是 `LLM_PROVIDER` / `*_API_KEY` / `*_MODEL` / `*_BASE_URL` 没配好：
`.env.example` 是模板，`clawd doctor` 做连通性复检。
限流（429）等几十秒即可，别改代码。

## E2xxx tool

工具层问题。`TOOL_APPROVAL_DENIED`（E2009）**不是缺陷**：当前 `approval_mode`
只允许分析，拒绝写文件/执行命令是预期行为 —— 要么让模型改用只读工具，要么调宽模式。

## E3xxx security

安全拦截一律**先停手**：命令注入、路径越界、危险操作都是有意拒绝。
正确做法是缩小操作范围或走显式确认，**不要关闭校验**。

## E4xxx config

配置取值问题。`clawd config` 打印优先级链（默认值 → `.env` → 运行时 → CLI → 文件 → API），
先看清实际生效的是哪一层；`clawd config --reset` 清运行时覆盖。

## E5xxx workflow

5 阶段工作流引擎问题。`clawd ledger` 看进度账本定位失败阶段；
引擎细节见 [`workflow.md`](workflow.md)。

## E6xxx auth

身份问题：令牌过期/无效、角色权限不足、账号禁用、租户不匹配。
凭据类问题不要靠"再试一次"解决，先确认凭据本身。

## E7xxx apikey

密钥问题：从服务商控制台重新复制（注意别带引号/尾随空格），更新 `.env` 后 `clawd doctor` 复检；
`clawd usage` 看本机消耗。

## E8xxx ratelimit

额度问题：`PROVIDER_RATE_LIMIT` / `PROVIDER_MAX_CONCURRENCY`（见 `.env.example`）调小，
或压缩上下文（`/compact`）。

## E9xxx state

运行时状态问题：租约（lease）、调度（dispatch）、邮箱（mailbox）、持久化与完整性校验。
`STATE_PERSISTENCE_ERROR` / `STATE_INTEGRITY_CHECK_FAILED` 属 critical ——
继续长任务可能丢数据，**先备份状态目录再处理**。
