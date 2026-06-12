# test_config.py

import logging
from io import StringIO

import pytest
import yaml

from hardcoverharvester.config import (
    Config,
    ConfigError,
    EnvLoader,
    _defaults,
)

missing = object()
base = _defaults.copy() | {
    "users": [{"id": 1234, "api_key": "secret123"}],
    "calibre_db_path": "metadata.db",
}


@pytest.fixture
def build_config(tmp_path):
    def _make(**overrides):
        data = base.copy()
        for key, value in overrides.items():
            if value is missing:
                data.pop(key, None)
            else:
                data[key] = value

        # Materialize file
        if (
            "calibre_db_path" in data
            and data["calibre_db_path"] is not missing
            and data["calibre_db_path"] != "not-exist.db"
        ):
            db_path = tmp_path / data["calibre_db_path"]
            db_path.write_text("")
            data["calibre_db_path"] = str(db_path)

        return Config(StringIO(yaml.dump(data)))

    return _make


def make_config(yaml_text: str) -> Config:
    return Config(StringIO(yaml_text))


def test_load_valid_config(build_config):
    config = build_config()

    assert config.get("users") == [
        {
            "id": 1234,
            "api_key": "secret123",
        }
    ]
    assert config.get("redact_sensitive_data") is True


def test_default_redact_sensitive_data(build_config):
    config = build_config(redact_sensitive_data=missing)
    assert config.get("redact_sensitive_data") is True


def test_missing_users_raises(build_config):
    with pytest.raises(ConfigError, match="Config item 'users' is missing"):
        build_config(users=missing)


def test_get_existing_key(build_config):
    config = build_config()
    assert config.get("users")[0]["id"] == 1234


def test_get_default_value(build_config):
    config = build_config()
    assert config.get("missing_key", "default") == "default"


def test_get_missing_key_raises(build_config):
    config = build_config()
    with pytest.raises(KeyError, match="Config item 'missing_key' not found"):
        config.get("missing_key")


def test_users_must_be_list(build_config):
    with pytest.raises(ConfigError, match="Config item 'users' must be a list"):
        build_config(users="not-a-list")


def test_user_must_be_dict(build_config):
    with pytest.raises(ConfigError, match="Each user must be a dict"):
        build_config(users=["not-a-dict"])


def test_user_requires_id(build_config):
    with pytest.raises(ConfigError, match="Each user must have an 'id' key"):
        build_config(users=[{"api_key": "secret"}])


def test_user_requires_api_key(build_config):
    with pytest.raises(ConfigError, match="Each user must have an 'api_key' key"):
        build_config(users=[{"id": 123410}])


def test_redact_sensitive_data_must_be_boolean(build_config):
    with pytest.raises(
        ConfigError,
        match="Config item 'redact_sensitive_data' must be a boolean",
    ):
        build_config(redact_sensitive_data="yes")


def test_env_tag_loads_environment_variable(monkeypatch, build_config):
    monkeypatch.setenv("API_KEY", "super-secret")
    config = build_config(users=[{"id": 1234, "api_key": "!ENV API_KEY"}])
    assert config.get("users")[0]["api_key"] == "super-secret"


def test_env_tag_missing_variable_raises(build_config):
    with pytest.raises(
        ConfigError,
        match="Environment variable 'DOES_NOT_EXIST' not found",
    ):
        build_config(users=[{"id": 1234, "api_key": "!ENV DOES_NOT_EXIST"}])


def test_sanitize_inline_env_string(monkeypatch, build_config):
    monkeypatch.setenv("TOKEN", "abc123")
    config = build_config()
    assert config._sanitize("!ENV TOKEN") == "abc123"


def test_sanitize_inline_env_string_missing(monkeypatch, build_config):
    monkeypatch.delenv("TOKEN", raising=False)
    config = build_config()
    with pytest.raises(
        ConfigError,
        match="Environment variable 'TOKEN' not found",
    ):
        config._sanitize("!ENV TOKEN")


def test_sanitize_trims_strings(build_config):
    config = build_config()
    assert config._sanitize("  hello  ") == "hello"


def test_redact_dictionary(build_config):
    config = build_config()
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


def test_redact_list(build_config):
    config = build_config()

    data = [
        {"api_key": "secret"},
        {"value": 1},
    ]

    redacted = config.redact(data)

    assert redacted == [
        {"api_key": "**REDACTED**"},
        {"value": 1},
    ]


def test_redaction_can_be_disabled(build_config):
    config = build_config(redact_sensitive_data=False)
    data = {"api_key": "secret"}
    assert config.redact(data) == data


def test_str_redacts_api_keys(build_config):
    config = build_config()
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


def test_unexpected_key_logs_warning(caplog, build_config):
    with caplog.at_level(logging.WARNING):
        build_config(extra_key="value")

    assert "Unexpected config item 'extra_key'" in caplog.text


def test_env_loader_directly(monkeypatch):
    monkeypatch.setenv("TEST_VAR", "value")

    data = yaml.load("key: !ENV TEST_VAR", Loader=EnvLoader)

    assert data["key"] == "value"


def test_user_id_must_be_int(build_config):
    with pytest.raises(ConfigError, match="User 'id' must be an integer"):
        build_config(users=[{"id": "not-an-int", "api_key": "secret"}])


def test_calibre_db_path_must_exist(build_config):
    with pytest.raises(ConfigError, match="Config item 'calibre_db_path' is missing"):
        build_config(calibre_db_path=missing)


def test_calibre_db_path_must_exist_on_filesystem(build_config):
    with pytest.raises(ConfigError, match="Calibre database file not found"):
        build_config(calibre_db_path="not-exist.db")


def test_calibredb_executable_path_defaults_to_calibredb(build_config):
    config = build_config()
    assert config.get("calibredb_executable") == "calibredb"


def test_calibredb_executable_path_can_be_overridden(build_config):
    config = build_config(calibredb_executable="/custom/path/calibredb")
    assert config.get("calibredb_executable") == "/custom/path/calibredb"


def test_matcher_threshold_defaults_to_0_92(build_config):
    config = build_config()
    assert config.get("matcher_threshold") == 0.92


def test_matcher_threshold_must_be_float(build_config):
    with pytest.raises(ConfigError, match="Config item 'matcher_threshold' must be a float"):
        build_config(matcher_threshold="not-a-float")

    with pytest.raises(ConfigError, match="Config item 'matcher_threshold' must be a float"):
        build_config(matcher_threshold=1)


def test_matcher_threshold_can_be_set(build_config):
    config = build_config(matcher_threshold=0.85)
    assert config.get("matcher_threshold") == 0.85
