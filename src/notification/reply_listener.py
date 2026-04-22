"""Reply Listener Daemon for bidirectional communication with Discord/Telegram."""

import json
import os
import stat
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .types import ReplyListenerDaemonConfig, ReplyListenerState


@dataclass
class RateLimiter:
    """Rate limiter to prevent abuse."""
    max_per_second: float = 1.0
    max_burst: int = 5
    _tokens: float = field(init=False)
    _last_time: float = field(init=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False)

    def __post_init__(self):
        self._tokens = float(self.max_burst)
        self._last_time = time.time()

    def can_proceed(self) -> bool:
        """Check if action is allowed under rate limit."""
        with self._lock:
            now = time.time()
            # Add tokens based on elapsed time
            elapsed = now - self._last_time
            self._tokens = min(self._tokens + elapsed * self.max_per_second, float(self.max_burst))
            self._last_time = now

            if self._tokens >= 1.0:
                self._tokens -= 1.0
                return True
            return False


class ReplyListener:
    """Daemon for listening to replies from Discord/Telegram."""

    def __init__(self, config: ReplyListenerDaemonConfig, state_dir: Path | None = None):
        self.config = config
        self.state_dir = state_dir or Path.home() / ".claw" / "reply_listener"
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self._state_file = self.state_dir / "state.json"
        self._pid_file = self.state_dir / "pid"
        self._log_file = self.state_dir / "log.txt"
        self._running = False
        self._thread: threading.Thread | None = None
        self._rate_limiter = RateLimiter(
            max_per_second=config.rate_limit_per_second,
            max_burst=config.rate_limit_burst
        )
        self._state: ReplyListenerState | None = None
        self._message_handler: Callable[[str, str, str], None] | None = None

    def _set_secure_permissions(self, file_path: Path) -> None:
        """Set file permissions to owner read/write only (0600)."""
        try:
            file_path.chmod(stat.S_IRUSR | stat.S_IWUSR)
        except (OSError, PermissionError):
            pass  # Best effort

    def _load_state(self) -> ReplyListenerState:
        """Load state from file or create default."""
        if self._state_file.exists():
            try:
                with open(self._state_file) as f:
                    data = json.load(f)
                    # Ensure required fields exist
                    state = ReplyListenerState(
                        last_discord_id=data.get('last_discord_id', '0'),
                        last_telegram_update_id=data.get('last_telegram_update_id', 0),
                        authorized_users=data.get('authorized_users', []),
                        rate_limited=data.get('rate_limited', False),
                        last_rate_limit_reset=data.get('last_rate_limit_reset', 0)
                    )
                    return state
            except (OSError, json.JSONDecodeError, KeyError):
                pass  # Fall back to default state
        # Default state
        state = ReplyListenerState(
            last_discord_id='0',
            last_telegram_update_id=0,
            authorized_users=list(self.config.authorized_users or []),
            rate_limited=False,
            last_rate_limit_reset=0
        )
        self._save_state(state)
        return state

    def _save_state(self, state: ReplyListenerState) -> None:
        """Save state to file with secure permissions."""
        try:
            data = {
                'last_discord_id': state.last_discord_id,
                'last_telegram_update_id': state.last_telegram_update_id,
                'authorized_users': state.authorized_users,
                'rate_limited': state.rate_limited,
                'last_rate_limit_reset': state.last_rate_limit_reset
            }
            with open(self._state_file, 'w') as f:
                json.dump(data, f, indent=2)
            self._set_secure_permissions(self._state_file)
        except OSError:
            pass  # Best effort

    def _write_pid_file(self) -> None:
        """Write current PID to pid file."""
        try:
            with open(self._pid_file, 'w') as f:
                f.write(str(os.getpid()))
            self._set_secure_permissions(self._pid_file)
        except OSError:
            pass

    def _remove_pid_file(self) -> None:
        """Remove pid file."""
        try:
            if self._pid_file.exists():
                self._pid_file.unlink()
        except OSError:
            pass

    def _log(self, message: str) -> None:
        """Write log message with timestamp."""
        try:
            timestamp = time.strftime('%Y-%m-%d %H:%M:%S')
            log_line = f"[{timestamp}] {message}\n"
            with open(self._log_file, 'a', encoding='utf-8') as f:
                f.write(log_line)
            self._set_secure_permissions(self._log_file)
        except OSError:
            pass

    def start(self) -> bool:
        """Start the reply listener daemon."""
        if self._running:
            self._log("Reply listener already running")
            return False

        # Normalize and validate config
        try:
            normalized_config = normalize_reply_listener_config(self.config)
        except ValueError as e:
            self._log(f"Configuration validation failed: {e}")
            return False

        self.config = normalized_config
        self._state = self._load_state()
        self._running = True
        self._thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._thread.start()
        self._write_pid_file()
        self._log("Reply listener started")
        return True

    def stop(self) -> bool:
        """Stop the reply listener daemon."""
        if not self._running:
            self._log("Reply listener not running")
            return False

        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5.0)
        self._remove_pid_file()
        self._log("Reply listener stopped")
        return True

    def is_running(self) -> bool:
        """Check if the daemon is running."""
        if not self._running:
            return False
        # Also check pid file for safety
        if self._pid_file.exists():
            try:
                with open(self._pid_file) as f:
                    pid = int(f.read().strip())
                # Check if process exists (simplified)
                return pid == os.getpid()
            except (OSError, ValueError):
                pass
        return False

    def get_status(self) -> dict[str, Any]:
        """Get current status."""
        return {
            'running': self.is_running(),
            'pid': self._get_pid(),
            'state': self._state.__dict__ if self._state else None,
            'config': {
                'enabled': self.config.enabled,
                'platforms': {
                    'discord': self.config.discord_enabled,
                    'telegram': self.config.telegram_enabled
                },
                'rate_limit': {
                    'per_second': self.config.rate_limit_per_second,
                    'burst': self.config.rate_limit_burst
                }
            }
        }

    def _get_pid(self) -> int | None:
        """Get PID from pid file."""
        if not self._pid_file.exists():
            return None
        try:
            with open(self._pid_file) as f:
                return int(f.read().strip())
        except (OSError, ValueError):
            return None

    def set_message_handler(self, handler: Callable[[str, str, str], None]) -> None:
        """Set handler for processing received messages.
        Handler signature: handler(platform, user_id, message_text)
        """
        self._message_handler = handler

    def _poll_loop(self) -> None:
        """Main polling loop."""
        self._log("Reply listener poll loop started")
        poll_interval = getattr(self.config, 'poll_interval_seconds', 5.0)
        while self._running:
            try:
                self._poll_once()
                time.sleep(poll_interval)
            except Exception as e:
                self._log(f"Error in poll loop: {e}")
                time.sleep(poll_interval)  # Continue after error

    def _poll_once(self) -> None:
        """Single polling iteration for all platforms."""
        # Poll Discord
        if self.config.discord_enabled and self.config.discordBotToken:
            try:
                self._poll_discord()
            except Exception as e:
                self._log(f"Discord polling error: {e}")

        # Poll Telegram
        if self.config.telegram_enabled and self.config.telegramBotToken:
            try:
                self._poll_telegram()
            except Exception as e:
                self._log(f"Telegram polling error: {e}")

    def _poll_discord(self) -> None:
        """Poll Discord for new messages (placeholder)."""
        # TODO: Implement actual Discord API polling
        # This would involve:
        # 1. Getting messages from Discord channel(s)
        # 2. Filtering for new messages since last_discord_id
        # 3. Checking if user is authorized
        # 4. Rate limiting
        # 5. Processing messages via message handler
        # 6. Updating last_discord_id
        pass

    def _poll_telegram(self) -> None:
        """Poll Telegram for new messages (placeholder)."""
        # TODO: Implement actual Telegram API polling
        # This would involve:
        # 1. Getting updates from Telegram Bot API
        # 2. Filtering for new messages since last_telegram_update_id
        # 3. Checking if chat/user is authorized
        # 4. Rate limiting
        # 5. Processing messages via message handler
        # 6. Updating last_telegram_update_id
        pass

    def _process_message(self, platform: str, user_id: str, message_text: str) -> None:
        """Process a received message."""
        # Check authorization
        if not self._is_authorized(user_id):
            self._log(f"Unauthorized {platform} user {user_id} attempted to send message")
            return

        # Check rate limit
        if not self._rate_limiter.can_proceed():
            self._log(f"Rate limit exceeded for {platform} user {user_id}")
            self._state.rate_limited = True
            self._state.last_rate_limit_reset = int(time.time())
            self._save_state(self._state)
            return

        # Reset rate limited flag if we're here
        if self._state.rate_limited:
            self._state.rate_limited = False
            self._save_state(self._state)

        # Process message via handler
        if self._message_handler:
            try:
                self._message_handler(platform, user_id, message_text)
            except Exception as e:
                self._log(f"Error in message handler: {e}")
        else:
            self._log(f"Received {platform} message from {user_id}: {message_text[:100]}")

    def _is_authorized(self, user_id: str) -> bool:
        """Check if user is authorized to send replies."""
        if not self.config.authorized_users:
            # If no authorized users list, allow all (not recommended for production)
            return True
        return user_id in self.config.authorized_users


def normalize_reply_listener_config(config: ReplyListenerDaemonConfig) -> ReplyListenerDaemonConfig:
    """Normalize and validate reply listener configuration.
    Returns a normalized config with defaults applied and values validated.
    """
    # Create a copy to avoid modifying original
    normalized = ReplyListenerDaemonConfig(
        enabled=config.enabled,
        discord_enabled=config.discord_enabled,
        telegram_enabled=config.telegram_enabled,
        discordBotToken=config.discordBotToken,
        telegramBotToken=config.telegramBotToken,
        authorized_users=list(config.authorized_users or []),
        rate_limit_per_second=max(0.1, float(config.rate_limit_per_second or 1.0)),
        rate_limit_burst=max(1, int(config.rate_limit_burst or 5)),
        poll_interval_seconds=max(1.0, float(getattr(config, 'poll_interval_seconds', 5.0))),
        state_dir=getattr(config, 'state_dir', None)
    )

    # Infer enabled flags from credentials if not explicitly set
    if not config.discord_enabled and config.discordBotToken:
        normalized.discord_enabled = True
    if not config.telegram_enabled and config.telegramBotToken:
        normalized.telegram_enabled = True

    # Ensure at least one platform is enabled if credentials exist
    if not normalized.discord_enabled and not normalized.telegram_enabled:
        if config.discordBotToken or config.telegramBotToken:
            # Enable platforms that have credentials
            if config.discordBotToken:
                normalized.discord_enabled = True
            if config.telegramBotToken:
                normalized.telegram_enabled = True

    return normalized


def create_reply_listener_from_config(
    config: ReplyListenerDaemonConfig | None = None,
    cwd: str | None = None
) -> ReplyListener | None:
    """Factory function to create reply listener from configuration.
    If config is None, attempts to load from environment/file.
    """
    if config is None:
        # In a real implementation, this would load from config file/environment
        # For now, return None to indicate configuration must be provided
        return None

    # Normalize the config
    try:
        normalized_config = normalize_reply_listener_config(config)
    except ValueError:
        return None

    return ReplyListener(normalized_config)
