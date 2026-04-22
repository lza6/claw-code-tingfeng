"""Skill Syncer — 跨项目技能同步工具

核心功能：
1. 扫描两个项目的 skills/ 目录
2. 识别缺失技能
3. 自动生成 Skill 描述并导入
"""
import shutil
from pathlib import Path


def sync_skills(source_dir: str, target_dir: str):
    source_path = Path(source_dir)
    target_path = Path(target_dir)

    if not source_path.exists() or not target_path.exists():
        print(f"路径不存在: {source_path} or {target_path}")
        return

    source_skills = {d.name for d in source_path.iterdir() if d.is_dir()}
    target_skills = {d.name for d in target_path.iterdir() if d.is_dir()}

    missing_skills = source_skills - target_skills
    print(f"发现缺失技能: {len(missing_skills)} 个: {missing_skills}")

    for skill_name in missing_skills:
        src_skill = source_path / skill_name
        dest_skill = target_path / skill_name

        # 只同步 SKILL.md 或 README.md
        dest_skill.mkdir(exist_ok=True)

        found_doc = False
        for doc_name in ["SKILL.md", "README.md"]:
            src_doc = src_skill / doc_name
            if src_doc.exists():
                shutil.copy(src_doc, dest_skill / doc_name)
                print(f"已同步技能文档: {skill_name}/{doc_name}")
                found_doc = True
                break

        if not found_doc:
            print(f"警告: 技能 {skill_name} 缺失文档，跳过")

if __name__ == "__main__":
    sync_skills("oh-my-codex-main/skills", "skills")
