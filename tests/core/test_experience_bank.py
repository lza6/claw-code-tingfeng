"""Tests for Unified Experience Bank"""
import json
import pytest
from pathlib import Path

from src.core.experience_bank import (
    ExperienceBank,
    ExperienceRecord,
    ExperienceEmbedder,
    _tokenize,
)


@pytest.fixture
def temp_storage(tmp_path: Path) -> Path:
    """临时存储路径"""
    return tmp_path / "experience.json"


@pytest.fixture
def bank(temp_storage: Path) -> ExperienceBank:
    """带持久化的经验库"""
    return ExperienceBank(storage_path=temp_storage)


class TestExperienceRecord:
    """经验记录测试"""

    def test_default_values(self):
        """默认值正确"""
        record = ExperienceRecord()
        assert record.success_rate == 0.5  # 默认值
        assert record.times_used == 1
        assert record.success_count == 0

    def test_update_success(self):
        """更新成功标记"""
        record = ExperienceRecord(success_count=0, fail_count=0)
        record.update(True)
        assert record.times_used == 2
        assert record.success_count == 1
        assert record.success_rate == 1.0

    def test_update_failure(self):
        """更新失败标记"""
        record = ExperienceRecord(success_count=1, fail_count=0)
        record.update(False)
        assert record.fail_count == 1
        assert record.failure_count == 1
        assert record.success_rate == 0.5

    def test_serialization_roundtrip(self):
        """序列化/反序列化往返"""
        original = ExperienceRecord(
            id="exp_test",
            error_pattern="test error",
            fix_strategy="test fix",
            success_count=5,
            fail_count=2,
            tags=["tag1", "tag2"],
        )
        data = original.to_dict()
        restored = ExperienceRecord.from_dict(data)

        assert restored.id == original.id
        assert restored.error_pattern == original.error_pattern
        assert restored.success_count == original.success_count
        assert restored.tags == original.tags


class TestExperienceBankBasic:
    """经验库基础测试"""

    def test_record_new_experience(self, bank: ExperienceBank):
        """记录新经验"""
        record = bank.record_experience(
            error_pattern="ModuleNotFoundError",
            error_category="ImportError",
            fix_strategy="Fix import path",
            success=True,
        )
        assert record.success_count == 1
        assert record.fail_count == 0
        assert record.error_category == "ImportError"

    def test_update_existing_experience(self, bank: ExperienceBank):
        """更新已有经验"""
        bank.record_experience(
            error_pattern="ModuleNotFoundError: foo",
            error_category="ImportError",
            fix_strategy="Fix import",
            success=True,
        )
        # 相同内容应更新而非创建新记录
        record2 = bank.record_experience(
            error_pattern="ModuleNotFoundError: foo",
            error_category="ImportError",
            fix_strategy="Fix import",
            success=False,
        )
        assert record2.times_used == 2
        assert record2.success_count == 1
        assert record2.fail_count == 1

    def test_find_similar_by_pattern(self, bank: ExperienceBank):
        """通过模式查找相似经验"""
        bank.record_experience(
            error_pattern="ModuleNotFoundError: no module named 'foo'",
            error_category="ImportError",
            fix_strategy="Fix import path",
            success=True,
        )
        result = bank.find_similar_fix(
            error_pattern="ModuleNotFoundError: no module 'bar'",
            error_category="ImportError",
            min_success_rate=0.5,
        )
        assert result is not None
        assert result.error_category == "ImportError"

    def test_no_similar_found(self, bank: ExperienceBank):
        """无相似经验时返回 None"""
        result = bank.find_similar_fix(
            error_pattern="CompletelyUnknownError",
            min_success_rate=0.8,
        )
        assert result is None

    def test_get_stats_empty(self, bank: ExperienceBank):
        """空库统计"""
        stats = bank.get_stats()
        assert stats["total"] == 0
        assert stats["overall_success_rate"] == 0.0

    def test_get_stats_with_data(self, bank: ExperienceBank):
        """有数据的统计"""
        bank.record_experience(
            error_pattern="Error A",
            error_category="TypeA",
            fix_strategy="Fix A",
            success=True,
        )
        bank.record_experience(
            error_pattern="Error B",
            error_category="TypeB",
            fix_strategy="Fix B",
            success=False,
        )

        stats = bank.get_stats()
        assert stats["total"] == 2
        assert "TypeA" in stats["by_category"]
        assert "TypeB" in stats["by_category"]

    def test_clear(self, bank: ExperienceBank):
        """清空经验库"""
        bank.record_experience(error_pattern="Error", fix_strategy="Fix", success=True)
        bank.clear()
        assert bank.get_stats()["total"] == 0


class TestExperienceBankVector:
    """向量模式测试"""

    def test_vector_mode_activation(self, bank: ExperienceBank):
        """有 traceback 时启用向量模式"""
        bank.record_experience(
            error_traceback="Traceback: ModuleNotFoundError: foo",
            fix_strategy="Fix import",
            success=True,
        )
        assert bank._vector_mode is True

    def test_find_similar_by_traceback(self, bank: ExperienceBank):
        """通过 traceback 查找相似经验"""
        bank.record_experience(
            error_traceback="Traceback (most recent call last):\n  File 'test.py'\nModuleNotFoundError: No module named 'requests'",
            fix_strategy="Install requests: pip install requests",
            success=True,
            error_category="ImportError",
        )

        results = bank.find_similar(
            error_traceback="Traceback: ModuleNotFoundError: No module named 'requests'",
            top_k=1,
        )
        assert len(results) >= 1
        assert results[0].error_category == "ImportError"

    def test_update_success_flag(self, bank: ExperienceBank):
        """更新成功标记"""
        exp_id = bank.record_experience(
            error_traceback="Some error",
            fix_strategy="Some fix",
            success=True,
        )
        result = bank.update_success(exp_id.id, False)
        assert result is True

        stats = bank.get_stats()
        assert stats["total_failure"] >= 1

    def test_update_nonexistent_id(self, bank: ExperienceBank):
        """更新不存在的 ID"""
        result = bank.update_success("nonexistent", True)
        assert result is False


class TestExperienceBankPersistence:
    """持久化测试"""

    def test_save_and_load(self, temp_storage: Path):
        """保存和加载"""
        bank1 = ExperienceBank(storage_path=temp_storage)
        bank1.record_experience(
            error_pattern="Test Error",
            fix_strategy="Test Fix",
            success=True,
        )

        bank2 = ExperienceBank(storage_path=temp_storage)
        count = bank2._load()
        assert count == 1

    def test_load_creates_directory(self, tmp_path: Path):
        """加载时自动创建目录"""
        storage = tmp_path / "subdir" / "exp.json"
        bank = ExperienceBank(storage_path=storage)
        bank.record_experience(error_pattern="E", fix_strategy="F", success=True)
        assert storage.exists()

    def test_save_handles_os_error(self, tmp_path: Path):
        """保存失败时不抛出异常"""
        # 指向不可写路径
        bank = ExperienceBank(storage_path=Path("/nonexistent/dir/exp.json"))
        bank.record_experience(error_pattern="E", fix_strategy="F", success=True)
        # 不应抛出异常

    def test_load_invalid_json(self, temp_storage: Path):
        """加载无效 JSON 时不抛出异常"""
        temp_storage.write_text("not json", encoding="utf-8")
        bank = ExperienceBank(storage_path=temp_storage)
        count = bank._load()
        assert count == 0

    def test_backward_compat_list_format(self, temp_storage: Path):
        """向后兼容旧版 list 格式"""
        old_data = [
            {
                "error_pattern": "Old Error",
                "error_category": "Test",
                "fix_strategy": "Old Fix",
                "success": True,
                "success_count": 3,
                "fail_count": 1,
            }
        ]
        temp_storage.write_text(json.dumps(old_data), encoding="utf-8")

        bank = ExperienceBank(storage_path=temp_storage)
        count = bank._load()
        assert count == 1

    def test_backward_compat_self_healing_format(self, temp_storage: Path):
        """向后兼容 self_healing 格式"""
        old_data = {
            "version": "1.0",
            "experiences": {
                "exp_old": {
                    "id": "exp_old",
                    "error_traceback": "Old traceback",
                    "error_embedding": {"term1": 0.5},
                    "fix_strategy": "Old fix",
                    "success_flag": True,
                    "success_count": 2,
                    "failure_count": 1,
                    "application_count": 3,
                    "error_category": "Test",
                    "tags": [],
                    "created_at": 1000000.0,
                    "updated_at": 1000001.0,
                }
            },
        }
        temp_storage.write_text(json.dumps(old_data), encoding="utf-8")

        bank = ExperienceBank(storage_path=temp_storage)
        count = bank._load()
        assert count == 1


class TestExperienceEmbedder:
    """嵌入器测试"""

    def test_embed_produces_dict(self):
        """嵌入生成字典"""
        embedder = ExperienceEmbedder()
        embedding = embedder.embed("ModuleNotFoundError: foo")
        assert isinstance(embedding, dict)
        assert len(embedding) > 0

    def test_cosine_similarity_identical(self):
        """相同向量相似度为 1"""
        embedder = ExperienceEmbedder()
        vec = {"term1": 1.0, "term2": 2.0}
        assert embedder.cosine_similarity(vec, vec) == pytest.approx(1.0)

    def test_cosine_similarity_orthogonal(self):
        """正交向量相似度为 0"""
        embedder = ExperienceEmbedder()
        vec_a = {"term1": 1.0}
        vec_b = {"term2": 1.0}
        assert embedder.cosine_similarity(vec_a, vec_b) == pytest.approx(0.0)

    def test_tokenize_filters_short_words(self):
        """分词过滤短词"""
        tokens = ExperienceEmbedder._tokenize("a b c import error")
        assert "a" not in tokens
        assert "b" not in tokens
        assert "import" in tokens


class TestTokenize:
    """分词函数测试"""

    def test_english_tokens(self):
        """英文分词"""
        tokens = _tokenize("ModuleNotFoundError: No module named 'foo'")
        assert "modulenotfounderror" in tokens
        assert "module" in tokens
        assert "foo" in tokens

    def test_chinese_tokens(self):
        """中文分词"""
        tokens = _tokenize("模块未找到错误")
        assert len(tokens) > 0

    def test_mixed_tokens(self):
        """中英文混合分词"""
        tokens = _tokenize("ModuleNotFoundError 模块未找到")
        assert "modulenotfounderror" in tokens
        assert any("\u4e00" <= c <= "\u9fff" for t in tokens for c in t)
