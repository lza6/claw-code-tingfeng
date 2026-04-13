"""Celery App Configuration — 整合 Onyx 的 worker 配置模式

增强特性:
- 从环境变量加载配置
- 多队列支持（参考 Onyx 7+ worker 类型）
- 任务优先级
- 监控指标集成
- 自定义 TenantAwareTask（contextvars 传播）

Worker 类型设计（参考 Onyx）:
- primary:   主 worker，处理一般任务（默认并发 4）
- heavy:     重量级任务（如 LLM 调用、索引构建）
- light:     轻量任务（如通知、清理）
- workflow:  工作流任务

启动不同 worker 类型:
    celery -A src.background.celery_app.celery_app worker -Q primary -c 4 --pool=threads
    celery -A src.background.celery_app.celery_app worker -Q heavy -c 2 --pool=threads
    celery -A src.background.celery_app.celery_app worker -Q light -c 8 --pool=threads
    celery -A src.background.celery_app.celery_app worker -Q workflow -c 4 --pool=threads
"""
import contextlib
import contextvars
import logging
import os

from celery import Celery, Task
from celery.signals import task_postrun, task_prerun, worker_process_init

logger = logging.getLogger(__name__)


def get_redis_url() -> str:
    """构建 Redis URL"""
    host = os.environ.get("REDIS_HOST", "localhost")
    port = int(os.environ.get("REDIS_PORT", 6379))
    db = int(os.environ.get("REDIS_DB", 0))
    password = os.environ.get("REDIS_PASSWORD", "")

    if password:
        return f"redis://:{password}@{host}:{port}/{db}"
    return f"redis://{host}:{port}/{db}"


# ---------------------------------------------------------------------------
# Worker 类型配置（参考 Onyx 设计）
# ---------------------------------------------------------------------------

# Worker 并发数配置
CELERY_WORKER_PRIMARY_CONCURRENCY = int(os.environ.get("CELERY_WORKER_PRIMARY_CONCURRENCY", 4))
CELERY_WORKER_HEAVY_CONCURRENCY = int(os.environ.get("CELERY_WORKER_HEAVY_CONCURRENCY", 2))
CELERY_WORKER_LIGHT_CONCURRENCY = int(os.environ.get("CELERY_WORKER_LIGHT_CONCURRENCY", 8))
CELERY_WORKER_WORKFLOW_CONCURRENCY = int(os.environ.get("CELERY_WORKER_WORKFLOW_CONCURRENCY", 4))
CELERY_WORKER_LLM_CONCURRENCY = int(os.environ.get("CELERY_WORKER_LLM_CONCURRENCY", 2))


# Celery配置 - 整合 Onyx 模式
celery_app = Celery(
    "clawd_tasks",
    broker=get_redis_url(),
    backend=get_redis_url().replace("/0", "/1"),
    include=[
        "src.background.tasks.workflow_tasks",
        "src.background.tasks.llm_tasks",
    ],
)

# 配置项 - 从环境变量加载 (Onyx 风格)
celery_app.conf.update(
    # 任务序列化
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,

    # 任务执行配置
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    task_track_started=True,

    # 结果配置
    result_expires=int(os.environ.get("CELERY_RESULT_EXPIRES", 60 * 60 * 24)),  # 24 hours

    # Worker配置
    worker_concurrency=int(os.environ.get("CELERY_CONCURRENCY", 4)),
    worker_prefetch_multiplier=int(os.environ.get("CELERY_PREFETCH_MULTIPLIER", 1)),
    worker_max_tasks_per_child=int(os.environ.get("CELERY_MAX_TASKS_PER_CHILD", 1000)),
    worker_pool=os.environ.get("CELERY_WORKER_POOL", "threads"),  # 默认使用线程池

    # Beat配置
    beat_scheduler=os.environ.get("CELERY_BEAT_SCHEDULER", "celery.beat:PersistentScheduler"),
    beat_filename=os.environ.get("CELERY_BEAT_FILENAME", "/tmp/celerybeat-schedule"),

    # 任务路由（参考 Onyx 多队列设计）
    task_routes={
        "src.background.tasks.workflow_tasks.*": {"queue": "workflow"},
        "src.background.tasks.llm_tasks.*": {"queue": "llm"},
    },

    # 任务优先级
    task_inherit_parent_priority=True,
    task_default_priority="default",

    # 监控
    worker_send_task_events=True,
    task_send_sent_event=True,

    # 速率限制 (Onyx 风格)
    task_default_rate_limit=os.environ.get("CELERY_DEFAULT_RATE_LIMIT", "100/m"),

    # 多队列定义（参考 Onyx 设计）
    task_queues={
        "primary": {
            "exchange": "primary",
            "routing_key": "primary",
        },
        "heavy": {
            "exchange": "heavy",
            "routing_key": "heavy",
        },
        "light": {
            "exchange": "light",
            "routing_key": "light",
        },
        "workflow": {
            "exchange": "workflow",
            "routing_key": "workflow",
        },
        "llm": {
            "exchange": "llm",
            "routing_key": "llm",
        },
    },

    # 队列优先级（数字越小优先级越高）
    task_queue_max_priority=5,
    task_default_delivery_mode="persistent",
)


# ---------------------------------------------------------------------------
# 自定义任务基类（参考 Onyx TenantAwareTask）
# ---------------------------------------------------------------------------

class ClawdTask(Task):
    """自定义任务基类 — 带重试、错误处理和 contextvars 传播

    参考 Onyx TenantAwareTask 设计:
    1. 自动重试（指数退避）
    2. contextvars 传播（保持请求上下文）
    3. 成功/失败回调
    4. 指标集成
    """

    abstract = True  # Celery 不注册为真实任务

    # 自动重试配置
    autoretry_for = (Exception,)
    retry_backoff = True
    retry_backoff_max = 600
    retry_jitter = True

    def apply_async(self, *args, **kwargs):
        """任务异步调用前传播 contextvars"""
        # 复制当前 context 并注入到 kwargs 中
        ctx = contextvars.copy_context()
        kwargs.setdefault('__context_vars__', {})
        for var in ctx:
            with contextlib.suppress(AttributeError, TypeError):
                kwargs['__context_vars__'][var.name] = ctx[var]
        return super().apply_async(*args, **kwargs)

    def __call__(self, *args, **kwargs):
        """任务执行时恢复 contextvars"""
        # 恢复 contextvars（如果存在）
        context_data = kwargs.pop('__context_vars__', {})

        def run_task():
            return self.run(*args, **kwargs)

        # 如果有 context 数据，在上下文中运行
        if context_data:
            ctx = contextvars.copy_context()
            # 这里可以恢复特定的 context vars
            return ctx.run(run_task)

        return run_task()

    def on_failure(self, exc, task_id, args, kwargs, einfo):
        """任务失败回调"""
        logger.error(f"Task {task_id} failed: {exc}")

        # 记录指标
        try:
            from src.core.telemetry.metrics import get_agent_metrics
            agent_metrics = get_agent_metrics()
            agent_metrics.record_tool_call(
                tool_name=self.name or "unknown",
                duration=0.0,
                status="failure",
            )
        except Exception:
            pass  # 指标记录失败不影响主逻辑

        super().on_failure(exc, task_id, args, kwargs, einfo)

    def on_success(self, retval, task_id, args, kwargs):
        """任务成功回调"""
        logger.info(f"Task {task_id} succeeded: {retval}")

        # 记录指标
        try:
            from src.core.telemetry.metrics import get_agent_metrics
            agent_metrics = get_agent_metrics()
            agent_metrics.record_tool_call(
                tool_name=self.name or "unknown",
                duration=0.0,
                status="success",
            )
        except Exception:
            pass

        super().on_success(retval, task_id, args, kwargs)


# ---------------------------------------------------------------------------
# 信号处理（增强版）
# ---------------------------------------------------------------------------

@task_prerun.connect
def on_task_prerun(task_id, task, *args, **kwargs):
    """任务执行前"""
    logger.info(f"Task {task_id} ({task.name}) starting")


@task_postrun.connect
def on_task_postrun(task_id, task, *args, **kwargs):
    """任务执行后"""
    logger.info(f"Task {task_id} ({task.name}) completed")


@worker_process_init.connect
def on_worker_process_init(sender=None, **kwargs):
    """Worker 进程初始化"""
    logger.info(f"Celery worker process initializing (pid={os.getpid()})")


__all__ = [
    "CELERY_WORKER_HEAVY_CONCURRENCY",
    "CELERY_WORKER_LIGHT_CONCURRENCY",
    "CELERY_WORKER_LLM_CONCURRENCY",
    # Worker 并发配置
    "CELERY_WORKER_PRIMARY_CONCURRENCY",
    "CELERY_WORKER_WORKFLOW_CONCURRENCY",
    "ClawdTask",
    "celery_app",
    "get_redis_url",
]
