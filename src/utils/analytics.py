"""Analytics - Telemetry from Aider

Adapted from aider/analytics.py
Provides: Optional telemetry with Mixpanel/PostHog (disabled by default)
"""

import contextlib
import json
import platform
import sys
import time
import uuid
from pathlib import Path


class Analytics:
    """Optional analytics tracking (disabled by default)."""

    # Provider instances
    mp = None
    ph = None

    # Persistent data
    user_id = None
    permanently_disable = None
    asked_opt_in = None

    # Ephemeral state
    logfile = None

    # Config
    PERCENT = 10  # Only track 10% of users by default

    def __init__(
        self,
        logfile=None,
        permanently_disable=True,  # Default to disabled!
        posthog_host=None,
        posthog_project_api_key=None,
    ):
        self.logfile = logfile
        self.get_or_create_uuid()
        self.custom_posthog_host = posthog_host
        self.custom_posthog_project_api_key = posthog_project_api_key

        # Default to disabled
        if self.permanently_disable is None:
            self.permanently_disable = True
        if self.asked_opt_in is None:
            self.asked_opt_in = True

        if self.permanently_disable or permanently_disable:
            self.disable(True)

    @staticmethod
    def compute_hex_threshold(percent):
        """Convert percentage to 6-digit hex threshold."""
        return format(int(0xFFFFFF * percent / 100), "06x")

    @staticmethod
    def is_uuid_in_percentage(uuid_str, percent):
        """Check if a UUID falls within the first X percent of UUID space."""
        if not (0 <= percent <= 100):
            raise ValueError("Percentage must be between 0 and 100")
        if not uuid_str:
            return False
        if percent == 0:
            return False
        threshold = Analytics.compute_hex_threshold(percent)
        return uuid_str[:6] <= threshold

    def enable(self):
        """Enable analytics."""
        if not self.user_id:
            self.disable(False)
            return
        if self.permanently_disable:
            self.disable(True)
            return
        if not self.asked_opt_in:
            self.disable(False)
            return

        # Try to enable PostHog (optional dependency)
        try:
            from posthog import Posthog
            posthog_host = self.custom_posthog_host or "https://us.i.posthog.com"
            posthog_key = self.custom_posthog_project_api_key or "phc_xxx"
            self.ph = Posthog(
                project_api_key=posthog_key,
                host=posthog_host,
                on_error=self._posthog_error,
                enable_exception_autocapture=True,
                super_properties=self.get_system_info(),
            )
        except ImportError:
            pass  # PostHog not installed, skip

    def disable(self, permanently):
        """Disable analytics."""
        self.mp = None
        self.ph = None
        if permanently:
            self.asked_opt_in = True
            self.permanently_disable = True
            self.save_data()

    def need_to_ask(self, args_analytics):
        """Check if we should ask user about analytics."""
        if args_analytics is False:
            return False
        could_ask = not self.asked_opt_in and not self.permanently_disable
        if not could_ask:
            return False
        if args_analytics is True:
            return True
        if not self.user_id:
            return False
        return self.is_uuid_in_percentage(self.user_id, self.PERCENT)

    def get_data_file_path(self):
        """Get the analytics data file path."""
        try:
            data_file = Path.home() / ".clawd" / "analytics.json"
            data_file.parent.mkdir(parents=True, exist_ok=True)
            return data_file
        except OSError:
            self.disable(permanently=False)
            return None

    def get_or_create_uuid(self):
        """Get or create user UUID."""
        self.load_data()
        if self.user_id:
            return
        self.user_id = str(uuid.uuid4())
        self.save_data()

    def load_data(self):
        """Load analytics data from file."""
        data_file = self.get_data_file_path()
        if not data_file:
            return
        if data_file.exists():
            try:
                data = json.loads(data_file.read_text())
                self.permanently_disable = data.get("permanently_disable")
                self.user_id = data.get("uuid")
                self.asked_opt_in = data.get("asked_opt_in", False)
            except (json.JSONDecodeError, OSError):
                self.disable(permanently=False)

    def save_data(self):
        """Save analytics data to file."""
        data_file = self.get_data_file_path()
        if not data_file:
            return
        data = dict(
            uuid=self.user_id,
            permanently_disable=self.permanently_disable,
            asked_opt_in=self.asked_opt_in,
        )
        try:
            data_file.write_text(json.dumps(data, indent=4))
        except OSError:
            self.disable(permanently=False)

    def get_system_info(self):
        """Get system information for telemetry."""
        try:
            from aider import __version__
            version = __version__
        except ImportError:
            version = "unknown"

        return {
            "python_version": sys.version.split()[0],
            "os_platform": platform.system(),
            "os_release": platform.release(),
            "machine": platform.machine(),
            "clawd_version": version,
        }

    def _posthog_error(self):
        """Disable PostHog on error."""
        self.ph = None

    def event(self, event_name, main_model=None, **kwargs):
        """Track an analytics event."""
        if not self.mp and not self.ph and not self.logfile:
            return

        properties = {}

        if main_model:
            if hasattr(main_model, 'name'):
                properties["main_model"] = main_model.name
            if hasattr(main_model, 'weak_model') and main_model.weak_model:
                properties["weak_model"] = main_model.weak_model.name

        properties.update(kwargs)

        # Convert numeric values
        for key, value in properties.items():
            if isinstance(value, (int, float)):
                properties[key] = value
            else:
                properties[key] = str(value)

        if self.ph:
            with contextlib.suppress(Exception):
                self.ph.capture(
                    event_name,
                    distinct_id=self.user_id,
                    properties=dict(properties)
                )

        if self.logfile:
            log_entry = {
                "event": event_name,
                "properties": properties,
                "user_id": self.user_id,
                "time": int(time.time()),
            }
            try:
                with open(self.logfile, "a") as f:
                    json.dump(log_entry, f)
                    f.write("\n")
            except OSError:
                pass


# Global singleton
_analytics = None


def get_analytics(disable=True) -> Analytics:
    """Get or create the global Analytics instance."""
    global _analytics
    if _analytics is None:
        _analytics = Analytics(permanently_disable=disable)
    return _analytics


def track_event(event_name, **kwargs):
    """Track an event using the global analytics instance."""
    analytics = get_analytics()
    analytics.event(event_name, **kwargs)


__all__ = [
    "Analytics",
    "get_analytics",
    "track_event",
]
