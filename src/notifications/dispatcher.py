"""Notifications 分发器

从 oh-my-codex-main/src/notifications/dispatcher.ts 汲取。

功能:
- send_discord(): 发送 Discord webhook 通知
- send_telegram(): 发送 Telegram 通知
- send_slack(): 发送 Slack 通知
- send_webhook(): 发送通用 webhook 通知
- dispatch_notifications(): 多平台分发

所有发送都是非阻塞的，带超时。失败被吞掉以避免阻塞钩子。
"""
from __future__ import annotations

import json
import re
import socket
import ssl
from dataclasses import dataclass
from datetime import datetime

from .config import parse_mention_allowed_mentions
from .types import (
    DiscordBotNotificationConfig,
    DiscordNotificationConfig,
    DispatchResult,
    FullNotificationConfig,
    FullNotificationPayload,
    NotificationEvent,
    NotificationPlatform,
    NotificationResult,
    SlackNotificationConfig,
    TelegramNotificationConfig,
    WebhookNotificationConfig,
)


# 简化的通知结果类（用于内部异步发送）
@dataclass
class SimpleNotificationResult:
    success: bool
    platform: str
    error: str | None = None
    status_code: int | None = None


# ===== 常量 =====
SEND_TIMEOUT_MS = 10_000
DISPATCH_TIMEOUT_MS = 15_000
DISCORD_MAX_CONTENT_LENGTH = 2000


# ===== 验证函数 =====
def validate_discord_url(webhook_url: str) -> bool:
    """验证 Discord webhook URL"""
    try:
        from urllib.parse import urlparse
        parsed = urlparse(webhook_url)
        allowed_hosts = ['discord.com', 'discordapp.com']
        if parsed.hostname not in allowed_hosts and not any(
            parsed.hostname.endswith(f'.{h}') for h in allowed_hosts
        ):
            return False
        return parsed.scheme == 'https'
    except Exception:
        return False


def validate_telegram_token(token: str) -> bool:
    """验证 Telegram bot token 格式"""
    return bool(re.match(r'^[0-9]+:[A-Za-z0-9_-]+$', token))


def validate_slack_url(webhook_url: str) -> bool:
    """验证 Slack webhook URL"""
    try:
        from urllib.parse import urlparse
        parsed = urlparse(webhook_url)
        return (
            parsed.scheme == 'https' and
            (parsed.hostname == 'hooks.slack.com' or
             parsed.hostname.endswith('.hooks.slack.com'))
        )
    except Exception:
        return False


def validate_webhook_url(url: str) -> bool:
    """验证通用 webhook URL"""
    try:
        from urllib.parse import urlparse
        parsed = urlparse(url)
        return parsed.scheme == 'https'
    except Exception:
        return False


# ===== 发送函数 =====

async def send_discord_webhook(
    webhook_url: str,
    content: str,
    username: str | None = None,
    avatar_url: str | None = None,
    timeout_ms: int = SEND_TIMEOUT_MS,
) -> NotificationResult:
    """发送 Discord webhook 通知（异步，非阻塞）

    参考: oh-my-codex-main/src/notifications/dispatcher.ts::sendDiscordWebhook

    Args:
        webhook_url: Discord webhook URL
        content: 消息内容
        username: 覆盖用户名（可选）
        avatar_url: 覆盖头像 URL（可选）
        timeout_ms: 超时时间（毫秒）

    Returns:
        NotificationResult 结果对象
    """
    import asyncio
    from dataclasses import dataclass

    @dataclass
    class SimpleNotificationResult:
        success: bool
        platform: str
        error: str | None = None
        status_code: int | None = None

    # 验证 URL
    if not validate_discord_url(webhook_url):
        return SimpleNotificationResult(
            success=False,
            platform="discord",
            error="Invalid Discord webhook URL",
        )

    # 准备 Discord payload
    payload = {
        "content": content[:DISCORD_MAX_CONTENT_LENGTH],
    }
    if username:
        payload["username"] = username
    if avatar_url:
        payload["avatar_url"] = avatar_url

    payload_bytes = json.dumps(payload).encode("utf-8")

    # 解析 URL
    from urllib.parse import urlparse
    parsed = urlparse(webhook_url)
    host = parsed.hostname
    path = parsed.path

    # 发送 HTTPS 请求
    try:
        loop = asyncio.get_event_loop()

        def _send():
            import socket
            import ssl

            # 创建 SSL 上下文
            ssl_context = ssl.create_default_context()

            # 创建连接
            sock = socket.create_connection((host, 443), timeout=timeout_ms / 1000)
            ssock = ssl_context.wrap_socket(sock, server_hostname=host)

            # 构建 HTTP 请求
            request = (
                f"POST {path} HTTP/1.1\r\n"
                f"Host: {host}\r\n"
                f"Content-Type: application/json\r\n"
                f"Content-Length: {len(payload_bytes)}\r\n"
                f"User-Agent: clawd-notifications/1.0\r\n"
                f"Connection: close\r\n"
                f"\r\n"
            ).encode() + payload_bytes

            ssock.sendall(request)

            # 读取响应
            response = b""
            while True:
                chunk = ssock.recv(4096)
                if not chunk:
                    break
                response += chunk

            ssock.close()
            sock.close()

            # 解析响应
            response_str = response.decode("utf-8", errors="ignore")
            status_line = response_str.split("\r\n")[0]
            status_code = int(status_line.split()[1]) if len(status_line.split()) > 1 else 0

            return status_code, response_str

        status_code, response_str = await loop.run_in_executor(None, _send)

        # Discord 返回 2xx 表示成功
        success = 200 <= status_code < 300
        return SimpleNotificationResult(
            success=success,
            platform="discord",
            status_code=status_code,
            error=None if success else f"HTTP {status_code}",
        )

    except asyncio.TimeoutError:
        return SimpleNotificationResult(
            success=False,
            platform="discord",
            error="Request timeout",
        )
    except Exception as e:
        return SimpleNotificationResult(
            success=False,
            platform="discord",
            error=str(e),
        )


async def send_telegram_message(
    bot_token: str,
    chat_id: str,
    text: str,
    parse_mode: str | None = None,
    timeout_ms: int = SEND_TIMEOUT_MS,
) -> NotificationResult:
    """发送 Telegram 消息（异步，非阻塞）

    参考: oh-my-codex-main/src/notifications/dispatcher.ts::sendTelegramMessage

    Args:
        bot_token: Telegram bot token
        chat_id: 聊天 ID
        text: 消息文本
        parse_mode: 解析模式 ("Markdown" 或 "HTML")
        timeout_ms: 超时时间（毫秒）

    Returns:
        NotificationResult 结果对象
    """
    import asyncio

    # 验证 token
    if not validate_telegram_token(bot_token):
        return SimpleNotificationResult(
            success=False,
            platform="telegram",
            error="Invalid Telegram bot token",
        )

    # 构建 API URL
    api_url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text[:4096]}  # Telegram 限制
    if parse_mode:
        payload["parse_mode"] = parse_mode

    payload_bytes = json.dumps(payload).encode("utf-8")

    try:
        loop = asyncio.get_event_loop()

        def _send():
            import socket
            import ssl
            from urllib.parse import urlparse

            parsed = urlparse(api_url)
            host = parsed.hostname
            path = parsed.path

            ssl_context = ssl.create_default_context()
            sock = socket.create_connection((host, 443), timeout=timeout_ms / 1000)
            ssock = ssl_context.wrap_socket(sock, server_hostname=host)

            request = (
                f"POST {path} HTTP/1.1\r\n"
                f"Host: {host}\r\n"
                f"Content-Type: application/json\r\n"
                f"Content-Length: {len(payload_bytes)}\r\n"
                f"User-Agent: clawd-notifications/1.0\r\n"
                f"Connection: close\r\n"
                f"\r\n"
            ).encode() + payload_bytes

            ssock.sendall(request)

            response = b""
            while True:
                chunk = ssock.recv(4096)
                if not chunk:
                    break
                response += chunk

            ssock.close()
            sock.close()

            response_str = response.decode("utf-8", errors="ignore")
            status_line = response_str.split("\r\n")[0]
            status_code = int(status_line.split()[1]) if len(status_line.split()) > 1 else 0

            return status_code, response_str

        status_code, response_str = await loop.run_in_executor(None, _send)

        success = 200 <= status_code < 300
        return SimpleNotificationResult(
            success=success,
            platform="telegram",
            status_code=status_code,
            error=None if success else f"HTTP {status_code}",
        )

    except asyncio.TimeoutError:
        return SimpleNotificationResult(
            success=False,
            platform="telegram",
            error="Request timeout",
        )
    except Exception as e:
        return SimpleNotificationResult(
            success=False,
            platform="telegram",
            error=str(e),
        )


async def send_slack_webhook(
    webhook_url: str,
    text: str,
    username: str | None = None,
    icon_emoji: str | None = None,
    timeout_ms: int = SEND_TIMEOUT_MS,
) -> NotificationResult:
    """发送 Slack webhook 通知（异步，非阻塞）

    参考: oh-my-codex-main/src/notifications/dispatcher.ts::sendSlackWebhook

    Args:
        webhook_url: Slack incoming webhook URL
        text: 消息文本
        username: 覆盖用户名
        icon_emoji: 图标 emoji
        timeout_ms: 超时时间（毫秒）

    Returns:
        NotificationResult 结果对象
    """
    import asyncio

    if not validate_slack_url(webhook_url):
        return SimpleNotificationResult(
            success=False,
            platform="slack",
            error="Invalid Slack webhook URL",
        )

    payload = {"text": text[:3000]}  # Slack 限制
    if username:
        payload["username"] = username
    if icon_emoji:
        payload["icon_emoji"] = icon_emoji

    payload_bytes = json.dumps(payload).encode("utf-8")

    try:
        loop = asyncio.get_event_loop()

        def _send():
            import socket
            import ssl
            from urllib.parse import urlparse

            parsed = urlparse(webhook_url)
            host = parsed.hostname
            path = parsed.path

            ssl_context = ssl.create_default_context()
            sock = socket.create_connection((host, 443), timeout=timeout_ms / 1000)
            ssock = ssl_context.wrap_socket(sock, server_hostname=host)

            request = (
                f"POST {path} HTTP/1.1\r\n"
                f"Host: {host}\r\n"
                f"Content-Type: application/json\r\n"
                f"Content-Length: {len(payload_bytes)}\r\n"
                f"User-Agent: clawd-notifications/1.0\r\n"
                f"Connection: close\r\n"
                f"\r\n"
            ).encode() + payload_bytes

            ssock.sendall(request)

            response = b""
            while True:
                chunk = ssock.recv(4096)
                if not chunk:
                    break
                response += chunk

            ssock.close()
            sock.close()

            response_str = response.decode("utf-8", errors="ignore")
            status_line = response_str.split("\r\n")[0]
            status_code = int(status_line.split()[1]) if len(status_line.split()) > 1 else 0

            return status_code, response_str

        status_code, response_str = await loop.run_in_executor(None, _send)

        success = 200 <= status_code < 300
        return SimpleNotificationResult(
            success=success,
            platform="slack",
            status_code=status_code,
            error=None if success else f"HTTP {status_code}",
        )

    except asyncio.TimeoutError:
        return SimpleNotificationResult(
            success=False,
            platform="slack",
            error="Request timeout",
        )
    except Exception as e:
        return SimpleNotificationResult(
            success=False,
            platform="slack",
            error=str(e),
        )


async def send_generic_webhook(
    webhook_url: str,
    payload: dict,
    timeout_ms: int = SEND_TIMEOUT_MS,
) -> NotificationResult:
    """发送通用 webhook（异步，非阻塞）

    Args:
        webhook_url: Webhook URL
        payload: JSON 载荷
        timeout_ms: 超时时间（毫秒）

    Returns:
        NotificationResult 结果对象
    """
    import asyncio

    if not validate_webhook_url(webhook_url):
        return SimpleNotificationResult(
            success=False,
            platform="webhook",
            error="Invalid webhook URL",
        )

    payload_bytes = json.dumps(payload).encode("utf-8")

    try:
        loop = asyncio.get_event_loop()

        def _send():
            import socket
            import ssl
            from urllib.parse import urlparse

            parsed = urlparse(webhook_url)
            host = parsed.hostname
            path = parsed.path or "/"

            ssl_context = ssl.create_default_context()
            sock = socket.create_connection((host, 443), timeout=timeout_ms / 1000)
            ssock = ssl_context.wrap_socket(sock, server_hostname=host)

            request = (
                f"POST {path} HTTP/1.1\r\n"
                f"Host: {host}\r\n"
                f"Content-Type: application/json\r\n"
                f"Content-Length: {len(payload_bytes)}\r\n"
                f"User-Agent: clawd-notifications/1.0\r\n"
                f"Connection: close\r\n"
                f"\r\n"
            ).encode() + payload_bytes

            ssock.sendall(request)

            response = b""
            while True:
                chunk = ssock.recv(4096)
                if not chunk:
                    break
                response += chunk

            ssock.close()
            sock.close()

            response_str = response.decode("utf-8", errors="ignore")
            status_line = response_str.split("\r\n")[0]
            status_code = int(status_line.split()[1]) if len(status_line.split()) > 1 else 0

            return status_code, response_str

        status_code, response_str = await loop.run_in_executor(None, _send)

        success = 200 <= status_code < 300
        return SimpleNotificationResult(
            success=success,
            platform="webhook",
            status_code=status_code,
            error=None if success else f"HTTP {status_code}",
        )

    except asyncio.TimeoutError:
        return SimpleNotificationResult(
            success=False,
            platform="webhook",
            error="Request timeout",
        )
    except Exception as e:
        return SimpleNotificationResult(
            success=False,
            platform="webhook",
            error=str(e),
        )


async def dispatch_notification(
    platform: NotificationPlatform,
    config: FullNotificationConfig,
    event: NotificationEvent,
    timeout_ms: int = DISPATCH_TIMEOUT_MS,
) -> DispatchResult:
    """分发通知到指定平台

    参考: oh-my-codex-main/src/notifications/dispatcher.ts::dispatchNotification

    Args:
        platform: 目标平台
        config: 通知配置
        event: 通知事件
        timeout_ms: 总超时时间

    Returns:
        DispatchResult 结果
    """

    start_time = datetime.now()

    # 根据平台分发
    if platform == NotificationPlatform.DISCORD:
        if isinstance(config, DiscordNotificationConfig):
            result = await send_discord_webhook(
                webhook_url=config.webhook_url,
                content=event.content,
                username=config.username,
                avatar_url=config.avatar_url,
                timeout_ms=timeout_ms,
            )
        else:
            result = SimpleNotificationResult(
                success=False,
                platform="discord",
                error="Invalid config type for Discord",
            )

    elif platform == NotificationPlatform.TELEGRAM:
        if isinstance(config, TelegramNotificationConfig):
            result = await send_telegram_message(
                bot_token=config.bot_token,
                chat_id=config.chat_id,
                text=event.content,
                parse_mode=config.parse_mode,
                timeout_ms=timeout_ms,
            )
        else:
            result = SimpleNotificationResult(
                success=False,
                platform="telegram",
                error="Invalid config type for Telegram",
            )

    elif platform == NotificationPlatform.SLACK:
        if isinstance(config, SlackNotificationConfig):
            result = await send_slack_webhook(
                webhook_url=config.webhook_url,
                text=event.content,
                username=config.username,
                icon_emoji=config.icon_emoji,
                timeout_ms=timeout_ms,
            )
        else:
            result = SimpleNotificationResult(
                success=False,
                platform="slack",
                error="Invalid config type for Slack",
            )

    elif platform == NotificationPlatform.WEBHOOK:
        if isinstance(config, WebhookNotificationConfig):
            payload = {"content": event.content, "event": event.event_type.value}
            result = await send_generic_webhook(
                webhook_url=config.webhook_url,
                payload=payload,
                timeout_ms=timeout_ms,
            )
        else:
            result = SimpleNotificationResult(
                success=False,
                platform="webhook",
                error="Invalid config type for webhook",
            )

    else:
        result = SimpleNotificationResult(
            success=False,
            platform=platform.value,
            error=f"Unsupported platform: {platform}",
        )

    duration_ms = (datetime.now() - start_time).total_seconds() * 1000

    return DispatchResult(
        platform=platform,
        success=result.success,
        error=result.error,
        status_code=result.status_code,
        duration_ms=duration_ms,
    )


# ===== Discord 辅助 =====
def compose_discord_content(
    message: str,
    mention: str | None,
) -> tuple[str, dict]:
    """组合 Discord 消息内容

    返回: (content, allowed_mentions)
    """
    mention_parsed = parse_mention_allowed_mentions(mention or '')
    allowed_mentions = {
        'parse': [],
        'users': mention_parsed.get('users', []),
        'roles': mention_parsed.get('roles', []),
    }

    if mention:
        prefix = f'{mention}\n'
        max_body = DISCORD_MAX_CONTENT_LENGTH - len(prefix)
        if len(message) > max_body:
            body = message[:max_body - 1] + '…'
        else:
            body = message
        content = f'{prefix}{body}'
    else:
        if len(message) > DISCORD_MAX_CONTENT_LENGTH:
            content = message[:DISCORD_MAX_CONTENT_LENGTH - 1] + '…'
        else:
            content = message

    return content, allowed_mentions


def _https_request(
    method: str,
    hostname: str,
    path: str,
    headers: dict,
    body: str,
    timeout_ms: int = SEND_TIMEOUT_MS,
) -> tuple[int, str]:
    """发送 HTTPS 请求（用于 Telegram）"""
    context = ssl.create_default_context()

    try:
        with socket.create_connection((hostname, 443), timeout=timeout_ms / 1000) as sock:
            with context.wrap_socket(sock, server_hostname=hostname) as ssock:
                request = (
                    f'{method} {path} HTTP/1.1\r\n'
                    f'Host: {hostname}\r\n'
                )
                for key, value in headers.items():
                    request += f'{key}: {value}\r\n'
                request += '\r\n'

                ssock.sendall(request.encode())
                ssock.sendall(body.encode())

                response = b''
                while True:
                    chunk = ssock.recv(4096)
                    if not chunk:
                        break
                    response += chunk
                    if b'\r\n\r\n' in response:
                        break

                # 解析状态码
                lines = response.split(b'\r\n')
                status_line = lines[0].decode('utf-8', errors='ignore')
                status_match = re.search(r'HTTP/\d\.\d\s+(\d+)', status_line)
                status_code = int(status_match.group(1)) if status_match else 0

                # 获取响应体
                body_start = response.find(b'\r\n\r\n')
                response_body = response[body_start + 4:].decode('utf-8', errors='ignore') if body_start > 0 else ''

                return status_code, response_body
    except Exception as e:
        return 0, str(e)


# ===== 平台发送函数 =====
async def send_discord(
    config: DiscordNotificationConfig,
    payload: FullNotificationPayload,
) -> NotificationResult:
    """发送 Discord webhook 通知"""
    if not config.enabled or not config.webhook_url:
        return NotificationResult(
            platform=NotificationPlatform.DISCORD,
            success=False,
            error='Not configured',
        )

    if not validate_discord_url(config.webhook_url):
        return NotificationResult(
            platform=NotificationPlatform.DISCORD,
            success=False,
            error='Invalid webhook URL',
        )

    try:
        import urllib.request

        content, allowed_mentions = compose_discord_content(
            payload.message,
            config.mention or None,
        )

        body = {'content': content, 'allowed_mentions': allowed_mentions}
        if config.username:
            body['username'] = config.username

        data = json.dumps(body).encode('utf-8')

        req = urllib.request.Request(
            config.webhook_url,
            data=data,
            headers={'Content-Type': 'application/json'},
            method='POST',
        )

        try:
            with urllib.request.urlopen(req, timeout=SEND_TIMEOUT_MS / 1000) as response:
                status = response.status
                if 200 <= status < 300:
                    return NotificationResult(
                        platform=NotificationPlatform.DISCORD,
                        success=True,
                    )
                else:
                    return NotificationResult(
                        platform=NotificationPlatform.DISCORD,
                        success=False,
                        error=f'HTTP {status}',
                    )
        except urllib.error.HTTPError as e:
            return NotificationResult(
                platform=NotificationPlatform.DISCORD,
                success=False,
                error=f'HTTP {e.code}',
            )
        except urllib.error.URLError as e:
            return NotificationResult(
                platform=NotificationPlatform.DISCORD,
                success=False,
                error=str(e.reason),
            )
    except Exception as e:
        return NotificationResult(
            platform=NotificationPlatform.DISCORD,
            success=False,
            error=str(e),
        )


async def send_discord_bot(
    config: DiscordBotNotificationConfig,
    payload: FullNotificationPayload,
) -> NotificationResult:
    """发送 Discord Bot API 通知"""
    if not config.enabled:
        return NotificationResult(
            platform=NotificationPlatform.DISCORD_BOT,
            success=False,
            error='Not enabled',
        )

    if not config.bot_token or not config.channel_id:
        return NotificationResult(
            platform=NotificationPlatform.DISCORD_BOT,
            success=False,
            error='Missing botToken or channelId',
        )

    try:
        import urllib.request

        content, allowed_mentions = compose_discord_content(
            payload.message,
            config.mention or None,
        )

        body = json.dumps({
            'content': content,
            'allowed_mentions': allowed_mentions,
        }).encode('utf-8')

        url = f'https://discord.com/api/v10/channels/{config.channel_id}/messages'
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bot {config.bot_token}',
        }

        req = urllib.request.Request(
            url,
            data=body,
            headers=headers,
            method='POST',
        )

        try:
            with urllib.request.urlopen(req, timeout=SEND_TIMEOUT_MS / 1000) as response:
                status = response.status
                if 200 <= status < 300:
                    # 尝试读取消息 ID
                    message_id = ''
                    try:
                        resp_data = json.loads(response.read().decode('utf-8'))
                        message_id = str(resp_data.get('id', ''))
                    except Exception:
                        pass
                    return NotificationResult(
                        platform=NotificationPlatform.DISCORD_BOT,
                        success=True,
                        message_id=message_id,
                    )
                else:
                    return NotificationResult(
                        platform=NotificationPlatform.DISCORD_BOT,
                        success=False,
                        error=f'HTTP {status}',
                    )
        except urllib.error.HTTPError as e:
            return NotificationResult(
                platform=NotificationPlatform.DISCORD_BOT,
                success=False,
                error=f'HTTP {e.code}',
            )
        except urllib.error.URLError as e:
            return NotificationResult(
                platform=NotificationPlatform.DISCORD_BOT,
                success=False,
                error=str(e.reason),
            )
    except Exception as e:
        return NotificationResult(
            platform=NotificationPlatform.DISCORD_BOT,
            success=False,
            error=str(e),
        )


async def send_telegram(
    config: TelegramNotificationConfig,
    payload: FullNotificationPayload,
) -> NotificationResult:
    """发送 Telegram 通知"""
    if not config.enabled or not config.bot_token or not config.chat_id:
        return NotificationResult(
            platform=NotificationPlatform.TELEGRAM,
            success=False,
            error='Not configured',
        )

    if not validate_telegram_token(config.bot_token):
        return NotificationResult(
            platform=NotificationPlatform.TELEGRAM,
            success=False,
            error='Invalid bot token format',
        )

    try:
        body = json.dumps({
            'chat_id': config.chat_id,
            'text': payload.message,
            'parse_mode': config.parse_mode or 'Markdown',
        })

        hostname = 'api.telegram.org'
        path = f'/bot{config.bot_token}/sendMessage'

        status_code, response_body = _https_request(
            'POST',
            hostname,
            path,
            {
                'Content-Type': 'application/json',
                'Content-Length': str(len(body)),
            },
            body,
            SEND_TIMEOUT_MS,
        )

        if 200 <= status_code < 300:
            # 尝试提取消息 ID
            message_id = ''
            try:
                resp_data = json.loads(response_body)
                if resp_data.get('ok') and resp_data.get('result'):
                    message_id = str(resp_data['result'].get('message_id', ''))
            except Exception:
                pass
            return NotificationResult(
                platform=NotificationPlatform.TELEGRAM,
                success=True,
                message_id=message_id,
            )
        else:
            return NotificationResult(
                platform=NotificationPlatform.TELEGRAM,
                success=False,
                error=f'HTTP {status_code}',
            )
    except Exception as e:
        return NotificationResult(
            platform=NotificationPlatform.TELEGRAM,
            success=False,
            error=str(e),
        )


async def send_slack(
    config: SlackNotificationConfig,
    payload: FullNotificationPayload,
) -> NotificationResult:
    """发送 Slack 通知"""
    if not config.enabled or not config.webhook_url:
        return NotificationResult(
            platform=NotificationPlatform.SLACK,
            success=False,
            error='Not configured',
        )

    if not validate_slack_url(config.webhook_url):
        return NotificationResult(
            platform=NotificationPlatform.SLACK,
            success=False,
            error='Invalid webhook URL',
        )

    try:
        import urllib.request

        body_dict: dict = {'text': payload.message}
        if config.channel:
            body_dict['channel'] = config.channel
        if config.username:
            body_dict['username'] = config.username

        body = json.dumps(body_dict).encode('utf-8')

        req = urllib.request.Request(
            config.webhook_url,
            data=body,
            headers={'Content-Type': 'application/json'},
            method='POST',
        )

        try:
            with urllib.request.urlopen(req, timeout=SEND_TIMEOUT_MS / 1000) as response:
                status = response.status
                if 200 <= status < 300:
                    return NotificationResult(
                        platform=NotificationPlatform.SLACK,
                        success=True,
                    )
                else:
                    return NotificationResult(
                        platform=NotificationPlatform.SLACK,
                        success=False,
                        error=f'HTTP {status}',
                    )
        except urllib.error.HTTPError as e:
            return NotificationResult(
                platform=NotificationPlatform.SLACK,
                success=False,
                error=f'HTTP {e.code}',
            )
        except urllib.error.URLError as e:
            return NotificationResult(
                platform=NotificationPlatform.SLACK,
                success=False,
                error=str(e.reason),
            )
    except Exception as e:
        return NotificationResult(
            platform=NotificationPlatform.SLACK,
            success=False,
            error=str(e),
        )


async def send_webhook(
    config: WebhookNotificationConfig,
    payload: FullNotificationPayload,
) -> NotificationResult:
    """发送通用 webhook 通知"""
    if not config.enabled or not config.url:
        return NotificationResult(
            platform=NotificationPlatform.WEBHOOK,
            success=False,
            error='Not configured',
        )

    if not validate_webhook_url(config.url):
        return NotificationResult(
            platform=NotificationPlatform.WEBHOOK,
            success=False,
            error='Invalid URL (HTTPS required)',
        )

    try:
        import urllib.request

        headers = {'Content-Type': 'application/json', **config.headers}
        body = json.dumps({
            'event': payload.event.value if isinstance(payload.event, NotificationEvent) else payload.event,
            'session_id': payload.session_id,
            'message': payload.message,
            'timestamp': payload.timestamp,
            'tmux_session': payload.tmux_session,
            'project_name': payload.project_name,
            'project_path': payload.project_path,
            'modes_used': payload.modes_used,
            'duration_ms': payload.duration_ms,
            'reason': payload.reason,
            'active_mode': payload.active_mode,
            'question': payload.question,
        }).encode('utf-8')

        req = urllib.request.Request(
            config.url,
            data=body,
            headers=headers,
            method=config.method or 'POST',
        )

        try:
            with urllib.request.urlopen(req, timeout=SEND_TIMEOUT_MS / 1000) as response:
                status = response.status
                if 200 <= status < 300:
                    return NotificationResult(
                        platform=NotificationPlatform.WEBHOOK,
                        success=True,
                    )
                else:
                    return NotificationResult(
                        platform=NotificationPlatform.WEBHOOK,
                        success=False,
                        error=f'HTTP {status}',
                    )
        except urllib.error.HTTPError as e:
            return NotificationResult(
                platform=NotificationPlatform.WEBHOOK,
                success=False,
                error=f'HTTP {e.code}',
            )
        except urllib.error.URLError as e:
            return NotificationResult(
                platform=NotificationPlatform.WEBHOOK,
                success=False,
                error=str(e.reason),
            )
    except Exception as e:
        return NotificationResult(
            platform=NotificationPlatform.WEBHOOK,
            success=False,
            error=str(e),
        )


# ===== 分发函数 =====
async def dispatch_notifications(
    config: FullNotificationConfig,
    event: NotificationEvent,
    payload: FullNotificationPayload,
) -> DispatchResult:
    """分发通知到所有已配置的平台

    参数:
        config: 通知配置
        event: 触发的事件
        payload: 通知负载

    返回:
        分发结果
    """
    if not config.enabled:
        return DispatchResult(event=event, results=[], any_success=False)

    promises: list = []
    platform_configs: list = []

    # Discord
    if config.discord and config.discord.enabled:
        promises.append(send_discord(config.discord, payload))
        platform_configs.append(('discord', config.discord))

    # Discord Bot
    if config.discord_bot and config.discord_bot.enabled:
        promises.append(send_discord_bot(config.discord_bot, payload))
        platform_configs.append(('discord-bot', config.discord_bot))

    # Telegram
    if config.telegram and config.telegram.enabled:
        promises.append(send_telegram(config.telegram, payload))
        platform_configs.append(('telegram', config.telegram))

    # Slack
    if config.slack and config.slack.enabled:
        promises.append(send_slack(config.slack, payload))
        platform_configs.append(('slack', config.slack))

    # Webhook
    if config.webhook and config.webhook.enabled:
        promises.append(send_webhook(config.webhook, payload))
        platform_configs.append(('webhook', config.webhook))

    if not promises:
        return DispatchResult(event=event, results=[], any_success=False)

    # 并发发送，带超时
    import asyncio

    try:
        results = await asyncio.wait_for(
            asyncio.gather(*promises, return_exceptions=True),
            timeout=DISPATCH_TIMEOUT_MS / 1000,
        )

        # 处理异常结果
        processed_results: list[NotificationResult] = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                platform = platform_configs[i][0] if i < len(platform_configs) else 'unknown'
                try:
                    platform_enum = NotificationPlatform(platform)
                except ValueError:
                    platform_enum = NotificationPlatform.WEBHOOK
                processed_results.append(NotificationResult(
                    platform=platform_enum,
                    success=False,
                    error=str(result),
                ))
            elif isinstance(result, NotificationResult):
                processed_results.append(result)
            else:
                processed_results.append(NotificationResult(
                    platform=NotificationPlatform.WEBHOOK,
                    success=False,
                    error='Unknown result type',
                ))

        return DispatchResult(
            event=event,
            results=processed_results,
            any_success=any(r.success for r in processed_results),
        )
    except asyncio.TimeoutError:
        return DispatchResult(
            event=event,
            results=[NotificationResult(
                platform=NotificationPlatform.WEBHOOK,
                success=False,
                error='Dispatch timeout',
            )],
            any_success=False,
        )
    except Exception as e:
        return DispatchResult(
            event=event,
            results=[NotificationResult(
                platform=NotificationPlatform.WEBHOOK,
                success=False,
                error=str(e),
            )],
            any_success=False,
        )


# ===== 导出 =====
__all__ = [
    "dispatch_notifications",
    "send_discord",
    "send_discord_bot",
    "send_slack",
    "send_telegram",
    "send_webhook",
    "validate_discord_url",
    "validate_slack_url",
    "validate_telegram_token",
    "validate_webhook_url",
]
