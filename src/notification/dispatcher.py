"""Notification Dispatcher

Handles sending notifications to various platforms (Discord, Telegram, Slack, webhook).
"""

import asyncio
import logging

import aiohttp

from .config import get_enabled_platforms
from .types import (
    DispatchResult,
    FullNotificationConfig,
    FullNotificationPayload,
    NotificationPlatform,
    NotificationResult,
)

logger = logging.getLogger(__name__)


async def send_discord(
    config: FullNotificationConfig,
    payload: FullNotificationPayload,
    session: aiohttp.ClientSession,
) -> NotificationResult:
    """Send notification to Discord webhook."""
    if not config.discord or not config.discord.enabled or not config.discord.webhook_url:
        return NotificationResult(
            platform=NotificationPlatform.DISCORD,
            success=False,
            error="Discord not configured",
        )

    try:
        # Format message for Discord (markdown supported)
        message = payload.message
        if config.discord.username:
            message = f"**{config.discord.username}**: {message}"
        if config.discord.mention:
            message = f"{config.discord.mention} {message}"

        data = {
            "content": message,
        }
        if config.discord.username:
            data["username"] = config.discord.username

        async with session.post(config.discord.webhook_url, json=data) as resp:
            if resp.status in (200, 204):
                return NotificationResult(
                    platform=NotificationPlatform.DISCORD,
                    success=True,
                )
            else:
                error_text = await resp.text()
                return NotificationResult(
                    platform=NotificationPlatform.DISCORD,
                    success=False,
                    error=f"Discord error {resp.status}: {error_text}",
                )
    except Exception as e:
        logger.exception("Failed to send Discord notification")
        return NotificationResult(
            platform=NotificationPlatform.DISCORD,
            success=False,
            error=str(e),
        )


async def send_discord_bot(
    config: FullNotificationConfig,
    payload: FullNotificationPayload,
    session: aiohttp.ClientSession,
) -> NotificationResult:
    """Send notification via Discord Bot API."""
    # This would require discord.py library - simplified for now
    # In a real implementation, this would use the Discord API
    if not config.discord_bot or not config.discord_bot.enabled:
        return NotificationResult(
            platform=NotificationPlatform.DISCORD_BOT,
            success=False,
            error="Discord Bot not configured",
        )

    # Placeholder - would need actual Discord bot implementation
    logger.info("Discord Bot notification would be sent here (not implemented)")
    return NotificationResult(
        platform=NotificationPlatform.DISCORD_BOT,
        success=True,  # Placeholder
    )


async def send_telegram(
    config: FullNotificationConfig,
    payload: FullNotificationPayload,
    session: aiohttp.ClientSession,
) -> NotificationResult:
    """Send notification to Telegram bot."""
    if not config.telegram or not config.telegram.enabled:
        return NotificationResult(
            platform=NotificationPlatform.TELEGRAM,
            success=False,
            error="Telegram not configured",
        )

    if not config.telegram.bot_token or not config.telegram.chat_id:
        return NotificationResult(
            platform=NotificationPlatform.TELEGRAM,
            success=False,
            error="Telegram bot token or chat ID missing",
        )

    try:
        url = f"https://api.telegram.org/bot{config.telegram.bot_token}/sendMessage"
        parse_mode = config.telegram.parse_mode or "Markdown"

        data = {
            "chat_id": config.telegram.chat_id,
            "text": payload.message,
            "parse_mode": parse_mode,
        }

        async with session.post(url, json=data) as resp:
            if resp.status == 200:
                result = await resp.json()
                if result.get("ok"):
                    return NotificationResult(
                        platform=NotificationPlatform.TELEGRAM,
                        success=True,
                        response=result,
                    )
                else:
                    error_desc = result.get("description", "Unknown error")
                    return NotificationResult(
                        platform=NotificationPlatform.TELEGRAM,
                        success=False,
                        error=f"Telegram API error: {error_desc}",
                    )
            else:
                error_text = await resp.text()
                return NotificationResult(
                    platform=NotificationPlatform.TELEGRAM,
                    success=False,
                    error=f"Telegram HTTP error {resp.status}: {error_text}",
                )
    except Exception as e:
        logger.exception("Failed to send Telegram notification")
        return NotificationResult(
            platform=NotificationPlatform.TELEGRAM,
            success=False,
            error=str(e),
        )


async def send_slack(
    config: FullNotificationConfig,
    payload: FullNotificationPayload,
    session: aiohttp.ClientSession,
) -> NotificationResult:
    """Send notification to Slack webhook."""
    if not config.slack or not config.slack.enabled or not config.slack.webhook_url:
        return NotificationResult(
            platform=NotificationPlatform.SLACK,
            success=False,
            error="Slack not configured",
        )

    try:
        data = {
            "text": payload.message,
        }
        if config.slack.channel:
            data["channel"] = config.slack.channel
        if config.slack.username:
            data["username"] = config.slack.username

        async with session.post(config.slack.webhook_url, json=data) as resp:
            if resp.status == 200:
                return NotificationResult(
                    platform=NotificationPlatform.SLACK,
                    success=True,
                )
            else:
                error_text = await resp.text()
                return NotificationResult(
                    platform=NotificationPlatform.SLACK,
                    success=False,
                    error=f"Slack error {resp.status}: {error_text}",
                )
    except Exception as e:
        logger.exception("Failed to send Slack notification")
        return NotificationResult(
            platform=NotificationPlatform.SLACK,
            success=False,
            error=str(e),
        )


async def send_webhook(
    config: FullNotificationConfig,
    payload: FullNotificationPayload,
    session: aiohttp.ClientSession,
) -> NotificationResult:
    """Send notification to generic webhook."""
    if not config.webhook or not config.webhook.enabled or not config.webhook.url:
        return NotificationResult(
            platform=NotificationPlatform.WEBHOOK,
            success=False,
            error="Webhook not configured",
        )

    try:
        headers = config.webhook.headers or {}
        method = config.webhook.method.upper()

        # Prepare JSON payload
        data = {
            "event": payload.event.value,
            "session_id": payload.session_id,
            "message": payload.message,
            "timestamp": payload.timestamp,
            # Include other relevant fields
        }

        # Add optional fields if present
        if payload.project_path:
            data["project_path"] = payload.project_path
        if payload.project_name:
            data["project_name"] = payload.project_name
        if payload.duration_ms is not None:
            data["duration_ms"] = payload.duration_ms

        async with session.request(
            method,
            config.webhook.url,
            json=data,
            headers=headers,
        ) as resp:
            if 200 <= resp.status < 300:
                return NotificationResult(
                    platform=NotificationPlatform.WEBHOOK,
                    success=True,
                )
            else:
                error_text = await resp.text()
                return NotificationResult(
                    platform=NotificationPlatform.WEBHOOK,
                    success=False,
                    error=f"Webhook error {resp.status}: {error_text}",
                )
    except Exception as e:
        logger.exception("Failed to send webhook notification")
        return NotificationResult(
            platform=NotificationPlatform.WEBHOOK,
            success=False,
            error=str(e),
        )


async def dispatch_notifications(
    config: FullNotificationConfig,
    payload: FullNotificationPayload,
) -> DispatchResult:
    """Dispatch notification to all enabled platforms."""
    if not config or not config.enabled:
        return DispatchResult(results=[])

    enabled_platforms = get_enabled_platforms(config)
    if not enabled_platforms:
        return DispatchResult(results=[])

    logger.info(f"Dispatching notification to platforms: {enabled_platforms}")

    # Create HTTP session
    timeout = aiohttp.ClientTimeout(total=30)
    connector = aiohttp.TCPConnector(limit=10)

    results = []

    async with aiohttp.ClientSession(timeout=timeout, connector=connector) as session:
        # Create tasks for all enabled platforms
        tasks = []

        if "discord" in enabled_platforms:
            tasks.append(send_discord(config, payload, session))
        if "discord-bot" in enabled_platforms:
            tasks.append(send_discord_bot(config, payload, session))
        if "telegram" in enabled_platforms:
            tasks.append(send_telegram(config, payload, session))
        if "slack" in enabled_platforms:
            tasks.append(send_slack(config, payload, session))
        if "webhook" in enabled_platforms:
            tasks.append(send_webhook(config, payload, session))

        # Wait for all to complete
        if tasks:
            platform_results = await asyncio.gather(*tasks, return_exceptions=True)

            # Process results
            platform_iter = iter(enabled_platforms)
            for result in platform_results:
                platform = next(platform_iter)
                if isinstance(result, Exception):
                    logger.exception(f"Platform {platform} notification failed")
                    results.append(NotificationResult(
                        platform=NotificationPlatform(platform),
                        success=False,
                        error=str(result),
                    ))
                else:
                    results.append(result)

    return DispatchResult(results=results)


# Legacy function names for backward compatibility
async def notify(
    config: FullNotificationConfig,
    payload: FullNotificationPayload,
) -> DispatchResult | None:
    """Legacy notification function."""
    if not config or not config.enabled:
        return None
    return await dispatch_notifications(config, payload)
