# test_config.py

from io import StringIO
import logging

import pytest
import yaml

from hardcoverharvester.config import (
    Config,
    ConfigError,
    EnvLoader,
)


def make_config(yaml_text: str) -> Config:
    return Config(StringIO(yaml_text))


VALID_CONFIG = """
users:
  - id: 1234
    api_key: secret123
"""


def test_load_valid_config():
    config = make_config(VALID_CONFIG)

    assert config.get("users") == [
        {
            "id": 1234,
            "api_key": "secret123",
        }
    ]
    assert config.get("redact_sensitive_data") is True


def test_default_redact_sensitive_data():
    config = make_config(VALID_CONFIG)

    assert config.get("redact_sensitive_data") is True


def test_missing_users_raises():
    with pytest.raises(ConfigError, match="Config item 'users' is missing"):
        make_config("{}")


def test_get_existing_key():
    config = make_config(VALID_CONFIG)

    assert config.get("users")[0]["id"] == 1234


def test_get_default_value():
    config = make_config(VALID_CONFIG)

    assert config.get("missing_key", "default") == "default"


def test_get_missing_key_raises():
    config = make_config(VALID_CONFIG)

    with pytest.raises(KeyError, match="Config item 'missing_key' not found"):
        config.get("missing_key")


def test_users_must_be_list():
    yaml_text = """
users: not-a-list
"""

    with pytest.raises(ConfigError, match="Config item 'users' must be a list"):
        make_config(yaml_text)


def test_user_must_be_dict():
    yaml_text = """
users:
  - not-a-dict
"""

    with pytest.raises(ConfigError, match="Each user must be a dict"):
        make_config(yaml_text)


def test_user_requires_id():
    yaml_text = """
users:
  - api_key: secret
"""

    with pytest.raises(ConfigError, match="Each user must have an 'id' key"):
        make_config(yaml_text)


def test_user_requires_api_key():
    yaml_text = """
users:
  - id: 123410
"""

    with pytest.raises(ConfigError, match="Each user must have an 'api_key' key"):
        make_config(yaml_text)


def test_redact_sensitive_data_must_be_boolean():
    yaml_text = """
users:
  - id: 1234
    api_key: secret
redact_sensitive_data: "yes"
"""

    with pytest.raises(
        ConfigError,
        match="Config item 'redact_sensitive_data' must be a boolean",
    ):
        make_config(yaml_text)


def test_env_tag_loads_environment_variable(monkeypatch):
    monkeypatch.setenv("API_KEY", "super-secret")

    yaml_text = """
users:
  - id: 1234
    api_key: !ENV API_KEY
"""

    config = make_config(yaml_text)

    assert config.get("users")[0]["api_key"] == "super-secret"


def test_env_tag_missing_variable_raises():
    yaml_text = """
users:
  - id: 1234
    api_key: !ENV DOES_NOT_EXIST
"""

    with pytest.raises(
        ConfigError,
        match="Environment variable 'DOES_NOT_EXIST' not found",
    ):
        make_config(yaml_text)


def test_sanitize_inline_env_string(monkeypatch):
    monkeypatch.setenv("TOKEN", "abc123")

    config = make_config(VALID_CONFIG)

    assert config._sanitize("!ENV TOKEN") == "abc123"


def test_sanitize_inline_env_string_missing(monkeypatch):
    monkeypatch.delenv("TOKEN", raising=False)

    config = make_config(VALID_CONFIG)

    with pytest.raises(
        ConfigError,
        match="Environment variable 'TOKEN' not found",
    ):
        config._sanitize("!ENV TOKEN")


def test_sanitize_trims_strings():
    config = make_config(VALID_CONFIG)

    assert config._sanitize("  hello  ") == "hello"


def test_redact_dictionary():
    config = make_config(VALID_CONFIG)

    data = {
        "api_key": "secret",
        "nested": {
            "api_key": "another-secret",
            "value": 123,
        },
    }

    redacted = config.redact(data)

    assert redacted == {
        "api_key": "**REDACTED**",
        "nested": {
            "api_key": "**REDACTED**",
            "value": 123,
        },
    }


def test_redact_list():
    config = make_config(VALID_CONFIG)

    data = [
        {"api_key": "secret"},
        {"value": 1},
    ]

    redacted = config.redact(data)

    assert redacted == [
        {"api_key": "**REDACTED**"},
        {"value": 1},
    ]


def test_redaction_can_be_disabled():
    yaml_text = """
users:
  - id: 123
    api_key: secret
redact_sensitive_data: false
"""

    config = make_config(yaml_text)

    data = {"api_key": "secret"}

    assert config.redact(data) == data


def test_str_redacts_api_keys():
    config = make_config(VALID_CONFIG)

    output = str(config)

    assert "**REDACTED**" in output
    assert "secret123" not in output


def test_invalid_yaml_raises_config_error():
    yaml_text = """
users:
  - id: 1234
    api_key: secret
    [
"""

    with pytest.raises(ConfigError, match="Error parsing config file"):
        make_config(yaml_text)


def test_unexpected_key_logs_warning(caplog):
    yaml_text = """
users:
  - id: 1234
    api_key: secret
extra_key: value
"""

    with caplog.at_level(logging.WARNING):
        make_config(yaml_text)

    assert "Unexpected config item 'extra_key'" in caplog.text


def test_env_loader_directly(monkeypatch):
    monkeypatch.setenv("TEST_VAR", "value")

    data = yaml.load("key: !ENV TEST_VAR", Loader=EnvLoader)

    assert data["key"] == "value"

def test_user_id_must_be_int():
    yaml_text = """
users:
    - id: "not-an-int"
      api_key: secret
"""
    with pytest.raises(ConfigError, match="User 'id' must be an integer"):
        make_config(yaml_text)
