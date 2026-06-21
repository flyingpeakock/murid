"""Module for loading and validating the configuration for the Murid application."""

import logging
import os
from io import StringIO
from typing import Any

import yaml
from croniter import croniter

logger = logging.getLogger("murid")


class _Missing:  # pylint: disable=too-few-public-methods
    """Sentinel class for missing config values."""

    def __repr__(self) -> str:
        """Return a string representation of the missing value."""
        return "<MISSING>"


_MISSING = _Missing()


_defaults = {
    "hardcover_api_keys": _MISSING,
    "redact_sensitive_data": True,
    "calibre_db_path": _MISSING,
    "calibredb_executable": "calibredb",
    "matcher_threshold": 0.7,
    "mam_id": _MISSING,
    "lang_codes": ["ENG"],
    "qbittorrent": {
        "host": _MISSING,
        "username": _MISSING,
        "password": _MISSING,
        "port": _MISSING,
        "verify_cert": True,
        "category": "murid",
        "mapping": {
            "qbit_path": None,
            "murid_path": None,
        },
    },
    "schedule": "0 * * * *",
    "apprise": None,
    "filetypes": [
        "epub",
        "mobi",
        "azw3",
        "azw",
    ],
    "blacklisted_torrent_ids": [],
}


class ConfigError(Exception):
    """Custom exception for configuration-related errors."""


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
        self._config = self._sanitize(deep_merge(_defaults, config if config is not None else {}))

        for key in _defaults:
            if config is None or key not in config:
                logger.debug(
                    "Using default value for config item '%s. Value: %s'",
                    key,
                    self._config[key],
                )

        self.validate()
        logger.debug("Config loaded:\n%s", self)

    def get(self, key: str, default: Any = _MISSING) -> Any:
        """Get a config value by key, with an optional default if the key is not found."""
        if key in self._config:
            return self._config[key]
        if default is not _MISSING:
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
        """Validate the loaded configuration.

        Ensure all required fields are present and correctly formatted."""
        self._ensure_not_missing(self._config)
        self._ensure_hardcover_api_keys(self.get("hardcover_api_keys"))
        self._ensure_type(self.get("redact_sensitive_data"), bool, "redact_sensitive_data")
        self._ensure_type(self.get("calibre_db_path"), str, "calibre_db_path")
        self._ensure_path_exists(self.get("calibre_db_path"))
        self._ensure_type(self.get("calibredb_executable"), str, "calibredb_executable")
        self._ensure_type(self.get("matcher_threshold"), float, "matcher_threshold")
        self._ensure_lang_codes(self.get("lang_codes"))
        self._ensure_qbittorrent(self.get("qbittorrent"))
        self._ensure_cron(self.get("schedule"))
        self._ensure_filetypes(self.get("filetypes"))
        self._ensure_blacklisted_torrent_ids(self.get("blacklisted_torrent_ids"))

        self._check_extra_keys(self._config)

    @staticmethod
    def _ensure_not_missing(data: Any) -> None:
        """Recursively check for missing config values in the provided data structure."""
        if isinstance(data, dict):
            for key, value in data.items():
                if value is _MISSING:
                    raise ConfigError(f"Config item '{key}' is missing")
                Config._ensure_not_missing(value)
        elif isinstance(data, list):
            for item in data:
                Config._ensure_not_missing(item)

    @staticmethod
    def _ensure_hardcover_api_keys(keys: list) -> None:
        """Ensure that the users config item is valid."""
        Config._ensure_type(keys, list, "hardcover_api_keys")
        for key in keys:
            if not key:
                raise ConfigError("Config item 'hardcover_api_keys' must not contain empty strings")
            Config._ensure_type(key, str, "hardcover_api_keys item")
            if not key.startswith("Bearer "):
                raise ConfigError("Config item 'hardcover_api_keys item' must start with 'Bearer '")

    @staticmethod
    def _ensure_type(data: Any, expected_type: type, position: str) -> None:
        """Ensure that the provided data is of the expected type."""
        if not isinstance(data, expected_type):
            raise ConfigError(
                f"Config item '{position}' must be an {expected_type.__name__}"
                if expected_type.__name__[0].lower() in "aeiou"
                else f"Config item '{position}' must be a {expected_type.__name__}"
            )

    @staticmethod
    def _ensure_path_exists(path: str) -> None:
        if not os.path.exists(path):
            raise ConfigError(f"Path '{path}' does not exist")

    @staticmethod
    def _ensure_lang_codes(lang_codes: list) -> None:
        """Ensure that the lang_codes config item is valid."""
        Config._ensure_type(lang_codes, list, "lang_codes")
        for lang in lang_codes:
            Config._ensure_type(lang, str, "lang_codes item")
        if len(lang_codes) == 0:
            raise ConfigError("Config item 'lang_codes' must be a non-empty list")

    @staticmethod
    def _ensure_qbittorrent(qbittorrent: dict) -> None:
        """Ensure that the qbittorrent config item is valid."""
        Config._ensure_type(qbittorrent, dict, "qbittorrent")
        required_keys = ["host", "username", "password", "port"]
        for key in required_keys:
            if key == "port":
                Config._ensure_type(qbittorrent[key], int, f"qbittorrent.{key}")
            else:
                Config._ensure_type(qbittorrent[key], str, f"qbittorrent.{key}")
        Config._ensure_type(qbittorrent.get("verify_cert", True), bool, "qbittorrent.verify_cert")
        Config._ensure_type(qbittorrent.get("category", "murid"), str, "qbittorrent.category")
        Config._ensure_type(qbittorrent.get("mapping", {}), dict, "qbittorrent.mapping")
        qbittorrent["host"] = qbittorrent["host"].rstrip("/")
        mapping = qbittorrent.get("mapping", {})
        if "qbit_path" not in mapping:
            raise ConfigError("Config item 'qbittorrent.mapping' must have a 'qbit_path' key")
        if "murid_path" not in mapping:
            raise ConfigError("Config item 'qbittorrent.mapping' must have a 'murid_path' key")
        if mapping["murid_path"] and not os.path.exists(mapping["murid_path"]):
            raise ConfigError(f"murid path '{mapping['murid_path']}' does not exist")
        if mapping["murid_path"] and not mapping["qbit_path"]:
            raise ConfigError(
                "Config item 'qbittorrent.mapping.qbit_path' must be set if 'murid_path' is set"
            )
        if mapping["qbit_path"] and not mapping["murid_path"]:
            raise ConfigError(
                "Config item 'qbittorrent.mapping.murid_path' must be set if 'qbit_path' is set"
            )

    @staticmethod
    def _check_extra_keys(config: dict) -> None:
        """Check for unexpected config items in the provided config dictionary."""
        expected_keys = set(_defaults.keys())
        for key in config.keys():
            if key not in expected_keys:
                logger.warning("Unexpected config item '%s' found in config file", key)

    @staticmethod
    def _ensure_cron(expr: str) -> None:
        """Ensure that the provided string is a valid cron expression."""
        try:
            croniter(expr)
        except (ValueError, KeyError):
            raise ConfigError("Config item 'schedule' must be a valid cron expression") from None

    @staticmethod
    def _ensure_filetypes(filetypes: list) -> None:
        """Ensure that the filetypes config item is valid."""
        Config._ensure_type(filetypes, list, "filetypes")
        for filetype in filetypes:
            Config._ensure_type(filetype, str, "filetypes item")
            if not filetype:
                raise ConfigError("Config item 'filetypes' must not contain empty strings")

    @staticmethod
    def _ensure_blacklisted_torrent_ids(ids: list[str]) -> None:
        """Ensure that the blacklisted_torrent_ids config item is valid."""
        Config._ensure_type(ids, list, "blacklisted_torrent_ids")
        for torrent_id in ids:
            Config._ensure_type(torrent_id, int, "blacklisted_torrent_ids item")

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
        return yaml.dump(self._config, default_flow_style=False)


def deep_merge(default, override):
    """Recursively merge two dictionaries

    Values from the override take precedence over the default.
    """
    if isinstance(default, dict) and isinstance(override, dict):
        out = dict(default)
        for k, v in override.items():
            out[k] = deep_merge(default.get(k), v)
        return out
    return override if override is not None else default
