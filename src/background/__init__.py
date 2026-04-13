"""Celery Background Tasks — 异步任务系统"""

from .celery_app import celery_app

__all__ = ["celery_app"]
