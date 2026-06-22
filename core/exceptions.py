"""Custom exceptions for the NEPSE trading bot."""


class NepseBotError(Exception):
    """Base exception for all bot errors."""

    def __init__(self, message: str, details: dict | None = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}


class BrokerError(NepseBotError):
    """Broker interaction failure."""


class LoginError(BrokerError):
    """Authentication failure."""


class SessionExpiredError(BrokerError):
    """Trading session has expired."""


class CaptchaDetectedError(BrokerError):
    """CAPTCHA challenge detected during login."""


class OrderError(NepseBotError):
    """Order placement or execution failure."""


class RiskLimitError(NepseBotError):
    """Risk management limit breached."""


class StrategyError(NepseBotError):
    """Strategy evaluation or configuration error."""


class MarketDataError(NepseBotError):
    """Market data feed error."""


class ConfigurationError(NepseBotError):
    """Invalid configuration."""


class KillSwitchActiveError(RiskLimitError):
    """Emergency kill switch is active."""
