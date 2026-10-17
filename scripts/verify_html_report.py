"""用真实 Chromium 验证变更报告的交互。

## 为什么需要这个脚本

HTML 报告里的测验是**交付物的一部分**：用户要求"我必须通过"。
只检查文件存在或 HTML 结构正确，证明不了点击后会发生什么。

本脚本真实驱动浏览器，覆盖三条路径：

1. 页面加载后 8 道题全部渲染
2. 全选正确答案 → 判定"通过"，分数 8/8
3. 故意错一题 → 判定"未通过"，并显示正确答案标色

用法：
    python scripts/verify_html_report.py 计划书/变更报告-v0.57.0.html
"""

from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright


def verify(html_path: Path) -> int:
    failures: list[str] = []

    with sync_playwright() as pw:
        # 优先用 Playwright 自带 Chromium；未下载时回退到系统已装的 Edge/Chrome。
        # 这样 CI 与本机都能跑，不必为了验证一张报告额外下载 ~100MB。
        browser = None
        for kwargs in ({}, {"channel": "msedge"}, {"channel": "chrome"}):
            try:
                browser = pw.chromium.launch(**kwargs)
                print(f"[0] 浏览器: {kwargs or 'bundled chromium'}")
                break
            except Exception:
                continue
        if browser is None:
            raise SystemExit("找不到可用浏览器：请运行 `playwright install chromium`，或安装 Edge/Chrome")
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.goto(html_path.resolve().as_uri())
        page.wait_for_load_state("networkidle")

        questions = page.locator(".q")
        n = questions.count()
        answers = page.evaluate("QUESTIONS.map(q => q.answer)")
        print(f"[1] 渲染题目数: {n}（页面定义 {len(answers)} 题）")
        if n != len(answers):
            failures.append(f"渲染题数 {n} 与定义数 {len(answers)} 不一致")
        if n == 0:
            failures.append("页面没有任何题目")

        print(f"[2] 页面内答案索引: {answers}")

        # --- 路径 A：全对 ---
        for i, ans in enumerate(answers):
            page.locator(f'.q[data-i="{i}"] input[value="{ans}"]').check()
        page.click("#submit")
        page.wait_for_timeout(150)
        verdict = page.locator("#verdict").inner_text()
        score = page.locator("#score").inner_text()
        print(f"[3] 全对判定: score={score} verdict={verdict[:32]!r}")
        if "通过" not in verdict or "未通过" in verdict:
            failures.append(f"全对时应判定通过，实际: {verdict}")
        if score.strip() != str(n):
            failures.append(f"全对时得分应为 {n}，实际 {score}")

        # 每题都应有解释且可见
        explained = page.locator(".explain.show").count()
        print(f"[4] 已显示解释的题目数: {explained}")
        if explained != n:
            failures.append(f"应有 {n} 条解释，实际 {explained}")

        # --- 路径 B：故意错一题 ---
        page.click("#reset")
        page.wait_for_timeout(100)
        wrong = (answers[0] + 1) % 4
        page.locator(f'.q[data-i="0"] input[value="{wrong}"]').check()
        for i, ans in enumerate(answers[1:], start=1):
            page.locator(f'.q[data-i="{i}"] input[value="{ans}"]').check()
        page.click("#submit")
        page.wait_for_timeout(150)
        verdict2 = page.locator("#verdict").inner_text()
        score2 = page.locator("#score").inner_text()
        print(f"[5] 错一题判定: score={score2} verdict={verdict2[:32]!r}")
        if "未通过" not in verdict2:
            failures.append(f"错一题时应判定未通过，实际: {verdict2}")
        if score2.strip() != str(n - 1):
            failures.append(f"错一题时得分应为 {n-1}，实际 {score2}")

        # 错误项应被标红，正确项应被标绿
        wrong_marked = page.locator(".opt.wrong").count()
        correct_marked = page.locator(".opt.correct").count()
        print(f"[6] 标记: wrong={wrong_marked} correct={correct_marked}")
        if wrong_marked != 1:
            failures.append(f"应有 1 个错误选项被标红，实际 {wrong_marked}")
        if correct_marked != n:
            failures.append(f"应有 {n} 个正确选项被标绿，实际 {correct_marked}")

        browser.close()

    print()
    if failures:
        print("=== 失败 ===")
        for f in failures:
            print("  -", f)
        return 1
    print("=== 全部通过（3 条路径 / 6 项断言）===")
    return 0


if __name__ == "__main__":
    target = Path(sys.argv[1] if len(sys.argv) > 1 else "计划书/变更报告-v0.57.0.html")
    if not target.exists():
        print(f"找不到文件: {target}")
        raise SystemExit(2)
    raise SystemExit(verify(target))
