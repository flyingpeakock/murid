import yaml
import argparse
import logging
import os
from typing import Any

logger = logging.getLogger("HardcoverHarvester")


class _Missing:
    def __str__(self) -> str:
        return "<MISSING>"


_MISSING = _Missing()


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
            raise ConfigError(f"Environment variable '{env_var}' not found")
        return value


class Config:
    def __init__(self, config_file: argparse.FileType) -> None:
        self._defaults = {
            "users": _MISSING,
            "redact_sensitive_data": True,
        }
        try:
            config = yaml.load(config_file, Loader=EnvLoader)
        except yaml.YAMLError as e:
            raise ConfigError(f"Error parsing config file: {e}")
        self._config = self._sanitize(
            self._defaults | (config if config is not None else {})
        )
        self.validate()
        logger.debug(f"Config loaded: {self}")

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
            return {
                self._sanitize(key): self._sanitize(val) for key, val in value.items()
            }
        else:
            return value

    def redact(self, data: Any) -> dict:
        if self.get("redact_sensitive_data") is False:
            return data
        sensitive_keys = ["api_key"]
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

        expected_keys = set(self._defaults.keys())
        for key in self._config.keys():
            if key not in expected_keys:
                logger.warning(f"Unexpected config item '{key}' found in config file")

    def __str__(self) -> str:
        return yaml.dump(self.redact(self._config), default_flow_style=False)
