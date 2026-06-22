"""Application configuration with environment and YAML support."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """Environment-based settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = "development"
    app_name: str = "nepse-trading-bot"
    log_level: str = "INFO"
    secret_key: SecretStr = Field(default="change-me")

    database_url: str = "sqlite+aiosqlite:///./data/nepse_bot.db"
    redis_url: str = "redis://localhost:6379/0"
    redis_enabled: bool = False

    broker_url: str = ""
    broker_profile: str = "naasa"
    broker_username: str = ""
    broker_password: SecretStr = Field(default="")
    broker_client_code: str = ""
    broker_headless: bool = True
    broker_debug_screenshots: bool = True
    broker_session_timeout_minutes: int = 30


    risk_daily_capital_limit: float = 500_000.0
    risk_max_quantity_per_order: int = 1000
    risk_max_exposure: float = 1_000_000.0
    risk_max_consecutive_failures: int = 5
    risk_kill_switch: bool = False

    dashboard_host: str = "0.0.0.0"
    dashboard_port: int = 8080

    credential_encryption_key: SecretStr = Field(default="")

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()


def load_yaml_config(path: str | Path) -> dict[str, Any]:
    """Load YAML configuration file."""
    config_path = Path(path)
    if not config_path.is_absolute():
        config_path = PROJECT_ROOT / config_path
    if not config_path.exists():
        return {}
    with open(config_path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def get_broker_config() -> dict[str, Any]:
    """Load broker-specific YAML profile and merge with app config."""
    app_config = get_app_config()
    broker_section = app_config.get("broker", {})
    profile = broker_section.get("profile", "naasa")
    profile_path = broker_section.get("config_file", f"config/brokers/{profile}.yaml")
    profile_config = load_yaml_config(profile_path)

    merged = {**broker_section}
    if profile_config:
        merged["profile_config"] = profile_config
        # Merge selectors: app defaults < profile overrides
        profile_selectors = profile_config.get("selectors", {})
        merged["selectors"] = {**broker_section.get("selectors", {}), **profile_selectors}
        # Use profile URLs if broker_url not set in env
        urls = profile_config.get("urls", {})
        merged["urls"] = urls
    return merged


def get_app_config() -> dict[str, Any]:
    """Load main application YAML config."""
    return load_yaml_config(PROJECT_ROOT / "config" / "settings.yaml")
