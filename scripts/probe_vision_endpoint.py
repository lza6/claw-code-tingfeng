"""直接问端点：content 数组（image_url）到底收不收

不清屏、不打印密钥；只输出状态码 / 异常类型与首行消息。
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# 读 .env（与产品同源）
env = Path(".env")
for line in env.read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    k, v = line.split("=", 1)
    os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

from openai import AsyncOpenAI  # noqa: E402

BASE = os.environ.get("OPENAI_BASE_URL") or os.environ.get("LLM_BASE_URL") or ""
KEY = os.environ.get("OPENAI_API_KEY") or os.environ.get("LLM_API_KEY") or ""
MODEL = os.environ.get("LLM_MODEL") or "step-5-preview"
PNG = (
    "iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAYAAABytg0kAAAAFElEQVR4nGP8z8DAwMDAxMDAwMDAAAAN"
    "HQEDasKb6QAAAABJRU5ErkJggg=="
)

print(f"base={BASE} model={MODEL} key={'set' if KEY else 'missing'}")


async def try_case(label: str, content):
    client = AsyncOpenAI(api_key=KEY, base_url=BASE, timeout=60.0)
    try:
        r = await client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": content}],
            max_tokens=64,
        )
        text = (r.choices[0].message.content or "").strip().replace("\n", " ")[:120]
        print(f"[{label}] OK -> {text!r}")
        return True
    except Exception as exc:  # noqa: BLE001 — 探针：把真实异常类型打出来
        print(f"[{label}] FAIL {type(exc).__name__}: {str(exc).splitlines()[0][:200]}")
        return False
    finally:
        await client.close()


async def main():
    await try_case("text-only", "说 PONG")
    await try_case(
        "image_url",
        [
            {"type": "text", "text": "这张图是什么颜色？只回答颜色。"},
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{PNG}"}},
        ],
    )


asyncio.run(main())
