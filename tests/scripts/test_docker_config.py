"""容器化部署的**静态契约**（Dockerfile / compose / CI 的 docker 步骤）。

这些断言全部来自 v0.90.0 的真实事故，不是风格偏好：

1. 镜像能构建成功，但容器启动即 `ModuleNotFoundError: No module named 'src'`
   —— 因为 `pip install .` 执行时构建目录里**还没有源码**，装出一个空的 dist-info。
2. 服务默认绑 `127.0.0.1`，容器里等于端不出容器 → 端口映射与健康检查全不通。
3. CI 的 docker 测试写成 `docker run ... --version || true`，末尾 `|| true`
   让"镜像根本跑不起来"也判 success（假绿）。
4. healthcheck 打的是恒真占位（`sys.exit(0)` / `import 一下就 exit 0`）。

真正的运行时验证在 CI 的 `docker-build` job（真构建 + 真探活）；
这里守的是"这些配置别被悄悄改回原样"。
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def dockerfile() -> str:
    return (ROOT / "Dockerfile").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def compose() -> dict:
    return yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))


class TestDockerfile:
    def test_source_copied_before_self_install(self, dockerfile: str):
        """必须先 COPY 源码再 `pip install .`，否则装出来的是空包"""
        idx_src = dockerfile.find("COPY src ")
        idx_install = dockerfile.find("pip install --no-cache-dir --prefix=/install .")
        assert idx_src != -1, "Dockerfile 没有在构建阶段拷贝 src（会装出空包）"
        assert idx_install != -1, "Dockerfile 没有安装项目自身"
        assert idx_src < idx_install, "COPY src 必须在 pip install . 之前"

    def test_self_install_does_not_skip_deps(self, dockerfile: str):
        """`--no-deps` 会漏掉只在 pyproject 里的依赖（实测：typer 不在 requirements.txt）"""
        line = next(
            (ln for ln in dockerfile.splitlines() if "pip install" in ln and "--prefix=/install ." in ln),
            "",
        )
        assert line, "找不到安装项目自身的步骤"
        assert "--no-deps" not in line, (
            f"安装自身时跳过依赖 → 漏装只在 pyproject 声明的依赖: {line.strip()}"
        )

    def test_prompts_copied_before_self_install(self, dockerfile: str):
        """prompts 也要在装包前就位（`clawd review` 的角色模板来自这里）"""
        assert dockerfile.find("COPY prompts ") < dockerfile.find("--prefix=/install .")

    def test_pythonpath_set(self, dockerfile: str):
        assert "PYTHONPATH=/app" in dockerfile, (
            "console script 从 /usr/local/bin 启动，不设 PYTHONPATH 就 import 不到 /app 下的 src"
        )

    def test_binds_all_interfaces_in_container(self, dockerfile: str):
        assert "AGENT_SERVER_HOST=0.0.0.0" in dockerfile, "容器内不绑 0.0.0.0 时端口映射无效"

    def test_workdir_owned_by_runtime_user(self, dockerfile: str):
        """整个 /app 必须归运行用户：serve 要把端口文件写进 workdir。

        真实事故（CI Linux runner）：只 chown 了 logs/.clawd，/app 属 root →
        `PermissionError: [Errno 13] /app/.clawd_host_port` → Host 崩 → /healthz 000。
        """
        assert "chown -R 1000:1000 /app" in dockerfile, (
            "Dockerfile 未把 /app 交给运行用户（端口文件会写不进去）"
        )


class TestCompose:
    def test_service_binds_all_interfaces(self, compose: dict):
        env = compose["services"]["clawd-code"]["environment"]
        joined = " ".join(env) if isinstance(env, list) else " ".join(f"{k}={v}" for k, v in env.items())
        assert "AGENT_SERVER_HOST=0.0.0.0" in joined, "compose 未让服务绑全部网卡"

    def test_data_dir_on_volume(self, compose: dict):
        """数据目录必须在挂载卷上，否则 `docker compose up` 一次就丢配置/会话"""
        env = compose["services"]["clawd-code"]["environment"]
        joined = " ".join(env) if isinstance(env, list) else " ".join(f"{k}={v}" for k, v in env.items())
        assert "CLAWD_DATA_DIR=/app/.clawd" in joined
        volumes = compose["services"]["clawd-code"].get("volumes") or []
        assert any(".clawd" in str(v) for v in volumes), "卷里没有 .clawd"


class TestCiDockerJob:
    def test_no_fake_green_in_docker_smoke(self):
        """`|| true` 会把"镜像跑不起来"变成 success —— 实测发生过"""
        text = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        docker_job = text.split("docker-build:", 1)[1]
        # 注释行不参与判定（`#` 开头在 shell 里没有语义）
        effective = "\n".join(
            ln for ln in docker_job.splitlines() if not ln.lstrip().startswith("#")
        )
        assert "--version || true" not in effective, "docker 冒烟仍是 `|| true` 假绿"
        assert "/healthz" in effective, "docker 冒烟没有真探活"
        assert "docker rm -f clawd-smoke" in effective, "冒烟容器没清理（会漏到后续 job/重跑冲突）"
