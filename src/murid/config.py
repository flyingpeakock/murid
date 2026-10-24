"""Module for loading and validating the configuration for the Murid application."""

import logging
import os
from io import StringIO
from typing import Any

import yaml
from pydantic import ValidationError

from .config_models import MuridSettings

logger = logging.getLogger("murid")


_GET_DEFAULT = object()


class ConfigError(Exception):
    """Custom exception for configuration-related errors."""


def hardcover_list_settings(entries: list) -> list[dict]:
    """Expand each account's grouped lists into independent runtime requests."""
    return [
        {
            "api_key": entry["api_key"],
            "list": slug,
            "media_types": [media] if isinstance(media, str) else list(media),
        }
        for entry in entries
        for slug, options in entry["reading_list"].items()
        for media in [options.get("type", "ebook")]
    ]


def requested_media_types(entries: list[dict]) -> set[str]:
    """Return the libraries required by normalized Hardcover list settings."""
    return {media for entry in entries for media in entry["media_types"]}


def env_constructor(loader: yaml.SafeLoader, node: yaml.Node) -> str:
    """YAML constructor for the !ENV tag to load values from environment variables."""
    env_var = loader.construct_scalar(node)
    value = os.getenv(env_var)
    if value is None:
        raise ConfigError(f"Environment variable '{env_var}' not found") from None
    return value


class Config:
    """Class for loading and validating the configuration for the Murid application."""

    def __init__(self, config_file: StringIO) -> None:
        """Initialize the Config class by loading and validating the configuration."""
        try:
            yaml.SafeLoader.add_constructor("!ENV", env_constructor)
            config = yaml.load(config_file, Loader=yaml.SafeLoader)
        except yaml.YAMLError as e:
            raise ConfigError(f"Error parsing config file: {e}") from e
        self._config = self._sanitize(config if config is not None else {})

        self.validate()
        logger.debug("Configuration loaded")

    def get(self, key: str, default: Any = _GET_DEFAULT) -> Any:
        """Get a config value by key, with an optional default if the key is not found."""
        if key in self._config:
            return self._config[key]
        if default is not _GET_DEFAULT:
            return default
        raise KeyError(f"Config item '{key}' not found in config file")

    @staticmethod
    def _sanitize(value: Any) -> Any:
        """Recursively sanitize config values.

        By striping whitespace and resolving environment variables.
        """
        if isinstance(value, str):
            value = value.strip()
            if value.startswith("!ENV"):
                env_var = value.removeprefix("!ENV").strip()
                env_value = os.getenv(env_var)
                if env_value is None:
                    raise ConfigError(f"Environment variable '{env_var}' not found")
                return env_value.strip()
            return value
        if isinstance(value, list):
            return [Config._sanitize(item) for item in value]
        if isinstance(value, dict):
            return {Config._sanitize(key): Config._sanitize(val) for key, val in value.items()}
        return value

    @staticmethod
    def redact(data: Any) -> dict:
        """Recursively redact sensitive data from the provided data structure."""
        sensitive_keys = [
            "api_key",
            "mam_id",
            "token",
            "password",
            "hardcover_api_keys",
            "server_password",
            "apprise",  # Notification URLs can contain credentials in any component.
        ]
        if isinstance(data, dict):
            return {
                key: ("**REDACTED**" if key in sensitive_keys else Config.redact(value))
                for key, value in data.items()
            }
        if isinstance(data, list):
            return [Config.redact(item) for item in data]
        return data

    def validate(self) -> None:
        """Validate settings and retain the dictionary interface used by callers."""
        try:
            settings = MuridSettings.model_validate(self._config)
        except ValidationError as error:
            messages = [
                f"{'.'.join(map(str, item['loc'])) or 'config'}: {item['msg']}"
                for item in error.errors(
                    include_input=False, include_context=False, include_url=False
                )
            ]
            raise ConfigError("Invalid configuration:\n" + "\n".join(messages)) from None
        self._config = settings.model_dump()
        # Keep omitted per-list options omitted in print-config output.
        self._config["hardcover_api_keys"] = [
            entry.model_dump(exclude_unset=True) for entry in settings.hardcover_api_keys
        ]
        self.hardcover_lists = hardcover_list_settings(self._config["hardcover_api_keys"])
        for key in settings.model_extra or {}:
            logger.warning("Unexpected config item %r found in config file", key)

    def copy(self) -> dict:
        """Return a copy of the configuration dictionary."""
        return self._config.copy()

    def __getattr__(self, name: str) -> Any:
        """Allow attribute-like access to config items."""
        try:
            return self._config[name]
        except KeyError:
            raise AttributeError(f"Config item '{name}' not found in config file") from None

    def __len__(self) -> int:
        """Allow dict-like access to get the number of config items."""
        return len(self._config)

    def __iter__(self):
        """Allow dict-like access to iterate over config items."""
        return iter(self._config)

    def __contains__(self, key: str) -> bool:
        """Allow dict-like access to check if a config item exists."""
        return key in self._config

    def __getitem__(self, key: str) -> Any:
        """Allow dict-like access to config items."""
        return self.get(key)

    def __str__(self) -> str:
        """Return a string representation of the configuration."""
        if self.get("redact_sensitive_data"):
            return yaml.dump(self.redact(self._config), default_flow_style=False)
        rendered = self._config.copy()
        if isinstance(rendered.get("audiobookshelf"), dict):
            rendered["audiobookshelf"] = {**rendered["audiobookshelf"], "api_key": "**REDACTED**"}
        return yaml.dump(rendered, default_flow_style=False)
