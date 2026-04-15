# Ralph Persistence - PRD/Progress 迁移与持久化增强

> 本文件汲取自 oh-my-codex-main/src/ralph/persistence.ts
> 提供 PRD 和 Progress 迁移、visual_feedback 记录支持

## PRD Migration

### 源文件
- Legacy: `.omx/prd.json` (read-only compatibility)
- Canonical: `.omx/plans/prd-{slug}.md`

### 迁移规则

1. **源文件识别顺序**:
   - `parsed.project`
   - `parsed.title`
   - `parsed.branchName`
   - `parsed.description`

2. **Slug 生成**:
   ```python
   def slugify(raw: str) -> str:
       return raw.lower() \
           .replace(/[^a-z0-9]+/g, '-') \
           .replace(/-+/g, '-') \
           .replace(/^-|-$/g, '') \
           .slice(0, 48) or 'legacy'
   ```

3. **Canonical PRD 格式**:
   ```markdown
   # {title}

   > Migrated from legacy `.omx/prd.json` (read-only compatibility import).

   ## Migration Marker
   - Source: `.omx/prd.json`
   - Source SHA256: `{sha256}`
   - Strategy: one-way conversion to canonical PRD markdown

   ## Legacy Snapshot
   ```json
   {legacy_json}
   ```
   ```

### 迁移检测
```python
async def migrate_legacy_prd_if_needed(cwd, existing_canonical_prd):
    if existing_canonical_prd:
        return {"canonicalPrdPath": existing_canonical_prd, "migrated": False}

    legacy_prd_path = join(cwd, ".omx/prd.json")
    if not exists(legacy_prd_path):
        return {"canonicalPrdPath": None, "migrated": False}

    # 执行迁移...
```

## Progress Migration

### 源文件
- Legacy: `.omx/progress.txt`
- Canonical: `.clawd/state/ralph-progress.json`

### 迁移规则
- 每行文本转换为: `{"index": N, "text": "line_content"}`
- 空行过滤掉

### Progress Ledger Schema
```python
@dataclass
class RalphProgressLedger:
    schema_version: int = 2
    source: str = ""           # 源文件路径
    source_sha256: str = ""    # 内容哈希
    strategy: str = ""         # 迁移策略
    created_at: str = ""      # ISO 时间戳
    updated_at: str = ""      # ISO 时间戳
    entries: list[dict] = []  # [{"index": N, "text": "..."}]
    visual_feedback: list[dict] = []  # 可选的视觉反馈数组
```

## Visual Feedback

### 记录格式
```python
@dataclass
class RalphVisualFeedback:
    score: int = 0           # 0-100 分数
    verdict: str = ""         # "pass" | "fail" | "partial"
    category_match: bool = True  # 类别匹配
    differences: list[str] = []  # 差异列表
    suggestions: list[str] = []    # 建议列表
    reasoning: str = ""       # 推理说明
    threshold: int = 90       # 及格阈值
```

### 记录到 Ledger
```python
async def record_ralph_visual_feedback(
    cwd: str,
    feedback: RalphVisualFeedback,
    session_id: str = None
):
    progress_path = join(
        get_state_dir(cwd, session_id),
        "ralph-progress.json"
    )
    ledger = await read_progress_ledger(progress_path)

    entry = {
        "recorded_at": now_iso(),
        "score": feedback.score,
        "verdict": feedback.verdict,
        "category_match": feedback.category_match,
        "threshold": feedback.threshold,
        "passes_threshold": feedback.score >= feedback.threshold,
        "differences": feedback.differences,
        "suggestions": feedback.suggestions,
        "reasoning": feedback.reasoning,
        "next_actions": generate_next_actions(feedback),
        "qualitative_feedback": {
            "summary": feedback.reasoning or feedback.verdict,
            "next_actions": generate_next_actions(feedback)[:30]
        }
    }

    ledger.visual_feedback.append(entry)
    ledger.visual_feedback = ledger.visual_feedback[-30:]  # 保留最近30条
    ledger.updated_at = now_iso()
    await write_progress_ledger(progress_path, ledger)
```

### Next Actions 限制
- 最大 30 条
- 来源: `suggestions` + `differences` 映射
- 每条截断到合理长度

## Migration Markers

### 标记文件
- 路径: `.omx/plans/ralph-migration-marker.json`

### 格式
```json
{
  "compatibility_window": "legacy-read-only-one-release-cycle",
  "prd_migration": {
    "source": ".omx/prd.json",
    "source_sha256": "...",
    "canonical_path": ".omx/plans/prd-{slug}.md",
    "strategy": "one-way-read-only"
  },
  "progress_migration": {
    "source": ".omx/progress.txt",
    "source_sha256": "...",
    "canonical_path": ".clawd/state/ralph-progress.json",
    "imported_entries": N,
    "strategy": "one-way-read-only"
  }
}
```

## Stable JSON

### 目的
生成确定性的 JSON 用于哈希和比较

### 实现
```python
def stable_json(value: Any) -> str:
    if value is None or type(value) not in (dict, list):
        return json.dumps(value)

    if isinstance(value, list):
        return f"[{','.join(stable_json(i) for i in value)}]"

    entries = sorted(value.items())
    pairs = [f"{json.dumps(k)}:{stable_json(v)}" for k, v in entries]
    return f"{{{','.join(pairs)}}}"

def stable_json_pretty(value: Any) -> str:
    return json.dumps(json.loads(stable_json(value)), indent=2)
```

## 使用示例

### PRD 迁移检测
```python
async def ensure_canonical_ralph_artifacts(
    cwd: str,
    session_id: str = None
) -> RalphCanonicalArtifacts:
    progress_path = join(get_state_dir(cwd, session_id), "ralph-progress.json")

    # 目录创建
    await mkdir(join(cwd, ".omx/plans"), recursive=True)
    await mkdir(get_state_dir(cwd, session_id), recursive=True)

    # PRD 迁移
    prd_files = await list_canonical_prd_files(cwd)
    prd_result = await migrate_legacy_prd_if_needed(cwd, prd_files[0])

    # Progress 迁移
    migrated = await migrate_legacy_progress_if_needed(cwd, progress_path)

    # 确保 ledger 存在
    await ensure_progress_ledger_file(progress_path)

    return {
        "canonical_prd_path": prd_result.canonical_prd_path,
        "canonical_progress_path": progress_path,
        "migrated_prd": prd_result.migrated,
        "migrated_progress": migrated
    }
```

### Progress 追加
```python
async def append_progress_entry(
    cwd: str,
    text: str,
    session_id: str = None
):
    progress_path = join(get_state_dir(cwd, session_id), "ralph-progress.json")
    ledger = await read_progress_ledger(progress_path)

    entry = {
        "index": len(ledger.entries) + 1,
        "text": text,
        "recorded_at": now_iso()
    }
    ledger.entries.append(entry)
    ledger.updated_at = now_iso()

    await write_progress_ledger(progress_path, ledger)
```

---

**整合来源**: oh-my-codex-main/src/ralph/persistence.ts
**更新时间**: 2026-04-14