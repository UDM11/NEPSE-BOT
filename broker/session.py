"""Browser session management with auto re-login."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from core.config import get_app_config, get_settings
from core.events import Event, EventBus, EventType
from core.exceptions import SessionExpiredError
from core.logging_config import get_logger

logger = get_logger("session_manager")


class SessionManager:
    """Track broker session state and trigger re-login when expired."""

    def __init__(self, event_bus: EventBus):
        self.event_bus = event_bus
        settings = get_settings()
        app_config = get_app_config()
        broker_config = app_config.get("broker", {})

        self.session_timeout = timedelta(
            minutes=settings.broker_session_timeout_minutes
        )
        self.auto_relogin = broker_config.get("auto_relogin", True)
        self._logged_in = False
        self._last_activity: datetime | None = None
        self._login_lock = asyncio.Lock()

    @property
    def is_logged_in(self) -> bool:
        return self._logged_in

    def mark_logged_in(self) -> None:
        self._logged_in = True
        self._last_activity = datetime.now(timezone.utc)
        logger.info("session_active")

    def mark_logged_out(self) -> None:
        self._logged_in = False
        self._last_activity = None
        logger.info("session_inactive")

    def touch(self) -> None:
        """Update last activity timestamp."""
        self._last_activity = datetime.now(timezone.utc)

    def is_expired(self) -> bool:
        if not self._logged_in or not self._last_activity:
            return True
        return datetime.now(timezone.utc) - self._last_activity > self.session_timeout

    async def ensure_session(self, login_callback) -> bool:
        """Ensure valid session, re-login if needed."""
        async with self._login_lock:
            if self._logged_in and not self.is_expired():
                return True

            if not self.auto_relogin:
                await self._publish_session_expired()
                raise SessionExpiredError("Session expired and auto-relogin disabled")

            logger.info("session_relogin_attempt")
            success = await login_callback()
            if success:
                self.mark_logged_in()
                return True

            await self._publish_session_expired()
            return False

    async def _publish_session_expired(self) -> None:
        self.mark_logged_out()
        await self.event_bus.publish(
            Event(
                type=EventType.SESSION_EXPIRED,
                source="session_manager",
                data={"auto_relogin": self.auto_relogin},
            )
        )

    def get_status(self) -> dict:
        return {
            "logged_in": self._logged_in,
            "last_activity": self._last_activity.isoformat() if self._last_activity else None,
            "is_expired": self.is_expired(),
            "auto_relogin": self.auto_relogin,
        }
