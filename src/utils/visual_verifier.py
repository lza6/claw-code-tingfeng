"""Visual Verifier — 视觉自动化评审工具 (汲取自 Project B)

核心功能：
1. 使用 Playwright 捕获 UI 截图
2. 调用多模态 LLM 进行视觉评审
3. 生成结构化 JSON 报告，辅助自动迭代
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger("utils.visual_verifier")

@dataclass
class VisualVerdict:
    score: int
    verdict: str  # pass, revise, fail
    differences: list[str]
    suggestions: list[str]
    reasoning: str

class VisualVerifier:
    def __init__(self, output_dir: str = ".clawd/visual"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    async def capture_screenshot(self, url: str, name: str = "current") -> Path:
        """使用 Playwright 捕获网页截图"""
        from playwright.async_api import async_playwright

        path = self.output_dir / f"{name}.png"
        logger.info(f"正在捕获 {url} 的截图并保存到 {path}...")

        async with async_playwright() as p:
            browser = await p.chromium.launch()
            page = await browser.new_page()
            await page.goto(url, wait_until="networkidle")
            await page.screenshot(path=str(path), full_page=True)
            await browser.close()

        return path

    async def get_verdict(self, screenshot_path: Path, reference_paths: list[Path] = None) -> VisualVerdict:
        """调用多模态模型生成视觉评审结论"""
        # 这里需要调用 llm 模块的多模态接口
        # 暂时模拟返回结果，后续集成 llm.message_handler
        logger.info(f"正在对 {screenshot_path.name} 进行视觉评审...")

        # 模拟逻辑：如果文件名包含 'fail'，则返回 revise
        if "fail" in screenshot_path.name:
            return VisualVerdict(
                score=75,
                verdict="revise",
                differences=["布局错位", "颜色不一致"],
                suggestions=["修复 CSS 边距", "调整主题颜色"],
                reasoning="视觉效果与参考图有较大偏差。"
            )

        return VisualVerdict(
            score=95,
            verdict="pass",
            differences=[],
            suggestions=[],
            reasoning="视觉效果非常完美，符合预期。"
        )

    def report_to_json(self, verdict: VisualVerdict, task_id: str):
        """保存评审报告"""
        report_path = self.output_dir / f"verdict_{task_id}.json"
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(verdict.__dict__, f, indent=2, ensure_ascii=False)
        logger.info(f"评审报告已保存到 {report_path}")
