# 详细设计文档：剩余整合组件

## 📐 组件设计总览

本文档详细描述剩余需要整合的 OMX 特性的具体实现设计。

---

## 1️⃣ Pre-context Intake Gate 设计

### 1.1 设计目标

在每次 Pipeline 执行前，强制收集任务上下文，确保：
- 任务意图清晰
- 边界明确（Non-goals）
- 已知事实和约束
- 待办事项清单

### 1.2 快照格式

**文件位置：** `.clawd/context/{task-slug}-{timestamp}.md`

**必需字段：**
```markdown
# 任务上下文快照

**任务描述：**
{原始用户任务}

**期望成果：**
{明确的可交付成果}

**已知事实/证据：**
- 事实 1
- 事实 2

**约束条件：**
- 约束 1
- 约束 2

**未解决问题：**
- 问题 1
- 问题 2

**可能涉及的代码区域：**
- 文件路径 1
- 文件路径 2

**快照时间：** {ISO 8601 时间戳}
**版本：** v1
```

### 1.3 核心实现

**文件：** `src/workflow/intake.py`

```python
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict
import uuid

class ContextSnapshotManager:
    """上下文快照管理器"""
    
    def __init__(self, workdir: Path):
        self.workdir = workdir
        self.snapshot_dir = workdir / ".clawd" / "context"
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)
    
    def generate_slug(self, task: str) -> str:
        """从任务生成文件系统安全的 slug"""
        # 转小写
        slug = task.lower()
        # 移除非字母数字字符（保留连字符）
        slug = re.sub(r'[^a-z0-9\s-]', '', slug)
        # 空格转连字符
        slug = re.sub(r'\s+', '-', slug.strip())
        # 压缩多个连字符
        slug = re.sub(r'-+', '-', slug)
        # 限制长度
        return slug[:50]
    
    def create_snapshot(
        self,
        task: str,
        fields: Dict[str, str],
        version: int = 1,
    ) -> Path:
        """创建新的上下文快照"""
        slug = self.generate_slug(task)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        filename = f"{slug}-{timestamp}.md"
        filepath = self.snapshot_dir / filename
        
        # 必需字段验证
        required = [
            "task", "outcome", "facts", "constraints",
            "unknowns", "touchpoints"
        ]
        for field in required:
            if field not in fields:
                raise ValueError(f"Missing required field: {field}")
        
        # 生成 Markdown 内容
        content = self._render_markdown(task, fields, version, timestamp)
        
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        
        return filepath
    
    def find_latest_snapshot(self, slug: str) -> Optional[Path]:
        """查找指定 slug 的最新快照"""
        pattern = f"{slug}-*.md"
        matches = list(self.snapshot_dir.glob(pattern))
        if not matches:
            return None
        # 按时间戳排序
        matches.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        return matches[0]
    
    def load_snapshot(self, path: Path) -> Dict[str, str]:
        """加载快照并解析字段（简单实现）"""
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # 解析 Markdown（简化版）
        fields = {}
        current_field = None
        
        for line in content.split('\n'):
            if line.startswith('**') and line.endswith(':**'):
                # 字段标题
                field_name = line.strip('*:').lower().replace(' ', '_')
                current_field = field_name
                fields[field_name] = ""
            elif current_field and line.strip():
                if fields[current_field]:
                    fields[current_field] += "\n" + line
                else:
                    fields[current_field] = line
        
        return fields
    
    def _render_markdown(
        self,
        task: str,
        fields: Dict[str, str],
        version: int,
        timestamp: str,
    ) -> str:
        """渲染 Markdown 快照"""
        lines = [
            f"# 任务上下文快照 (v{version})",
            "",
            f"**快照时间：** {timestamp}",
            f"**任务 ID：** {uuid.uuid4().hex[:8]}",
            "",
            "---",
            "",
            f"## 任务描述",
            "",
            fields.get("task", task),
            "",
            "## 期望成果",
            "",
            fields.get("outcome", "待明确"),
            "",
            "## 已知事实 / 证据",
            "",
            fields.get("facts", "无"),
            "",
            "## 约束条件",
            "",
            fields.get("constraints", "无"),
            "",
            "## 未解决问题",
            "",
            fields.get("unknowns", "无"),
            "",
            "## 可能涉及的代码区域",
            "",
            fields.get("touchpoints", "待探索"),
            "",
            "---",
            "",
            "*此快照由 Clawd Code 自动生成*",
        ]
        return "\n".join(lines)

class IntakeGate:
    """Pre-context Intake 门禁
    
    执行流程：
    1. 尝试复用现有快照
    2. 如不存在则创建新快照
    3. 评估任务清晰度
    4. 必要时调用 deep-interview 澄清
    """
    
    def __init__(self, workdir: Path, enable_clarification: bool = True):
        self.workdir = workdir
        self.snapshot_mgr = ContextSnapshotManager(workdir)
        self.enable_clarification = enable_clarification
    
    def process_task(self, task: str) -> Path:
        """处理任务，返回快照路径"""
        slug = self.snapshot_mgr.generate_slug(task)
        
        # 1. 尝试查找现有快照
        existing = self.snapshot_mgr.find_latest_snapshot(slug)
        if existing:
            print(f"[Intake] 复用现有快照: {existing.name}")
            return existing
        
        # 2. 创建新快照
        print(f"[Intake] 创建新上下文快照...")
        
        # 初始字段（可能为空）
        fields = {
            "task": task,
            "outcome": "",
            "facts": "",
            "constraints": "",
            "unknowns": "",
            "touchpoints": "",
        }
        
        # 如果需要澄清
        if self.enable_clarification:
            fields = self._clarify_task(task, fields)
        
        snapshot_path = self.snapshot_mgr.create_snapshot(task, fields)
        print(f"[Intake] 快照已创建: {snapshot_path}")
        
        return snapshot_path
    
    def _clarify_task(self, task: str, fields: Dict[str, str]) -> Dict[str, str]:
        """使用 deep-interview 澄清任务"""
        # TODO: 调用 deep-interview skill
        # 临时返回原字段
        return fields
```

### 1.4 与 Pipeline 集成

在 `PipelineOrchestrator.run()` 开始时调用：

```python
from .intake import IntakeGate

async def run(self, task: str, ...):
    # Pre-context Intake Gate
    intake = IntakeGate(self.workdir)
    snapshot_path = intake.process_task(task)
    self._logger.info(f"Context snapshot: {snapshot_path}")
    
    # 将快照路径记录到 state
    self._state.artifacts["context_snapshot"] = str(snapshot_path)
    
    # 继续执行...
```

---

## 2️⃣ AI Slop Cleaner 设计

### 2.1 设计目标

自动识别并移除代码中的 AI 生成冗余：
- 自明性注释
- 过度详细的变量名
- 重复的代码块
- 未使用的导入/函数

### 2.2 核心算法

**文件：** `src/tools/slops_cleaner.py`

```python
import ast
import re
from pathlib import Path
from typing import List, Tuple, Optional
from dataclasses import dataclass

@dataclass
class SlopIssue:
    """冗余代码问题"""
    type: str  # "obvious_comment", "dead_code", "redundant_assignment"
    line: int
    message: str
    severity: str  # "low", "medium", "high"
    suggestion: Optional[str] = None

class SlopCleaner:
    """AI 代码脱水器"""
    
    # 自明性注释模式
    OBVIOUS_COMMENT_PATTERNS = [
        (r'# increment \w+ by \d+', '自明性注释：增量操作'),
        (r'# decrement \w+ by \d+', '自明性注释：减量操作'),
        (r'# set \w+ to \w+', '自明性注释：赋值操作'),
        (r'# assign \w+', '自明性注释：赋值'),
        (r'# loop over \w+', '自明性注释：循环'),
        (r'# iterate \w+', '自明性注释：迭代'),
        (r'# check if \w+', '自明性注释：条件检查'),
        (r'# return \w+', '自明性注释：返回值'),
    ]
    
    # 死代码模式
    DEAD_CODE_PATTERNS = [
        (r'^\s*#.*TODO.*', 'TODO 注释（应尽快处理）'),
        (r'^\s*#.*FIXME.*', 'FIXME 注释（需要修复）'),
        (r'^\s*#.*HACK.*', 'HACK 注释（临时方案）'),
    ]
    
    def __init__(self, workdir: Path, aggressive: bool = False):
        self.workdir = workdir
        self.aggressive = aggressive  # 激进模式：移除更多内容
    
    def clean_file(self, filepath: Path) -> Tuple[bool, str, List[SlopIssue]]:
        """清理单个文件
        
        Returns:
            (是否有修改, 新内容, 问题列表)
        """
        with open(filepath, 'r', encoding='utf-8') as f:
            original = f.read()
        
        issues = self.detect_slop(original)
        cleaned = self._apply_cleaning(original, issues)
        
        return (cleaned != original, cleaned, issues)
    
    def detect_slop(self, content: str) -> List[SlopIssue]:
        """检测代码中的冗余"""
        issues = []
        lines = content.split('\n')
        
        for i, line in enumerate(lines, 1):
            # 1. 自明性注释
            for pattern, message in self.OBVIOUS_COMMENT_PATTERNS:
                if re.search(pattern, line, re.IGNORECASE):
                    issues.append(SlopIssue(
                        type="obvious_comment",
                        line=i,
                        message=message,
                        severity="low",
                        suggestion="移除该注释，代码已自明"
                    ))
            
            # 2. 死代码标记
            for pattern, message in self.DEAD_CODE_PATTERNS:
                if re.search(pattern, line, re.IGNORECASE):
                    issues.append(SlopIssue(
                        type="dead_code_marker",
                        line=i,
                        message=message,
                        severity="medium",
                        suggestion="尽快处理或删除该代码段"
                    ))
            
            # 3. 重复的空行（>2 连续空行）
            if line.strip() == '' and i > 1:
                # 检查前一行
                if lines[i-2].strip() == '':
                    issues.append(SlopIssue(
                        type="excessive_blank_lines",
                        line=i,
                        message="过多空行",
                        severity="low",
                        suggestion="保留最多 2 个连续空行"
                    ))
        
        # 4. AST 级别：未使用的变量
        try:
            tree = ast.parse(content)
            for node in ast.walk(tree):
                if isinstance(node, ast.Assign):
                    # 简单检测：赋值后未使用的变量
                    # 完整实现需要构建作用域分析
                    pass
        except SyntaxError:
            pass  # 语法错误文件跳过
        
        return issues
    
    def _apply_cleaning(
        self,
        content: str,
        issues: List[SlopIssue],
    ) -> str:
        """应用清理规则"""
        lines = content.split('\n')
        
        # 按行号倒序排序，避免删除影响后续行号
        issues.sort(key=lambda x: x.line, reverse=True)
        
        for issue in issues:
            if issue.type == "obvious_comment":
                # 移除自明性注释（保留代码）
                line = lines[issue.line - 1]
                # 分离代码和注释
                code_part = line.split('#')[0].rstrip()
                if code_part:
                    lines[issue.line - 1] = code_part
                else:
                    # 整行是注释，删除
                    del lines[issue.line - 1]
            
            elif issue.type == "excessive_blank_lines":
                # 合并多余空行
                # 由后处理逻辑统一处理
                pass
        
        # 后处理：压缩连续空行到最多 2 个
        result = []
        blank_count = 0
        for line in lines:
            if line.strip() == '':
                blank_count += 1
                if blank_count <= 2:
                    result.append(line)
            else:
                blank_count = 0
                result.append(line)
        
        return '\n'.join(result)
    
    def clean_files(
        self,
        filepaths: List[Path],
    ) -> Dict[Path, Tuple[bool, str, List[SlopIssue]]]:
        """批量清理文件"""
        results = {}
        for path in filepaths:
            results[path] = self.clean_file(path)
        return results
```

### 2.3 CLI 封装

**入口：** `python -m src.tools.slops_cleaner`

```python
# src/tools/__init__.py
from .slops_cleaner import main

if __name__ == "__main__":
    main()
```

**命令行参数：**
```bash
python -m src.tools.slops_cleaner \
    --files src/foo.py src/bar.py \
    [--aggressive] \
    [--dry-run] \
    [--report report.md]
```

---

## 3️⃣ Visual Verdict 设计

### 3.1 设计目标

截图对比验证，确保 UI 修改符合预期。

### 3.2 核心实现

**文件：** `src/tools/visual_verdict.py`

```python
from pathlib import Path
from typing import Dict, List, Tuple
from dataclasses import dataclass
import json

try:
    from PIL import Image, ImageChops
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

@dataclass
class VisualDifference:
    """视觉差异"""
    region: str  # "button", "header", etc.
    change_type: str  # "color", "position", "size"
    before_bbox: Tuple[int, int, int, int]
    after_bbox: Tuple[int, int, int, int]
    severity: str  # "minor", "major", "critical"

@dataclass
class VerdictResult:
    """验证结果"""
    score: int  # 0-100
    verdict: str  # "pass" | "fail"
    category_match: bool
    differences: List[VisualDifference]
    suggestions: List[str]
    reasoning: str

class VisualVerdictEngine:
    """视觉验证引擎"""
    
    def __init__(
        self,
        threshold: float = 0.90,  # 90% 相似度阈值
        min_diff_area: int = 100,  # 最小差异面积
    ):
        self.threshold = threshold
        self.min_diff_area = min_diff_area
        
        if not HAS_PIL:
            raise ImportError(
                "Pillow is required for visual verification. "
                "Install with: pip install Pillow"
            )
    
    def compare(
        self,
        before_path: Path,
        after_path: Path,
        regions: Dict[str, Tuple[int, int, int, int]] | None = None,
    ) -> VerdictResult:
        """对比两张截图"""
        
        # 1. 加载图像
        before = Image.open(before_path).convert('RGB')
        after = Image.open(after_path).convert('RGB')
        
        # 尺寸检查
        if before.size != after.size:
            return VerdictResult(
                score=0,
                verdict="fail",
                category_match=False,
                differences=[],
                suggestions=["截图尺寸不一致"],
                reasoning="尺寸不匹配无法比较"
            )
        
        # 2. 计算整体相似度
        similarity = self._calculate_similarity(before, after)
        score = int(similarity * 100)
        
        # 3. 差异区域检测
        differences = []
        if regions:
            for region_name, bbox in regions.items():
                diff = self._compare_region(before, after, bbox)
                if diff:
                    differences.append(VisualDifference(
                        region=region_name,
                        change_type=diff,
                        before_bbox=bbox,
                        after_bbox=bbox,
                        severity=self._assess_severity(diff)
                    ))
        
        # 4. 判定
        verdict = "pass" if similarity >= self.threshold else "fail"
        
        # 5. 生成建议
        suggestions = self._generate_suggestions(differences, score)
        
        return VerdictResult(
            score=score,
            verdict=verdict,
            category_match=(score >= 85),
            differences=differences,
            suggestions=suggestions,
            reasoning=f"整体相似度: {similarity:.2%}"
        )
    
    def _calculate_similarity(
        self,
        img1: Image.Image,
        img2: Image.Image,
    ) -> float:
        """计算两张图像的相似度（简化 SSIM）"""
        import numpy as np
        
        # 转换为 numpy 数组
        arr1 = np.array(img1).astype(float)
        arr2 = np.array(img2).astype(float)
        
        # 计算均方误差 (MSE)
        mse = np.mean((arr1 - arr2) ** 2)
        if mse == 0:
            return 1.0
        
        # 转换为相似度（简化）
        max_val = 255.0 ** 2
        similarity = 1 - (mse / max_val)
        return max(0, similarity)
    
    def _compare_region(
        self,
        before: Image.Image,
        after: Image.Image,
        bbox: Tuple[int, int, int, int],
    ) -> Optional[str]:
        """对比指定区域"""
        region_before = before.crop(bbox)
        region_after = after.crop(bbox)
        
        # 检查颜色变化
        diff = ImageChops.difference(region_before, region_after)
        bbox_diff = diff.getbbox()
        
        if bbox_diff is None:
            return None  # 无差异
        
        area = (bbox_diff[2] - bbox_diff[0]) * (bbox_diff[3] - bbox_diff[1])
        if area < self.min_diff_area:
            return None  # 差异太小，忽略
        
        # 判断变化类型
        return "color"  # 简化实现
    
    def _assess_severity(self, change_type: str) -> str:
        """评估差异严重程度"""
        severity_map = {
            "color": "minor",
            "position": "major",
            "size": "major",
            "missing": "critical",
            "extra": "critical",
        }
        return severity_map.get(change_type, "minor")
    
    def _generate_suggestions(
        self,
        differences: List[VisualDifference],
        score: int,
    ) -> List[str]:
        """生成建议"""
        suggestions = []
        
        if score < 70:
            suggestions.append("视觉差异过大，请检查实现是否正确")
        
        for diff in differences:
            if diff.severity == "critical":
                suggestions.append(
                    f"区域 '{diff.region}' 出现严重变化，请确认是否预期"
                )
        
        return suggestions

def verdict_cli():
    """命令行接口"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Visual Verdict - 截图对比验证")
    parser.add_argument("--before", type=Path, required=True, help="修改前截图")
    parser.add_argument("--after", type=Path, required=True, help="修改后截图")
    parser.add_argument("--threshold", type=float, default=0.90, help="相似度阈值")
    parser.add_argument("--output", type=Path, help="输出 JSON 结果")
    parser.add_argument("--regions", type=Path, help="区域定义 JSON")
    
    args = parser.parse_args()
    
    engine = VisualVerdictEngine(threshold=args.threshold)
    
    regions = None
    if args.regions:
        with open(args.regions) as f:
            regions = json.load(f)
    
    result = engine.compare(args.before, args.after, regions)
    
    # 输出 JSON
    output = {
        "score": result.score,
        "verdict": result.verdict,
        "category_match": result.category_match,
        "differences": [
            {
                "region": d.region,
                "change_type": d.change_type,
                "severity": d.severity,
            }
            for d in result.differences
        ],
        "suggestions": result.suggestions,
        "reasoning": result.reasoning,
    }
    
    if args.output:
        with open(args.output, 'w') as f:
            json.dump(output, f, indent=2)
    else:
        print(json.dumps(output, indent=2))
```

### 3.3 与 Ralph 集成

在 Ralph 循环的 Visual Task Gate 步骤：

```python
# Ralph 循环中
if screenshot_available:
    verdict = visual_verdict.compare(before, after)
    if verdict.score < 90:
        # 不通过，继续修复
        continue
```

---

## 4️⃣ ModeState 状态管理设计

### 4.1 设计目标

提供统一的跨会话状态持久化机制，支持：
- 多模式状态隔离（pipeline, ralph, team）
- 自动保存/加载
- 状态迁移（版本兼容）
- HUD 实时显示

### 4.2 核心实现

**文件：** `src/core/mode_state.py`

```python
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Optional, Dict
from uuid import uuid4

class ModeStateStatus(Enum):
    ACTIVE = "active"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"

@dataclass
class ModeState:
    """模式状态基类"""
    mode_name: str
    status: ModeStateStatus
    session_id: str
    created_at: str
    updated_at: str
    data: Dict[str, Any] = field(default_factory=dict)
    version: str = "1.0"
    
    def to_dict(self) -> dict:
        """序列化为字典"""
        d = asdict(self)
        d["status"] = self.status.value
        return d
    
    @classmethod
    def from_dict(cls, data: dict) -> ModeState:
        """从字典反序列化"""
        data["status"] = ModeStateStatus(data["status"])
        return cls(**data)
    
    def touch(self):
        """更新修改时间"""
        self.updated_at = datetime.now(timezone.utc).isoformat()

class ModeStateManager:
    """模式状态管理器
    
    单例模式，全局访问
    """
    
    _instance: Optional[ModeStateManager] = None
    
    def __init__(self, workdir: Path):
        self.workdir = workdir
        self.state_dir = workdir / ".clawd" / "state"
        self.state_dir.mkdir(parents=True, exist_ok=True)
        
        self._states: Dict[str, ModeState] = {}
        self._lock_file = self.state_dir / ".lock"
    
    @classmethod
    def get_instance(cls, workdir: Optional[Path] = None) -> ModeStateManager:
        """获取单例实例"""
        if cls._instance is None:
            if workdir is None:
                workdir = Path.cwd()
            cls._instance = cls(workdir)
        return cls._instance
    
    def start_mode(
        self,
        mode: str,
        total_steps: Optional[int] = None,
        initial_data: Optional[Dict] = None,
    ) -> ModeState:
        """启动新模式"""
        # 如果已有活跃的同名模式，先取消
        if mode in self._states:
            existing = self._states[mode]
            if existing.status == ModeStateStatus.ACTIVE:
                self.cancel_mode(mode)
        
        # 创建新状态
        now = datetime.now(timezone.utc).isoformat()
        state = ModeState(
            mode_name=mode,
            status=ModeStateStatus.ACTIVE,
            session_id=uuid4().hex[:12],
            created_at=now,
            updated_at=now,
            data={
                "total_steps": total_steps,
                "current_step": 0,
                "current_phase": "starting",
                **(initial_data or {}),
            },
        )
        
        self._states[mode] = state
        self._persist(state)
        
        return state
    
    def update_mode(
        self,
        mode: str,
        updates: Dict[str, Any],
    ) -> bool:
        """更新模式状态"""
        state = self._states.get(mode)
        if not state:
            return False
        
        state.data.update(updates)
        state.touch()
        self._persist(state)
        return True
    
    def read_mode(self, mode: str) -> Optional[ModeState]:
        """读取模式状态"""
        # 先从内存读取
        if mode in self._states:
            return self._states[mode]
        
        # 从磁盘加载
        state_file = self.state_dir / f"{mode}-state.json"
        if state_file.exists():
            try:
                with open(state_file, 'r') as f:
                    data = json.load(f)
                state = ModeState.from_dict(data)
                self._states[mode] = state
                return state
            except Exception as e:
                print(f"[ModeState] 加载失败: {e}")
        
        return None
    
    def cancel_mode(self, mode: str) -> bool:
        """取消模式"""
        state = self._states.get(mode)
        if not state:
            return False
        
        state.status = ModeStateStatus.CANCELLED
        state.touch()
        self._persist(state)
        
        # 从内存移除
        del self._states[mode]
        return True
    
    def list_active_modes(self) -> list[str]:
        """列出所有活跃模式"""
        active = []
        for mode, state in self._states.items():
            if state.status == ModeStateStatus.ACTIVE:
                active.append(mode)
        return active
    
    def _persist(self, state: ModeState) -> None:
        """持久化状态到磁盘"""
        state_file = self.state_dir / f"{state.mode_name}-state.json"
        try:
            with open(state_file, 'w') as f:
                json.dump(state.to_dict(), f, indent=2)
        except Exception as e:
            print(f"[ModeState] 持久化失败: {e}")
    
    def cleanup(self) -> None:
        """清理所有状态文件（测试用）"""
        for state_file in self.state_dir.glob("*-state.json"):
            try:
                state_file.unlink()
            except:
                pass
```

### 4.3 全局访问

```python
# 使用方式
from src.core.mode_state import ModeStateManager

# 获取实例
mgr = ModeStateManager.get_instance(Path.cwd())

# 启动模式
state = mgr.start_mode("pipeline", total_steps=3)

# 更新进度
mgr.update_mode("pipeline", {
    "current_step": 1,
    "current_phase": "stage:ralplan"
})

# 读取状态
state = mgr.read_mode("pipeline")
print(f"当前阶段: {state.data['current_phase']}")
```

---

## 5️⃣ Team Runtime 协调设计

### 5.1 设计目标

在 Python 端模拟 OMX 的 Team 协调能力：
- 任务分派 (Dispatch)
- 消息队列 (Mailbox)
- 生命周期管理
- Worktree 隔离

### 5.2 Mailbox 实现

**文件：** `src/agent/swarm/mailbox.py`

```python
from __future__ import annotations

import json
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Dict
from uuid import uuid4

@dataclass
class Message:
    """消息"""
    id: str
    from_agent: str
    to_agent: str
    subject: str
    body: str
    timestamp: str
    ack: bool = False

class Mailbox:
    """基于文件系统的邮箱"""
    
    def __init__(
        self,
        team_name: str,
        state_root: Path,
        agent_id: str,
    ):
        self.team_name = team_name
        self.state_root = state_root
        self.agent_id = agent_id
        
        # 邮箱目录
        self.inbox_dir = (
            state_root / "team" / team_name / "mailbox" / agent_id / "inbox"
        )
        self.outbox_dir = (
            state_root / "team" / team_name / "mailbox" / agent_id / "outbox"
        )
        self.inbox_dir.mkdir(parents=True, exist_ok=True)
        self.outbox_dir.mkdir(parents=True, exist_ok=True)
    
    def send(self, to_agent: str, subject: str, body: str) -> str:
        """发送消息"""
        msg = Message(
            id=uuid4().hex[:8],
            from_agent=self.agent_id,
            to_agent=to_agent,
            subject=subject,
            body=body,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
        
        # 写入收件人邮箱
        target_inbox = (
            self.state_root / "team" / self.team_name / "mailbox"
            / to_agent / "inbox"
        )
        target_inbox.mkdir(parents=True, exist_ok=True)
        
        msg_file = target_inbox / f"{msg.id}.json"
        with open(msg_file, 'w') as f:
            json.dump(asdict(msg), f, indent=2)
        
        return msg.id
    
    def receive(self) -> List[Message]:
        """读取所有未读消息"""
        messages = []
        for msg_file in self.inbox_dir.glob("*.json"):
            with open(msg_file, 'r') as f:
                data = json.load(f)
            msg = Message(**data)
            messages.append(msg)
        
        # 按时间排序
        messages.sort(key=lambda m: m.timestamp)
        return messages
    
    def ack(self, msg_id: str) -> None:
        """确认消息已读"""
        msg_file = self.inbox_dir / f"{msg_id}.json"
        if msg_file.exists():
            # 移动到已读或删除
            msg_file.unlink()
```

### 5.3 Dispatch 实现

**文件：** `src/agent/swarm/dispatch.py`

```python
from typing import List, Dict, Optional
from pathlib import Path
from .mailbox import Mailbox, Message

class TaskDispatcher:
    """任务分发器"""
    
    def __init__(
        self,
        team_name: str,
        state_root: Path,
        leader_id: str,
    ):
        self.team_name = team_name
        self.state_root = state_root
        self.leader_id = leader_id
        self.mailbox = Mailbox(team_name, state_root, leader_id)
    
    def dispatch_task(
        self,
        worker_id: str,
        task: Dict[str, Any],
    ) -> str:
        """分发任务给 worker"""
        subject = f"task:{task.get('id', 'unnamed')}"
        body = json.dumps(task, ensure_ascii=False, indent=2)
        
        msg_id = self.mailbox.send(worker_id, subject, body)
        return msg_id
    
    def collect_results(
        self,
        worker_ids: List[str],
        timeout: float = 30.0,
    ) -> List[Message]:
        """收集 worker 结果"""
        import time
        start = time.time()
        results = []
        
        while time.time() - start < timeout:
            for worker_id in worker_ids:
                worker_mailbox = Mailbox(
                    self.team_name, self.state_root, worker_id
                )
                messages = worker_mailbox.receive()
                results.extend(messages)
            
            if results:
                break
            
            time.sleep(0.5)
        
        return results
```

### 5.4 Team Orchestrator

**文件：** `src/agent/swarm/team_orchestrator.py`

```python
from typing import List, Dict
from pathlib import Path
from dataclasses import dataclass, field
from .dispatch import TaskDispatcher
from .mailbox import Mailbox

@dataclass
class WorkerSpec:
    """Worker 规范"""
    id: str
    role: str  # "executor", "architect", "auditor"
    model: Optional[str] = None
    worktree: Optional[str] = None

@dataclass
class TeamManifest:
    """Team 清单"""
    team_name: str
    leader_id: str
    workers: List[WorkerSpec]
    tasks: List[Dict] = field(default_factory=list)
    state: str = "initializing"  # initializing, running, completed, failed

class TeamOrchestrator:
    """Team 协调器（简化版，不依赖 tmux）"""
    
    def __init__(
        self,
        team_name: str,
        state_root: Path,
        leader_id: str,
    ):
        self.team_name = team_name
        self.state_root = state_root
        self.leader_id = leader_id
        self.manifest_file = (
            state_root / "team" / team_name / "manifest.v2.json"
        )
        
        self.dispatcher = TaskDispatcher(team_name, state_root, leader_id)
        self.manifest = self._load_or_create_manifest()
    
    def add_worker(self, worker: WorkerSpec) -> None:
        """添加 worker"""
        self.manifest.workers.append(worker)
        self._save_manifest()
    
    def assign_task(self, task: Dict) -> None:
        """分配任务给所有 worker（广播）"""
        for worker in self.manifest.workers:
            self.dispatcher.dispatch_task(worker.id, task)
    
    def wait_completion(self, timeout: float = 60.0) -> List[Dict]:
        """等待所有任务完成"""
        worker_ids = [w.id for w in self.manifest.workers]
        messages = self.dispatcher.collect_results(worker_ids, timeout)
        return [json.loads(m.body) for m in messages]
    
    def _load_or_create_manifest(self) -> TeamManifest:
        """加载或创建清单"""
        self.manifest_file.parent.mkdir(parents=True, exist_ok=True)
        
        if self.manifest_file.exists():
            with open(self.manifest_file, 'r') as f:
                data = json.load(f)
            return TeamManifest(**data)
        
        return TeamManifest(
            team_name=self.team_name,
            leader_id=self.leader_id,
            workers=[],
        )
    
    def _save_manifest(self) -> None:
        """保存清单"""
        with open(self.manifest_file, 'w') as f:
            json.dump(asdict(self.manifest), f, indent=2)
```

### 5.5 与现有系统集成

**集成到 WorkflowEngine：**

```python
# src/workflow/engine.py (扩展)
from .team_coordinator import TeamOrchestrator

class WorkflowEngine:
    async def _execute_with_team(
        self,
        task: str,
        worker_count: int,
    ) -> Dict[str, Any]:
        """使用 Team 模式执行"""
        team = TeamOrchestrator(
            team_name=f"team-{uuid4().hex[:8]}",
            state_root=self.workdir / ".clawd" / "state",
            leader_id="leader",
        )
        
        # 添加 workers
        for i in range(worker_count):
            team.add_worker(WorkerSpec(
                id=f"worker-{i}",
                role="executor",
            ))
        
        # 分配任务
        team.assign_task({"task": task, "type": "implementation"})
        
        # 等待结果
        results = team.wait_completion(timeout=300.0)
        
        return {"results": results}
```

---

## 6️⃣ AGENTS.md 模板增强

### 6.1 新增内容

**文件：** `AGENTS.md` (根目录，更新)

```markdown
# Agent 指南 - Clawd Code

## Agent Tiers (能力等级)

在执行任务时，根据复杂度选择合适的 agent tier：

| Tier | 适用场景 | 期望质量 | 示例 |
|------|----------|----------|------|
| **LOW** | 简单查询、信息查找 | 快速响应 | "这个函数返回什么？" |
| **STANDARD** | 标准实现、常规修改 | 生产就绪 | "添加错误处理" |
| **THOROUGH** | 复杂重构、安全敏感 | 严格审查 | "重构认证模块支持 OAuth2" |

### Tier 选择指南

```python
# 在技能或代码中指定 tier
delegate(role="executor", tier="LOW", task="...")
delegate(role="architect", tier="THOROUGH", task="...")
```

---

## Pre-context Intake Gate

**在执行任何实质性工作前，必须完成：**

1. **创建上下文快照** (`.clawd/context/`)
   - 任务描述
   - 期望成果
   - 已知事实
   - 约束条件
   - 未解决问题
   - 代码涉及区域

2. **评估清晰度**
   - 如果任务模糊，运行 `$deep-interview --quick <task>`
   - 将澄清结果合并到快照

3. **快照复用**
   - 相同任务的后续迭代，尝试复用最新快照
   - 记录快照路径到执行状态

---

## Deslop Pass (代码脱水)

**每次 Ralph 循环完成后，必须执行：**

1. 识别本次会话修改的文件
2. 运行 `oh-my-codex:ai-slop-cleaner` (standard mode)
3. 检查是否有回归
4. 如果回归，回滚或修复

**Deslop 跳过条件：**
- 用户明确指定 `--no-deslop`
- 修改的文件不包含代码（仅文档）

---

## Visual Verdict 使用

**针对 UI/截图相关的任务：**

1. 保存修改前截图到 `.clawd/visual/before.png`
2. 执行修改
3. 保存修改后截图到 `.clawd/visual/after.png`
4. 运行 `$visual-verdict --before ... --after ...`
5. 检查 `score >= 90`，否则继续修复

---

## Team Mode 规范

**使用 `$team` 进行多代理协作：**

### 前置条件
- tmux 已安装（Windows: psmux）
- 当前会话在 tmux 内
- 已有上下文快照

### Worker 分配策略

| 任务类型 | 推荐 Worker 数 | Agent Type |
|----------|---------------|------------|
| 独立子任务 | 3-5 | executor |
| 复杂分析 | 2-3 | architect |
| 验证测试 | 2 | auditor |

### 生命周期

```
启动 → 就绪 → 执行 → 验证 → 完成/失败
```

---

## 最佳实践

1. **始终从 Intake 开始** - 不要跳过上下文收集
2. **Ralph 循环确保质量** - 不要提前宣称完成
3. **Deslop 保持代码简洁** - 每轮迭代后执行
4. **Visual Verdict 保障 UI** - 截图任务必须验证
5. **Team 提升并行度** - 独立任务同时执行

---

## 参考

- oh-my-codex 官方文档: https://yeachan-heo.github.io/oh-my-codex-website/
- Clawd Code 架构: `ARCHITECTURE.md`
```

---

## 7️⃣ 测试策略细化

### 7.1 单元测试覆盖

**Pipeline 测试：**
```python
# tests/workflow/test_pipeline.py
def test_pipeline_stage_skip():
    """测试阶段跳过逻辑"""
    
def test_pipeline_state_persistence():
    """测试状态持久化"""
    
def test_pipeline_resume():
    """测试恢复执行"""
```

**Intake 测试：**
```python
# tests/workflow/test_intake.py
def test_slug_generation():
    """测试 slug 生成"""
    
def test_snapshot_creation():
    """测试快照创建"""
    
def test_snapshot_reuse():
    """测试快照复用"""
```

**Slop Cleaner 测试：**
```python
# tests/tools/test_slops_cleaner.py
def test_obvious_comment_detection():
    """测试自明性注释检测"""
    
def test_clean_file():
    """测试文件清理"""
```

**Visual Verdict 测试：**
```python
# tests/tools/test_visual_verdict.py
def test_image_similarity():
    """测试相似度计算"""
    
def test_difference_detection():
    """测试差异检测"""
```

### 7.2 集成测试

```python
# tests/integration/test_pipeline_integration.py
async def test_full_pipeline():
    """测试完整 pipeline 流程"""
    
    # 1. Intake
    # 2. Ralplan
    # 3. Team Exec
    # 4. Ralph Verify + Deslop
    
    assert result["verification_result"] == "passed"
```

### 7.3 向后兼容性测试

```python
# tests/test_backward_compatibility.py
def test_existing_workflow_engine():
    """确保现有 WorkflowEngine 不受影响"""
    
def test_existing_skills():
    """确保现有技能系统正常工作"""
```

---

## 8️⃣ 依赖管理

### 8.1 新增依赖

**pyproject.toml 添加：**
```toml
[project.dependencies]
# 视觉验证
Pillow >= 10.0.0

# 可选：更高级的图像处理
# opencv-python >= 4.8.0  # 如果需要复杂图像分析
```

### 8.2 可选依赖

对于不需要的组件，使用可选依赖：
```python
try:
    from PIL import Image
    HAS_VISUAL = True
except ImportError:
    HAS_VISUAL = False
```

---

## 9️⃣ 配置管理

### 9.1 新增配置项

**`src/core/config/settings.py` 扩展：**

```python
@dataclass
class PipelineSettings:
    """Pipeline 配置"""
    enable_pipeline: bool = True
    enable_precontext_intake: bool = True
    enable_deslop_pass: bool = True
    enable_visual_verdict: bool = False  # 需要 Pillow
    
    # Ralph 设置
    default_max_iterations: int = 10
    require_architect_verification: bool = True
    
    # Team 设置
    default_worker_count: int = 2
    default_agent_type: str = "executor"
    
    # 视觉验证
    visual_similarity_threshold: float = 0.90

@dataclass
class SlopCleanerSettings:
    """Slop Cleaner 配置"""
    aggressive_mode: bool = False
    auto_deslop_on_ralph: bool = True
    excluded_patterns: List[str] = field(default_factory=list)
```

---

## 🔟 迁移指南

### 10.1 从现有 WorkflowEngine 迁移

旧 API 保持不变：
```python
# 旧方式（仍然有效）
from src.workflow.engine import WorkflowEngine
engine = WorkflowEngine()
result = await engine.run()
```

新 Pipeline API：
```python
# 新方式（推荐）
from src.workflow.pipeline import PipelineOrchestrator, create_autopilot_pipeline_config

config = create_autopilot_pipeline_config(
    task="实现用户认证",
    worker_count=3,
    max_ralph_iterations=15,
)
orchestrator = PipelineOrchestrator()
orchestrator.configure(config["stages"])
result = await orchestrator.run(config["task"])
```

### 10.2 技能系统迁移

现有技能无需修改。新增的技能放在对应分类目录下。

---

## 📊 监控指标

### 10.1 执行指标

- Pipeline 执行成功率
- 各阶段平均耗时
- Ralph 迭代次数分布
- Deslop 代码压缩率

### 10.2 质量指标

- 验证通过率
- 视觉匹配分数
- 代码冗余减少比例

### 10.3 日志

所有操作记录到：
- `.clawd/logs/workflow.jsonl` - 工作流日志
- `.clawd/logs/pipeline.jsonl` - Pipeline 详细日志
- `.clawd/logs/ralph.jsonl` - Ralph 循环日志

---

## 🚀 部署清单

### 代码合并前检查

- [ ] 所有新增文件通过 lint (ruff/black)
- [ ] 单元测试覆盖率 > 80%
- [ ] 集成测试通过
- [ ] 向后兼容性测试通过
- [ ] 文档更新（README, ARCHITECTURE.md）
- [ ] 更新 CHANGELOG.md

### 发布说明模板

```markdown
## [v0.51.0] - 2026-01-XX

### 新增特性

- **Pipeline 架构**：可配置的阶段式执行管道
- **Pre-context Intake**：任务执行前自动收集上下文
- **Ralph 增强循环**：强制验证 + Deslop 代码脱水
- **AI Slop Cleaner**：自动移除代码冗余
- **Visual Verdict**：截图对比验证
- **ModeState**：跨会话状态持久化
- **Team Runtime**：tmux 多代理协调（实验性）

### 改进

- 工作流引擎模块化
- 状态管理更健壮
- 技能系统重组

###  Breaking Changes

- 无（向后兼容）
```

---

## 📞 获取帮助

如遇到问题：
1. 查阅 `docs/` 目录
2. 运行 `python -m src.main doctor`
3. 查看 `.clawd/logs/` 日志
4. 提交 Issue

---

*文档版本：1.0 | 最后更新：2026-01-20*
