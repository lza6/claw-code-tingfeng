"""Background Tasks — 工作流相关任务"""

import logging

from celery import shared_task
from celery.signals import task_revoked

from ..workflow.engine import WorkflowEngine
from .celery_app import ClawdTask

logger = logging.getLogger(__name__)


@shared_task(bind=True, base=ClawdTask, expires=3600)
def run_workflow_async(self, workflow_config: dict, session_id: str):
    """异步执行工作流"""
    logger.info(f"Running workflow async for session: {session_id}")

    engine = WorkflowEngine()
    result = engine.execute(workflow_config)

    return {
        "status": result.status.value,
        "session_id": session_id,
        "result": result.to_dict() if hasattr(result, 'to_dict') else str(result),
    }


@shared_task(bind=True, base=ClawdTask, expires=1800)
def execute_workflow_step(self, step_id: str, context: dict):
    """异步执行单个工作流步骤"""
    logger.info(f"Executing workflow step: {step_id}")

    # 这里简化处理，实际应该从状态存储获取步骤详情
    return {
        "step_id": step_id,
        "status": "completed",
        "context": context,
    }


@shared_task(bind=True, base=ClawdTask, expires=600)
def cleanup_workflow_session(self, session_id: str):
    """清理工作流会话"""
    logger.info(f"Cleaning up workflow session: {session_id}")

    # 清理逻辑
    return {"session_id": session_id, "cleaned": True}


@shared_task
def schedule_periodic_tasks():
    """定期任务调度"""
    logger.info("Running periodic tasks")

    # 定时检查待处理任务
    return {"checked": True}


# 任务撤销信号
@task_revoked.connect
def on_task_revoked(request, terminated, signum, expiration):
    logger.warning(f"Task {request.id} was revoked")


__all__ = [
    "cleanup_workflow_session",
    "execute_workflow_step",
    "run_workflow_async",
    "schedule_periodic_tasks",
]
