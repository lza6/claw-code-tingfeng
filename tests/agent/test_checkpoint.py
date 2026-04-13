import pytest
import os
import json
import gzip
from pathlib import Path
from src.agent.checkpoint import save_checkpoint, load_checkpoint, list_checkpoints, cleanup_old_checkpoints

def test_save_load_checkpoint_json(tmp_path):
    path = tmp_path / "checkpoint_test.json"
    messages = [{"role": "user", "content": "hello"}]
    iteration = 1
    max_iterations = 5
    tool_history = [("BashTool", "ls")]
    goal = "test goal"

    saved_path = save_checkpoint(path, messages, iteration, max_iterations, tool_history, goal, "gpt-4o")
    assert saved_path.exists()

    state = load_checkpoint(saved_path)
    assert state.messages == messages
    assert state.iteration == iteration
    assert state.max_iterations == max_iterations
    assert state.tool_call_history == tool_history
    assert state.goal == goal
    assert state.model == "gpt-4o"

def test_save_load_checkpoint_gzip(tmp_path):
    path = tmp_path / "checkpoint_test.json.gz"
    messages = [{"role": "user", "content": "hi"}]

    saved_path = save_checkpoint(path, messages, 0, 10, [], "goal")
    assert str(saved_path).endswith(".gz")

    state = load_checkpoint(saved_path)
    assert state.messages == messages

def test_list_and_cleanup_checkpoints(tmp_path):
    # 创建多个文件
    (tmp_path / "checkpoint_1").write_text("1")
    (tmp_path / "checkpoint_2").write_text("2")
    (tmp_path / "checkpoint_3").write_text("3")
    (tmp_path / "other_file").write_text("other")

    checkpoints = list_checkpoints(tmp_path)
    assert len(checkpoints) == 3

    deleted = cleanup_old_checkpoints(tmp_path, keep_last=1)
    assert len(deleted) == 2
    assert len(list_checkpoints(tmp_path)) == 1
