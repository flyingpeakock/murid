import yaml
import argparse
import logging
import os
from typing import Any

logger = logging.getLogger("HardcoverHarvester")


class Config:
    def __init__(self, config_file: argparse.FileType) -> None:
        self._config = yaml.safe_load(config_file)
        self._defaults = {
            "users": None,
        }
        logger.debug(f"Config loaded: {self._config}")

    def get(self, key: str) -> Any:
        try:
            return self._sanitize(self._config[key])
        except KeyError:
            if key in self._defaults and self._defaults[key] is not None:
                return self._sanitize(self._defaults[key])
            else:
                raise KeyError(f"Config item '{key}' not found in config file")

    def _sanitize(self, value: Any) -> Any:
        if isinstance(value, str):
            if value.strip().startswith("!ENV"):
                env_var = value[5:-1]  # Extract the environment variable name
                env_value = os.getenv(env_var)
                if env_value is None:
                    raise ValueError(f"Environment variable '{env_var}' not found")
                return env_value.strip()
            else:
                return value.strip()
        elif isinstance(value, list):
            return [self._sanitize(item) for item in value]
        elif isinstance(value, dict):
            return {
                self._sanitize(key): self._sanitize(val) for key, val in value.items()
            }
        else:
            return value
