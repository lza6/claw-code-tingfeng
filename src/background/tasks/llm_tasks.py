"""LLM Tasks — LLM相关后台任务"""

import logging

from celery import shared_task

from .celery_app import ClawdTask

logger = logging.getLogger(__name__)


@shared_task(bind=True, base=ClawdTask, expires=300)
def generate_completion_async(self, prompt: str, model: str, **kwargs):
    """异步生成 completion"""
    from ..llm import get_llm

    llm = get_llm(model)
    response = llm.generate(prompt, **kwargs)

    return {"response": response}


@shared_task(bind=True, base=ClawdTask, expires=600)
def batch_generate(self, prompts: list, model: str):
    """批量生成"""
    from ..llm import get_llm

    llm = get_llm(model)
    results = []

    for prompt in prompts:
        try:
            result = llm.generate(prompt)
            results.append({"success": True, "result": result})
        except Exception as e:
            results.append({"success": False, "error": str(e)})

    return {"results": results}


@shared_task(bind=True, base=ClawdTask, expires=1800)
def generate_streaming(self, prompt: str, model: str):
    """流式生成任务"""
    from ..llm import get_llm

    llm = get_llm(model)

    yield from llm.stream(prompt)


__all__ = [
    "batch_generate",
    "generate_completion_async",
    "generate_streaming",
]
