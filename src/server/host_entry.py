"""Host 服务入口 — 桌面端/Web 端的本地 Host（参考 DSH Desktop 模式）

架构分工（对齐 DSH）:
- Host（本模块）: agent 权威运行时 + WS 服务 + 端口文件
- Electron 壳: 只做窗口/托盘/spawn Python/loadURL，壳内不造 IPC

用法:
    venv/Scripts/python.exe -m src serve                # 前台启动（端口来自配置）
    venv/Scripts/python.exe -m src serve --port 18765   # 指定端口
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import secrets
from pathlib import Path

logger = logging.getLogger(__name__)

PORT_FILE_NAME = ".clawd_host_port"


def write_port_file(workdir: Path, port: int, host: str, token: str) -> Path:
    """写端口文件（Electron 壳与浏览器发现服务的唯一机制）"""
    pf = workdir / PORT_FILE_NAME
    pf.write_text(
        json.dumps({"port": port, "host": host, "token": token}),
        encoding="utf-8",
    )
    return pf


def read_port_file(workdir: Path) -> dict | None:
    pf = workdir / PORT_FILE_NAME
    if not pf.exists():
        return None
    try:
        return json.loads(pf.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


async def run_host(
    port: int | None = None, workdir: Path | None = None, env_file: Path | None = None
) -> int:
    """启动 Host：WS 服务 + 端口文件（长驻直到 Ctrl+C）"""
    from ..server import create_server

    workdir = (workdir or Path.cwd()).resolve()

    # 加载 .env 并构建 LLM 配置（Host 创建的每个引擎都继承此配置）
    # 查找顺序: --env-file 显式传入（桌面壳的 userData）→ workdir/.env
    try:
        from dotenv import load_dotenv

        if env_file and env_file.exists():
            load_dotenv(env_file, override=True)
            logger.info(f"已加载环境配置: {env_file}")
        load_dotenv(workdir / ".env")
    except ImportError:
        pass
    llm_config = None
    try:
        from ..llm.config import LLMConfig

        llm_config = LLMConfig.from_env()
        if not llm_config.api_key:
            llm_config = None
            logger.warning("LLM API key 未配置，引擎将以无 LLM 模式运行")
    except Exception as e:
        logger.warning(f"LLM 配置加载失败: {e}")

    # 令牌：AGENT_SERVER_TOKEN 环境变量优先，否则随机生成（写入端口文件供壳读取）
    import os

    token = os.environ.get("AGENT_SERVER_TOKEN") or secrets.token_urlsafe(24)

    # Web UI 静态目录：desktop/web（存在才托管，纯增强不影响纯 WS 用法）
    web_dir = workdir / "desktop" / "web"
    static_dir = str(web_dir) if web_dir.is_dir() else None

    # create_server(port=None) 时走 ClawdWebSocketServer 的配置/env 逻辑；
    # 显式 port 则覆盖。token 通过同参传入，保证与端口文件一致。
    server = create_server(
        host="127.0.0.1",
        port=port,
        token=token,
        static_dir=static_dir,
        static_token=token,
        llm_config=llm_config,
    )

    host, actual_port = await server.start()
    pf = write_port_file(workdir, actual_port, host, token)
    print(f"[clawd-host] ws://{host}:{actual_port}")
    print(f"[clawd-host] token: {token}")
    if static_dir:
        print(f"[clawd-host] web ui: http://{host}:{actual_port}/?token={token[:8]}...")
    print(f"[clawd-host] 端口文件: {pf}")

    try:
        await server.run_forever()
    finally:
        (workdir / PORT_FILE_NAME).unlink(missing_ok=True)
    return 0


def cmd_serve(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="serve", description="启动本地 Host 服务（桌面端/Web 端）")
    parser.add_argument("--port", type=int, default=None, help="WS 端口（默认走配置/环境变量）")
    parser.add_argument("--workdir", type=str, default=None)
    parser.add_argument("--env-file", type=str, default=None,
                        help="额外加载的 .env（桌面端壳传入 userData 下的 .env）")
    parser.add_argument("--data-dir", type=str, default=None,
                        help="运行期数据目录（provider/用量/会话）；桌面端传 userData/data，升级不丢")
    args = parser.parse_args(argv)
    if args.data_dir:
        import os as _os

        _os.environ["CLAWD_DATA_DIR"] = str(Path(args.data_dir).expanduser())
    try:
        return asyncio.run(
            run_host(
                port=args.port,
                workdir=Path(args.workdir) if args.workdir else None,
                env_file=Path(args.env_file) if args.env_file else None,
            )
        )
    except KeyboardInterrupt:
        print("\n[clawd-host] 已停止")
        return 0


if __name__ == "__main__":
    raise SystemExit(cmd_serve())
