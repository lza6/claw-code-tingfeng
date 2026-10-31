"""中文错误字典 —— 把 `ErrorCode` 翻译成「用户看得懂 + 知道下一步做什么」的文案。

## 为什么要有这张表

`src/core/exceptions.py` 里的 `ErrorCode` 只是机器可读的编号（`E1001` 等），
用户在自己的终端里看到 `[E1001] LLM 提供商未配置` 时，仍然不知道该敲哪条命令。
历史上用户可见报错中英混杂（例如 "Provider is not configured, falling back to ..."），
用户只能去翻源码猜。审计条目 F-04 / X-8 要求：**任何用户可见错误都必须带中文说明
和可执行的下一步命令**，而不是一句英文 + 堆栈。

所以这张表做三件事：

1. 给每个 `ErrorCode` 一份简体中文文案：标题（发生了什么）+ 说明（为什么会这样）
   + 下一步（用户现在该敲什么命令）+ 严重级别（要不要立刻停手）；
2. 提供稳定排序的查询/渲染 API，CLI（`clawd errors [code] [--json]`）和异常捕获点
   共用同一份文案，避免同一个错误码在不同地方写两套中英文；
3. 暴露 `missing_codes()` 给测试与门禁用 —— 新增 `ErrorCode` 却忘记登记中文文案时，
   测试立刻变红，而不是等用户来报"这条报错是英文的"。

## 边界

本模块属于 `src/core/`（最底层），只用标准库 + `src.core.exceptions`，
不 import `cli` / `agent` / `tools_runtime` / `workflow`（见 `scripts/core_surface.py`）。

## 文档链接来源

`src/utils/urls.py` 里只有 Aider 移植过来的文档链接，没有本项目错误码文档条目；
仓库 git remote 是 `https://github.com/lza6/clawd-code`，因此 `DOCS_BASE` 取
`https://github.com/lza6/clawd-code/blob/main/docs/`，各类别锚点指向
`docs/troubleshooting-errors.md` 的对应小节。文案正文以本模块为唯一事实来源，
文档页只做索引，避免两处漂移。

用法::

    from src.core.errors_catalog import coerce, render

    try:
        ...
    except ClawdError as exc:
        code, entry = coerce(exc)
        print(render(code, detail=exc.message))
"""

from __future__ import annotations

import re
from typing import Any

from .exceptions import ErrorCode

__all__ = [
    'CATEGORY_DOCS',
    'DOCS_BASE',
    'ERRORS_DOC_PATH',
    'SEVERITIES',
    'catalog_entries',
    'coerce',
    'doc_url_for',
    'lookup',
    'missing_codes',
    'render',
]

# ---------------------------------------------------------------------------
# 文档链接与级别常量
# ---------------------------------------------------------------------------

#: 文档根（与 git remote `lza6/clawd-code` 的 main 分支保持一致的路径前缀）
DOCS_BASE = 'https://github.com/lza6/clawd-code/blob/main/docs/'

#: 错误码排障页（各类别锚点见 CATEGORY_DOCS）
ERRORS_DOC_PATH = 'troubleshooting-errors.md'

#: 严重级别取值（闭集，测试会校验每个条目都在其中）
SEVERITIES = ('info', 'warning', 'error', 'critical')

#: 错误码前缀 -> (文档锚点 slug, 中文类别名)
CATEGORY_DOCS: dict[str, tuple[str, str]] = {
    'E0': ('general', '通用错误'),
    'E1': ('llm', 'LLM 相关错误'),
    'E2': ('tool', '工具执行错误'),
    'E3': ('security', '安全相关错误'),
    'E4': ('config', '配置相关错误'),
    'E5': ('workflow', '工作流引擎错误'),
    'E6': ('auth', '认证与授权错误'),
    'E7': ('apikey', 'API Key 相关错误'),
    'E8': ('ratelimit', '限流相关错误'),
    'E9': ('state', '状态/运行时错误'),
}

#: 从任意文本里捞错误码（用户把整行报错贴回来时也能识别，大小写不敏感）
_CODE_PATTERN = re.compile(r'\bE\d{4}\b', re.IGNORECASE)

# ---------------------------------------------------------------------------
# 字典本体：(ErrorCode, 中文标题, 中文说明, 下一步, 严重级别)
# ---------------------------------------------------------------------------

_RAW: tuple[tuple[ErrorCode, str, str, str, str], ...] = (
    # ---- E0xxx 通用 ----
    (
        ErrorCode.UNKNOWN_ERROR,
        '未知错误',
        '抛出了一个没有被归类到具体错误码的异常，通常意味着上游异常没有被包装，错误信息可能不足以定位问题。',
        '先跑 `clawd doctor` 确认运行环境；仍复现时用 `clawd errors E0001` 查看说明，'
        '并把完整堆栈贴到 issue（https://github.com/lza6/clawd-code/issues）。',
        'error',
    ),
    (
        ErrorCode.INTERNAL_ERROR,
        '框架内部错误',
        '框架自身的不变量被破坏（不该失败的地方失败了），属于程序缺陷而非配置问题。',
        '带上复现步骤和堆栈提 issue；在此之前可先 `clawd doctor` 排除环境因素，'
        '并用 `clawd config --reset` 排除脏配置。',
        'critical',
    ),
    (
        ErrorCode.VALIDATION_ERROR,
        '输入校验失败',
        '传进来的参数不满足校验规则（缺字段、类型不对、取值越界），请求没有真正执行。',
        '按报错里的字段名修正参数后重试；不确定字段格式就先看 `clawd --help` 或对应子命令的 `--help`。',
        'warning',
    ),
    # ---- E1xxx LLM ----
    (
        ErrorCode.LLM_PROVIDER_NOT_CONFIGURED,
        'LLM 提供商未配置',
        '没有检测到任何可用的 LLM 提供商凭据，模型调用无法发起。',
        '在 `.env` 里设置 `LLM_PROVIDER` 与对应密钥（如 `OPENAI_API_KEY` / '
        '`ANTHROPIC_API_KEY`，模板见 `.env.example`），然后跑 `clawd doctor` 复检。',
        'error',
    ),
    (
        ErrorCode.LLM_API_CALL_FAILED,
        'LLM 接口调用失败',
        '请求发出去了但没有拿到有效响应（网络、鉴权、服务端 5xx 或模型名写错都可能）。',
        '先看 `clawd doctor` 的连通性检查；确认 `*_MODEL` 与 `*_BASE_URL` 拼写正确，'
        '再重试一次；持续失败可 `clawd config` 看当前生效配置来自哪一层。',
        'error',
    ),
    (
        ErrorCode.LLM_RATE_LIMIT_EXCEEDED,
        'LLM 调用频率超限',
        '提供商侧限流（429），短时间内请求太密集；一般几十秒后自动恢复。',
        '降低 `PROVIDER_MAX_CONCURRENCY` / `PROVIDER_RATE_LIMIT`（见 `.env.example`），'
        '或换用配额更宽的模型；无需改代码。',
        'warning',
    ),
    (
        ErrorCode.LLM_INVALID_RESPONSE,
        'LLM 返回内容无法解析',
        '模型返回了不符合预期的结构（空响应、非法 JSON、缺少必填字段），通常是模型能力不足或提示词与会话格式不匹配。',
        '重试一次；仍失败可换更强的模型，或检查是否开了流式解析相关开关'
        '（`ENABLE_HEURISTIC_TOOL_PARSER` 等）导致格式判断偏移。',
        'warning',
    ),
    (
        ErrorCode.LLM_CONTEXT_TOO_LONG,
        '上下文超出模型上限',
        '消息加文件内容超过了模型的上下文窗口，框架会尝试截断或压缩。',
        '用 `clawd chat` 里的 `/compact` 压缩会话，或减少一次性加入的文件；长期方案是换上下文更大的模型。',
        'warning',
    ),
    # ---- E2xxx 工具 ----
    (
        ErrorCode.TOOL_NOT_FOUND,
        '找不到要执行的工具',
        '模型要求调用一个当前未注册的工具（名字拼错、插件没加载、能力被关闭）。',
        '确认工具名与 `clawd doctor` 输出的工具清单一致；若是自定义工具，'
        '检查是否已在 `src/tools_runtime/__init__.py` 注册。',
        'error',
    ),
    (
        ErrorCode.TOOL_EXECUTION_FAILED,
        '工具执行失败',
        '工具真正跑起来后失败了（命令非零退出、文件不可写、外部依赖缺失）。',
        '看报错里的 `详情` 拿到原始输出；先在本地手敲同一条命令复现，再决定是改参数、补依赖还是换做法。',
        'error',
    ),
    (
        ErrorCode.TOOL_TIMEOUT,
        '工具执行超时',
        '工具在给定时间内没有跑完（长命令、下载、大仓库搜索最常见）。',
        '缩小命令范围（例如把整仓搜索限定到子目录），或改用后台/分批执行；必要时上调该工具的超时配置后重试。',
        'warning',
    ),
    (
        ErrorCode.TOOL_INVALID_ARGS,
        '工具参数不合法',
        '调用工具时给的参数类型或取值不对，工具在被执行前就拒绝了。',
        '按报错里的 `reason` 修正参数；模型自动调用时，把这条错误原文留在会话里，它下一轮会据此调整（无需人工介入）。',
        'warning',
    ),
    (
        ErrorCode.TOOL_REGISTRATION_ERROR,
        '工具注册失败',
        '启动时注册工具出错（重名、缺少必需属性、模块导入异常），该工具本次不可用。',
        '跑 `clawd doctor` 看是哪个工具注册失败；检查该工具类是否声明了 '
        '`name` / `description` / `parameter_schemas` / `risk_kind`。',
        'error',
    ),
    (
        ErrorCode.TOOL_CAPSULE_ISOLATION_FAILED,
        '工具隔离环境不可用',
        '工具胶囊（隔离执行沙箱）创建失败，出于安全考虑调用被拒绝。',
        '确认系统支持当前隔离方式（容器/沙箱可用、临时目录可写），'
        '再跑 `clawd doctor` 复检；无法启用隔离时不要强行关闭，改用低风险工具。',
        'error',
    ),
    (
        ErrorCode.TOOL_OBSERVABILITY_HOOK_ERROR,
        '工具监控钩子出错',
        '工具前后置的可观测性钩子抛错；工具本身可能已执行成功，但统计/审计数据不完整。',
        '看报错里的钩子名，检查对应钩子实现；`clawd usage` 可确认本次调用是否被记账。',
        'warning',
    ),
    (
        ErrorCode.TOOL_PARALLEL_LIMIT_EXCEEDED,
        '并发工具数超限',
        '一轮里要求并行执行的工具数量超过上限，多余的调用被推迟或拒绝。',
        '减少同一轮的工具调用数量，或上调并行上限配置后重试；无需改业务代码。',
        'warning',
    ),
    (
        ErrorCode.TOOL_APPROVAL_DENIED,
        '审批模式拒绝该工具调用',
        '当前 `approval_mode` 只允许分析、不允许改动，因此写文件/执行命令类工具被策略拒绝；'
        '这不是缺陷，重试不会改变结果。',
        '要么让模型改用只读工具，要么把审批模式调宽（`default` / `auto-edit` / `yolo`）；'
        '查看当前模式：`clawd config`。',
        'warning',
    ),
    # ---- E3xxx 安全 ----
    (
        ErrorCode.SECURITY_COMMAND_INJECTION,
        '命令注入被拦截',
        '待执行命令里出现了拼接/串联等注入特征，安全层直接阻止执行。',
        '改成不含 `;` `&&` `|` 的单一命令，或使用框架提供的结构化工具参数；不要为了跑通而绕过这一层拦截。',
        'critical',
    ),
    (
        ErrorCode.SECURITY_PATH_TRAVERSAL,
        '路径越界被拦截',
        '访问路径跳出了允许的工作目录（`..`、绝对路径、软链接指向外部）。',
        '把路径参数改到项目工作目录内；确实需要访问外部目录时，通过配置显式放开白名单，而不是关闭校验。',
        'critical',
    ),
    (
        ErrorCode.SECURITY_AUTH_FAILED,
        '认证失败',
        '请求未通过认证（缺少令牌、令牌不匹配、来源不在允许范围）。',
        '确认 CLI/服务端使用的令牌与配置一致；本地服务场景检查 `clawd serve` 的鉴权参数与调用方是否匹配。',
        'error',
    ),
    (
        ErrorCode.SECURITY_IP_BANNED,
        '来源 IP 已被封禁',
        '该来源因重复失败被临时封禁（默认 5 分钟），期间请求一律拒绝。',
        '等待封禁到期后重试，并先修正触发失败的原因（错误令牌/高频请求），否则解封后会再次被禁。',
        'warning',
    ),
    (
        ErrorCode.SECURITY_DANGEROUS_OPERATION,
        '危险操作被拦截',
        '检测到破坏性操作（递归删除、强制覆盖、写系统路径等），默认策略拒绝执行。',
        '确认操作确实必要后，缩小作用范围（指定具体文件/目录），或走显式确认流程；不要直接关闭危险操作拦截。',
        'critical',
    ),
    # ---- E4xxx 配置 ----
    (
        ErrorCode.CONFIG_MISSING,
        '缺少必要配置项',
        '运行必需的配置项为空（例如没有密钥、没有指定模型），流程无法继续。',
        '按报错里的 `key` 在 `.env` 或配置文件补齐（模板见 `.env.example`），'
        '再用 `clawd config` 确认该项来源与最终取值。',
        'error',
    ),
    (
        ErrorCode.CONFIG_INVALID,
        '配置值不合法',
        '配置项存在但取值无法解析（枚举值拼错、数字格式不对、类型不匹配）。',
        '用 `clawd config` 查看优先级链，找出实际生效的那一层并改成合法值；`clawd config --reset` 可清掉运行时覆盖。',
        'error',
    ),
    (
        ErrorCode.CONFIG_FILE_NOT_FOUND,
        '配置文件不存在',
        '指定路径下没有找到配置文件，可能路径写错或文件尚未创建。',
        '核对报错里的 `file_path`；需要新配置时从 `.env.example` 复制一份，或运行 `clawd config` 生成默认配置。',
        'error',
    ),
    # ---- E5xxx Workflow ----
    (
        ErrorCode.WORKFLOW_VERSION_MISMATCH,
        '工作流版本不匹配',
        '工作流文件的版本与当前引擎支持的版本不一致，为避免误执行被拒绝。',
        '按 `docs/workflow.md` 的版本说明迁移该工作流文件，或使用引擎自带的迁移/模板重新生成。',
        'error',
    ),
    (
        ErrorCode.WORKFLOW_FILE_NOT_FOUND,
        '工作流文件不存在',
        '指定的工作流定义文件路径找不到，任务无法开始。',
        '检查路径拼写与工作目录；用 `clawd run "目标"` 让引擎自动生成流程，或确认自定义工作流文件确实存在。',
        'error',
    ),
    (
        ErrorCode.TECH_DEBT_FILE_ERROR,
        '技术债台账读写出错',
        '技术债/审计台账文件读写失败（格式损坏、无写权限、路径不可达）。',
        '确认该文件未被其他进程占用且内容为合法 JSON；损坏时可备份后重建台账。',
        'warning',
    ),
    (
        ErrorCode.WORKFLOW_EXECUTION_ERROR,
        '工作流执行中断',
        '某个阶段执行失败导致整条流程中止，已完成阶段的产物会保留。',
        '用 `clawd ledger` 查看进度账本定位失败阶段，修正该阶段问题后从断点重跑。',
        'error',
    ),
    # ---- E6xxx 认证与授权 ----
    (
        ErrorCode.AUTH_FAILED,
        '登录/鉴权失败',
        '用户名口令或凭据不正确，身份没有被确认。',
        '重新核对凭据并重试；多次失败会触发封禁，先确认凭据无误再试。',
        'error',
    ),
    (
        ErrorCode.AUTH_TOKEN_EXPIRED,
        '令牌已过期',
        '访问令牌超过有效期，需要重新获取。',
        '重新登录或刷新令牌后重试；长期跑的任务建议在调用前检查有效期。',
        'warning',
    ),
    (
        ErrorCode.AUTH_TOKEN_INVALID,
        '令牌无效',
        '令牌格式错误、被篡改或与当前环境不匹配。',
        '清掉本地缓存令牌后重新登录获取新令牌；确认使用的不是其他环境的令牌。',
        'error',
    ),
    (
        ErrorCode.AUTH_PERMISSION_DENIED,
        '权限不足',
        '身份有效但角色不允许执行该操作。',
        '换用有权限的账号，或请管理员为该角色补上对应权限；不要用绕过鉴权的方式推进。',
        'error',
    ),
    (
        ErrorCode.AUTH_USER_DISABLED,
        '账号已被禁用',
        '该账号被管理员停用，任何操作都会被拒绝。',
        '联系管理员确认停用原因并申请恢复；恢复前换用其他可用账号。',
        'warning',
    ),
    (
        ErrorCode.AUTH_TENANT_NOT_FOUND,
        '租户不存在',
        '指定的租户标识没有对应记录（拼错、已被删除、属于其他环境）。',
        '核对租户标识与当前环境配置；多租户场景确认令牌所属租户与请求租户一致。',
        'error',
    ),
    # ---- E7xxx API Key ----
    (
        ErrorCode.API_KEY_INVALID,
        'API Key 无效',
        '密钥无法通过服务端校验（复制不全、混入空格、已被服务商吊销）。',
        '从服务商控制台重新复制密钥写入 `.env`（注意不要带引号或尾随空格），然后 `clawd doctor` 复检。',
        'error',
    ),
    (
        ErrorCode.API_KEY_DISABLED,
        'API Key 已被禁用',
        '该密钥在服务商侧被停用（欠费、违规、手动关闭）。',
        '登录服务商控制台查看密钥状态并启用或重新签发，再更新 `.env` 并跑 `clawd doctor`。',
        'error',
    ),
    (
        ErrorCode.API_KEY_RATE_LIMITED,
        'API Key 触发限流',
        '该密钥的配额在窗口内用尽，请求被服务商拒绝。',
        '降低并发与请求频率，或改用其他密钥/更高配额的套餐；`clawd usage` 可看到本机消耗情况。',
        'warning',
    ),
    (
        ErrorCode.API_KEY_NOT_FOUND,
        '未找到 API Key',
        '环境里没有任何可用密钥，调用无法发起。',
        '在 `.env` 设置对应提供商的密钥（参考 `.env.example`），或运行 `clawd config --web` 用可视化界面填写。',
        'error',
    ),
    (
        ErrorCode.API_KEY_EXPIRED,
        'API Key 已过期',
        '密钥超过有效期，服务端不再接受。',
        '重新签发密钥并替换 `.env` 中的旧值，然后 `clawd doctor` 复检。',
        'error',
    ),
    # ---- E8xxx 限流 ----
    (
        ErrorCode.RATE_LIMIT_EXCEEDED,
        '请求过于频繁',
        '本机或服务端的速率限制被触发。',
        '稍等片刻重试；持续出现时下调 `PROVIDER_RATE_LIMIT`（见 `.env.example`）或减少并发任务。',
        'warning',
    ),
    (
        ErrorCode.TOKEN_LIMIT_EXCEEDED,
        'Token 用量超限',
        '单次请求或窗口累计 token 超过上限，请求被拒绝。',
        '压缩上下文（`clawd chat` 里用 `/compact`）或减少单次输入文件；`clawd usage` 可查看已用额度。',
        'warning',
    ),
    (
        ErrorCode.TENANT_LIMIT_EXCEEDED,
        '租户配额已用尽',
        '所属租户的总额度用完，本租户下所有请求都会被拒。',
        '联系租户管理员提升额度或结算欠费；临时可换其他租户凭据继续。',
        'warning',
    ),
    # ---- E9xxx 状态/运行时 ----
    (
        ErrorCode.STATE_LEASE_NOT_HELD,
        '未持有权限租约',
        '当前执行者没有拿到该资源的租约，不能执行需要独占的写操作。',
        '先获取租约再操作；若上一持有者异常退出，等租约过期或显式释放后重试。',
        'warning',
    ),
    (
        ErrorCode.STATE_LEASE_STALE,
        '权限租约已过期',
        '租约超过有效时间自动失效，写操作被拒绝。',
        '重新申请租约后重试；长任务应周期性续租。',
        'warning',
    ),
    (
        ErrorCode.STATE_LEASE_CONFLICT,
        '权限租约冲突',
        '该资源已被其他持有者占用，或持有者信息与当前执行者不匹配。',
        '等待对方释放，或改用独立 worktree/独立资源并行；不要强抢同一资源。',
        'error',
    ),
    (
        ErrorCode.STATE_DISPATCH_NOT_FOUND,
        '调度记录不存在',
        '按 request_id 找不到对应调度记录（已被清理、写错 id、未落盘）。',
        '核对 request_id；记录缺失时重跑该任务，并检查状态目录是否可写。',
        'error',
    ),
    (
        ErrorCode.STATE_INVALID_TRANSITION,
        '非法状态转换',
        '试图把任务从当前状态切换到不允许的目标状态，被状态机拒绝。',
        '按状态机允许的路径推进（可参考 `docs/workflow.md`），不要跳步；需要回退时走显式的恢复/重置流程。',
        'error',
    ),
    (
        ErrorCode.STATE_MAILBOX_NOT_FOUND,
        '邮箱消息不存在',
        '按 message_id 找不到消息记录（已消费、过期清理或 id 错误）。',
        '核对 message_id；消息确已丢失时重发，并确认邮箱目录可写。',
        'error',
    ),
    (
        ErrorCode.STATE_ALREADY_DELIVERED,
        '消息已交付',
        '该消息此前已被投递过，重复投递被拒绝（幂等保护）。',
        '无需重试，属于预期行为；确需重新投递请生成新的 message_id。',
        'warning',
    ),
    (
        ErrorCode.STATE_RECOVERY_FAILED,
        '状态恢复失败',
        '按持久化快照恢复运行时状态时出错，可能快照损坏或版本不兼容。',
        '保留现场（备份状态目录）后从更早的快照或全新状态重跑，并把快照版本信息附在 issue 里。',
        'error',
    ),
    (
        ErrorCode.STATE_PERSISTENCE_ERROR,
        '状态持久化失败',
        '状态写入磁盘失败（磁盘满、权限不足、路径被占用），继续执行可能丢数据。',
        '检查磁盘空间与目录写权限后重试；不要忽略此错误继续长任务。',
        'critical',
    ),
    (
        ErrorCode.STATE_INTEGRITY_CHECK_FAILED,
        '完整性校验失败',
        '状态文件的内容与校验值不一致（被外部篡改、写入中断、并发写冲突）。',
        '停止使用该状态：备份后删除或回滚到上一个校验通过的状态，再重跑任务。',
        'critical',
    ),
)


def doc_url_for(code: ErrorCode | str) -> str:
    """返回错误码对应的文档链接（按码段映射到排障页锚点）。"""
    raw = code.value if isinstance(code, ErrorCode) else str(code)
    prefix = raw[:2].upper() if len(raw) >= 2 else ''
    slug = CATEGORY_DOCS.get(prefix, ('general', '通用错误'))[0]
    return f'{DOCS_BASE}{ERRORS_DOC_PATH}#{prefix.lower()}xxx-{slug}'


def _build_catalog() -> dict[ErrorCode, dict[str, str]]:
    catalog: dict[ErrorCode, dict[str, str]] = {}
    for member, title, message, next_step, severity in _RAW:
        if severity not in SEVERITIES:  # 写表时的手滑，导入期即暴露
            raise ValueError(f'{member.value} 的 severity 非法: {severity}')
        catalog[member] = {
            'code': member.value,
            'zh_title': title,
            'zh_message': message,
            'next_step': next_step,
            'doc_url': doc_url_for(member),
            'severity': severity,
        }
    return catalog


_CATALOG: dict[ErrorCode, dict[str, str]] = _build_catalog()


# ---------------------------------------------------------------------------
# 查询 API
# ---------------------------------------------------------------------------


def _as_member(value: Any) -> ErrorCode | None:
    """把 `ErrorCode` / 码值字符串 / 成员名 归一成 `ErrorCode` 成员。

    刻意不用 `try: ErrorCode(x) except ValueError: pass` 的写法：本项目有
    「静默吞异常不得增加」的硬指标（`scripts/check_silent_except.py`），
    而这里本来就不需要异常机制 —— 直接按成员名/码值查表即可，语义更清楚。
    """
    if isinstance(value, ErrorCode):
        return value
    if not isinstance(value, str):
        return None
    text = value.strip()
    match = _CODE_PATTERN.search(text)
    if match:
        text = match.group(0)
    candidate = text.upper()  # 码值/成员名都不区分大小写

    member = ErrorCode.__members__.get(candidate)
    if member is not None:
        return member
    for code in ErrorCode:
        if str(code.value).upper() == candidate:
            return code
    return None


def catalog_entries() -> list[dict[str, str]]:
    """返回全部已登记条目（按错误码升序稳定排序，返回副本）。"""
    return [dict(_CATALOG[member]) for member in sorted(_CATALOG, key=lambda m: m.value)]


def lookup(code: Any) -> dict[str, str] | None:
    """按错误码查条目；`ErrorCode` / 码值 / 成员名都接受，未知返回 `None`。"""
    member = _as_member(code)
    if member is None:
        return None
    entry = _CATALOG.get(member)
    return dict(entry) if entry is not None else None


def missing_codes() -> list[str]:
    """返回 `ErrorCode` 里存在但字典没登记的码（正常应为空列表）。"""
    return sorted(member.value for member in ErrorCode if member not in _CATALOG)


def _fallback_entry(raw_code: str) -> dict[str, str]:
    """未知错误码的兜底条目：仍然给出中文说明与下一步，而不是抛出异常。"""
    shown = raw_code or 'UNKNOWN'
    return {
        'code': shown,
        'zh_title': '未登记的错误码',
        'zh_message': f'错误码 {shown} 没有收录进中文错误字典，可能来自新代码或第三方组件。',
        'next_step': '运行 `clawd errors` 查看已登记的错误码；把该错误码反馈到 issue，以便补充中文说明与下一步。',
        'doc_url': f'{DOCS_BASE}{ERRORS_DOC_PATH}#e0xxx-general',
        'severity': 'error',
    }


def _extract_code(err: Any) -> str:
    """从 `Exception` / `str` / `ErrorCode` 里提取错误码字符串（取不到返回空串）。"""
    if isinstance(err, ErrorCode):
        return err.value
    if isinstance(err, str):
        match = _CODE_PATTERN.search(err)
        return match.group(0) if match else err.strip()[:64]
    code = getattr(err, 'code', None)
    if isinstance(code, ErrorCode):
        return code.value
    if isinstance(code, str) and code.strip():
        return code.strip()
    # 没有错误码的普通异常 -> 归入通用未知错误
    if isinstance(err, BaseException):
        return ErrorCode.UNKNOWN_ERROR.value
    return ''


def coerce(err: Any) -> tuple[str, dict[str, str]]:
    """把 `Exception` / `str` / `ErrorCode` 归一成 `(错误码字符串, 条目)`。

    未知错误码不抛异常，返回带原始码值的兜底条目（中文说明「未登记的错误码」）。
    """
    raw = _extract_code(err)
    member = _as_member(raw)
    if member is None:
        return (raw or 'UNKNOWN', _fallback_entry(raw))
    entry = _CATALOG.get(member)
    if entry is None:
        code = member.value
        return (code, _fallback_entry(code))
    return (member.value, dict(entry))


def render(code: Any, *, detail: str | None = None) -> str:
    """把错误码渲染成用户可读的中文段落（问题 / 下一步 / 文档 三段）。"""
    code_str, entry = coerce(code)
    lines = [
        f'【{code_str}】{entry["zh_title"]}（严重级别：{entry["severity"]}）',
        '',
        f'问题：{entry["zh_message"]}',
    ]
    if detail:
        lines.append(f'详情：{str(detail).strip()}')
    lines.extend(
        [
            '',
            f'下一步：{entry["next_step"]}',
            '',
            f'文档：{entry["doc_url"]}',
        ]
    )
    return '\n'.join(lines)
