import logging
import os
from io import StringIO
from typing import Any

import yaml

logger = logging.getLogger("HardcoverHarvester")


class _Missing:
    def __str__(self) -> str:
        return "<MISSING>"


_MISSING = _Missing()


_defaults = {
    "users": _MISSING,
    "redact_sensitive_data": True,
    "calibre_db_path": _MISSING,
    "calibredb_executable": "calibredb",
    "matcher_threshold": 0.85,
    "mam_id": _MISSING,
    "lang_codes": ["ENG"],
    "qbittorrent": {
        "host": _MISSING,
        "username": _MISSING,
        "password": _MISSING,
        "port": _MISSING,
        "verify_cert": True,
        "category": "hardcoverharvester",
    },
}


class ConfigError(Exception):
    pass


class EnvLoader(yaml.SafeLoader):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.add_constructor("!ENV", self._env_constructor)

    def _env_constructor(self, loader: yaml.SafeLoader, node: yaml.Node) -> str:
        env_var = loader.construct_scalar(node)
        value = os.getenv(env_var)
        if value is None:
            raise ConfigError(f"Environment variable '{env_var}' not found") from None
        return value


class Config:
    def __init__(self, config_file: StringIO) -> None:
        try:
            config = yaml.load(config_file, Loader=EnvLoader)
        except yaml.YAMLError as e:
            raise ConfigError(f"Error parsing config file: {e}") from e
        self._config = self._sanitize(deep_merge(_defaults, config if config is not None else {}))

        for key in _defaults:
            if config is None or key not in config:
                logger.info(
                    f"Using default value for config item '{key}. Value: {self._config[key]}'"
                )

        self.validate()
        logger.debug(f"Config loaded:\n{self}")

    def get(self, key: str, default: Any = _MISSING) -> Any:
        if key in self._config:
            return self._config[key]
        if default is not _MISSING:
            return default
        raise KeyError(f"Config item '{key}' not found in config file")

    def _sanitize(self, value: Any) -> Any:
        if isinstance(value, str):
            value = value.strip()
            if value.startswith("!ENV"):
                env_var = value.removeprefix("!ENV").strip()
                env_value = os.getenv(env_var)
                if env_value is None:
                    raise ConfigError(f"Environment variable '{env_var}' not found")
                return env_value.strip()
            else:
                return value
        elif isinstance(value, list):
            return [self._sanitize(item) for item in value]
        elif isinstance(value, dict):
            return {self._sanitize(key): self._sanitize(val) for key, val in value.items()}
        else:
            return value

    def redact(self, data: Any) -> dict:
        if self.get("redact_sensitive_data") is False:
            return data
        sensitive_keys = ["api_key", "mam_id"]
        if isinstance(data, dict):
            return {
                key: ("**REDACTED**" if key in sensitive_keys else self.redact(value))
                for key, value in data.items()
            }
        elif isinstance(data, list):
            return [self.redact(item) for item in data]
        else:
            return data

    def validate(self) -> None:
        for key, value in self._config.items():
            if value is _MISSING:
                raise ConfigError(f"Config item '{key}' is missing")

        users = self.get("users")
        if not isinstance(users, list):
            raise ConfigError("Config item 'users' must be a list")
        for user in users:
            if not isinstance(user, dict):
                raise ConfigError("Each user must be a dict")
            if "id" not in user:
                raise ConfigError("Each user must have an 'id' key")
            if "api_key" not in user:
                raise ConfigError("Each user must have an 'api_key' key")
            if not isinstance(user["id"], int):
                raise ConfigError("User 'id' must be an integer")

        if not isinstance(self.get("redact_sensitive_data"), bool):
            raise ConfigError("Config item 'redact_sensitive_data' must be a boolean")

        if not os.path.isfile(self.get("calibre_db_path")):
            raise ConfigError("Calibre database file not found")

        if not isinstance(self.get("matcher_threshold"), float):
            raise ConfigError("Config item 'matcher_threshold' must be a float")

        if not isinstance(self.get("lang_codes"), list):
            raise ConfigError("Config item 'lang_codes' must be a list")

        for lang in self.get("lang_codes"):
            if not isinstance(lang, str):
                raise ConfigError("Config item 'lang_codes' must be a list of strings")

        if len(self.get("lang_codes")) == 0:
            raise ConfigError("Config item 'lang_codes' must be a non-empty list")

        if not isinstance(self.get("qbittorrent"), dict):
            raise ConfigError("Config item 'qbittorrent' must be a dict")

        qbit = self.get("qbittorrent")
        required_qbit_keys = ["host", "username", "password", "port"]

        for key in required_qbit_keys:
            if key not in qbit:
                raise ConfigError(f"Config item 'qbittorrent' must have a '{key}' key")
            if not isinstance(qbit[key], str) and key != "port":
                raise ConfigError(f"Config item 'qbittorrent.{key}' must be a string")
            if key == "port" and not isinstance(qbit[key], int):
                raise ConfigError("Config item 'qbittorrent.port' must be an integer")

        if qbit["host"].endswith("/"):
            qbit["host"] = qbit["host"].rstrip("/")
        if not qbit["host"].startswith("http://") and not qbit["host"].startswith("https://"):
            raise ConfigError(
                "Config item 'qbittorrent.host' must start with 'http://' or 'https://'"
            )

        if not isinstance(qbit["verify_cert"], bool):
            raise ConfigError("Config item 'qbittorrent.verify_cert' must be a boolean")

        if not isinstance(qbit["category"], str):
            raise ConfigError("Config item 'qbittorrent.category' must be a string")

        expected_keys = set(_defaults.keys())
        for key in self._config.keys():
            if key not in expected_keys:
                logger.warning(f"Unexpected config item '{key}' found in config file")

    def __str__(self) -> str:
        return yaml.dump(self.redact(self._config), default_flow_style=False)


def deep_merge(default, override):
    if isinstance(default, dict) and isinstance(override, dict):
        out = dict(default)
        for k, v in override.items():
            out[k] = deep_merge(default.get(k), v)
        return out
    return override if override is not None else default
