# test_config.py

import logging
from io import StringIO
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import yaml

from murid.config import Config, ConfigError, _defaults, env_constructor
from murid.services.service_factory import ServiceFactory

missing = object()
base = _defaults.copy() | {
    "hardcover_api_keys": ["Bearer secret123"],
    "calibre": {
        "library": "metadata.db",
    },
    "mam_id": "abc123",
    "qbittorrent": {
        "host": "http://localhost",
        "username": "admin",
        "password": "adminadmin",
        "port": 8080,
        "verify_cert": False,
        "category": "murid",
    },
}


def audiobook_settings(**overrides):
    return {
        "url": "https://audio.example.com/abs/",
        "api_key": "audio-secret",
        "library_id": "library-id",
        "library_path": "/mnt/audiobooks",
        **overrides,
    }


def test_grouped_reading_lists_and_defaults(build_config):
    entries = [{"api_key": "Bearer key", "reading_list": {
        "want-to-read": {}, "audio": {"type": "audiobook"},
        "both": {"type": ["ebook", "audiobook"]},
    }}]
    config = build_config(hardcover_api_keys=entries, audiobookshelf=audiobook_settings())
    assert config.hardcover_lists == [
        {"api_key": "Bearer key", "list": "audio", "media_types": ["audiobook"]},
        {"api_key": "Bearer key", "list": "both", "media_types": ["ebook", "audiobook"]},
        {"api_key": "Bearer key", "list": "want-to-read", "media_types": ["ebook"]},
    ]


def test_omitting_reading_list_defaults_to_want_to_read_ebooks(build_config):
    config = build_config(hardcover_api_keys=[{"api_key": "Bearer key"}])
    assert config.hardcover_lists == [
        {"api_key": "Bearer key", "list": "want-to-read", "media_types": ["ebook"]},
    ]


def test_normalized_lists_preserve_raw_config_and_are_reused_by_factory(build_config, monkeypatch):
    entries = ["Bearer legacy", {"api_key": "Bearer custom", "list": "selected"}]
    config = build_config(hardcover_api_keys=entries)
    assert config.hardcover_api_keys == entries
    assert yaml.safe_load(str(config))["hardcover_api_keys"] == "**REDACTED**"
    normalize = Mock(side_effect=AssertionError("Loaded config must not be normalized again"))
    monkeypatch.setattr("murid.services.service_factory.hardcover_list_settings", normalize)
    factory = ServiceFactory(SimpleNamespace(), config, initialize_notifier=False)
    assert factory.hardcover_lists is config.hardcover_lists
    normalize.assert_not_called()


@pytest.mark.parametrize("lists", [
    {}, None, [], {"want to read": {}}, {"": {}}, {5: {}},
    {"audio": None}, {"audio": {"format": "mp3"}},
    {"audio": {"type": "audiobooks"}}, {"audio": {"type": []}},
    {"audio": {"type": True}}, {"audio": {"type": ["video"]}},
])
def test_invalid_grouped_reading_lists(build_config, lists):
    with pytest.raises(ConfigError, match="reading_list"):
        build_config(hardcover_api_keys=[{"api_key": "Bearer key", "reading_list": lists}])


@pytest.mark.parametrize("legacy", [{"list": "a"}, {"media_types": ["ebook"]}])
def test_grouped_lists_reject_ambiguous_legacy_settings(build_config, legacy):
    with pytest.raises(ConfigError, match="cannot be combined"):
        build_config(hardcover_api_keys=[{
            "api_key": "Bearer key", "reading_list": {"a": {}}, **legacy,
        }])


def test_grouped_audio_only_needs_no_calibre(build_config):
    config = build_config(calibre=missing, audiobookshelf=audiobook_settings(),
                          hardcover_api_keys=[{"api_key": "Bearer key", "reading_list": {
                              "audio": {"type": "audiobook"},
                          }}])
    assert config.audiobookshelf["library_id"] == "library-id"


@pytest.mark.parametrize("media_types", [[], "audiobook", ["video"], [None], [True]])
def test_reject_invalid_media_types(build_config, media_types):
    with pytest.raises(ConfigError, match="media_types"):
        build_config(hardcover_api_keys=[{"api_key": "Bearer key", "media_types": media_types}])


def test_audio_only_config_needs_no_calibre(build_config):
    config = build_config(
        calibre=missing,
        hardcover_api_keys=[{"api_key": "Bearer key", "media_types": ["audiobook"]}],
        audiobookshelf=audiobook_settings(),
    )
    assert config.audiobookshelf["filetypes"] == ["m4b", "mp3"]
    assert config.audiobookshelf["url"] == "https://audio.example.com/abs"


def test_audiobook_requests_require_backend(build_config):
    with pytest.raises(ConfigError, match="require 'audiobookshelf'"):
        build_config(hardcover_api_keys=[{"api_key": "Bearer key", "media_types": ["audiobook"]}])


def test_both_media_require_both_libraries(build_config):
    with pytest.raises(ConfigError, match="calibre.library"):
        build_config(
            calibre=missing,
            hardcover_api_keys=[{"api_key": "Bearer key", "media_types": ["ebook", "audiobook"]}],
            audiobookshelf=audiobook_settings(),
        )


@pytest.mark.parametrize("redact", [True, False])
def test_audiobookshelf_secret_always_redacted(build_config, redact):
    config = build_config(audiobookshelf=audiobook_settings(), redact_sensitive_data=redact)
    assert "audio-secret" not in str(config)
    assert config.audiobookshelf["api_key"] == "audio-secret"


@pytest.mark.parametrize("key,value", [
    ("url", "ftp://example.com"), ("url", "https://user:secret@example.com"),
    ("url", "https://example.com?token=secret"), ("api_key", ""),
    ("url", "https://[broken"), ("url", "https://example.com:invalid"),
    ("library_id", ""), ("library_path", "relative/path"),
    ("filetypes", []), ("filetypes", ["epub"]), ("filetypes", "mp3"),
])
def test_invalid_audiobookshelf_settings(build_config, key, value):
    with pytest.raises(ConfigError, match="audiobookshelf"):
        build_config(audiobookshelf=audiobook_settings(**{key: value}))


@pytest.mark.parametrize("key", ["url", "api_key", "library_id", "library_path"])
def test_audiobookshelf_required_fields(build_config, key):
    settings = audiobook_settings()
    settings.pop(key)
    with pytest.raises(ConfigError, match=f"audiobookshelf.{key}"):
        build_config(audiobookshelf=settings)


@pytest.fixture
def build_config(tmp_path):
    def _make(**overrides):
        data = base.copy()
        for key, value in overrides.items():
            if value is missing:
                data.pop(key, None)
            else:
                data[key] = value

        calibre = data.get("calibre")
        if calibre and isinstance(calibre.get("library"), str):
            library = calibre["library"]
            if (
                library
                and not library.startswith(("http://", "https://"))
                and library != "not-exist.db"
            ):
                library_path = tmp_path / library
                library_path.write_text("")
                calibre["library"] = str(library_path)

        return Config(StringIO(yaml.dump(data)))

    return _make


def make_config(yaml_text: str) -> Config:
    return Config(StringIO(yaml_text))


def test_load_valid_config(build_config):
    config = build_config()

    assert config.get("hardcover_api_keys") == ["Bearer secret123"]
    assert config.get("redact_sensitive_data") is True


def test_default_redact_sensitive_data(build_config):
    config = build_config(redact_sensitive_data=missing)
    assert config.get("redact_sensitive_data") is True


def test_get_existing_key(build_config):
    config = build_config()
    assert config.get("hardcover_api_keys")[0] == "Bearer secret123"


def test_get_default_value(build_config):
    config = build_config()
    assert config.get("missing_key", "default") == "default"


def test_get_missing_key_raises(build_config):
    config = build_config()
    with pytest.raises(KeyError, match="Config item 'missing_key' not found"):
        config.get("missing_key")


def test_redact_sensitive_data_must_be_boolean(build_config):
    with pytest.raises(
        ConfigError,
        match="Config item 'redact_sensitive_data' must be a bool",
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
        "mam_id": "mam-secret",
        "nested": {
            "api_key": "another-secret",
            "value": 123,
        },
    }
    redacted = config.redact(data)
    assert redacted == {
        "api_key": "**REDACTED**",
        "mam_id": "**REDACTED**",
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


def test_str_redacts_api_keys(build_config):
    config = build_config()
    output = str(config)
    print(output)
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

    yaml.SafeLoader.add_constructor("!ENV", env_constructor)
    data = yaml.load("key: !ENV TEST_VAR", Loader=yaml.SafeLoader)

    assert data["key"] == "value"


def test_calibredb_executable_path_defaults_to_calibredb(build_config):
    config = build_config()
    assert config.get("calibre").get("calibredb_executable") == "calibredb"


def test_calibredb_executable_path_can_be_overridden(build_config):
    config = build_config(
        calibre={"calibredb_executable": "/custom/path/calibredb", "library": "fake-path"}
    )
    assert config.get("calibre")["calibredb_executable"] == "/custom/path/calibredb"


def test_calibre_library_accepts_server_url(build_config):
    config = build_config(calibre={"library": "http://localhost:8080/#books"})
    assert config.get("calibre")["library"] == "http://localhost:8080/#books"


@pytest.mark.parametrize("library", ["not-exist.db", "", None, 123])
def test_calibre_library_rejects_invalid_path_or_value(build_config, library):
    with pytest.raises(ConfigError, match="calibre.library|Calibre database path"):
        build_config(calibre={"library": library})


@pytest.mark.parametrize("old_key", ["library_path", "server_url"])
def test_calibre_rejects_old_library_options(build_config, old_key):
    with pytest.raises(ConfigError, match="calibre.library"):
        build_config(calibre={"library": "metadata.db", old_key: "old value"})


def test_matcher_threshold_defaults_to_0_92(build_config):
    config = build_config()
    assert config.get("matcher_threshold") == 0.92


def test_matcher_threshold_must_be_float(build_config):
    with pytest.raises(ConfigError, match="Config item 'matcher_threshold' must be a float"):
        build_config(matcher_threshold="not-a-float")

    with pytest.raises(ConfigError, match="Config item 'matcher_threshold' must be a float"):
        build_config(matcher_threshold=1)


def test_matcher_threshold_can_be_set(build_config):
    config = build_config(matcher_threshold=0.92)
    assert config.get("matcher_threshold") == 0.92


def test_mam_id_must_exist(build_config):
    with pytest.raises(ConfigError, match="Config item 'mam_id' is missing"):
        build_config(mam_id=missing)


def test_mam_id_can_be_set(build_config):
    config = build_config(mam_id="new_mam_id")
    assert config.get("mam_id") == "new_mam_id"


def test_lang_codes_defaults_to_ENG(build_config):
    config = build_config()
    assert config.get("lang_codes") == ["ENG"]


def test_lang_codes_can_be_overridden(build_config):
    config = build_config(lang_codes=["SWE"])
    assert config.get("lang_codes") == ["SWE"]


def test_lang_codes_must_be_list(build_config):
    with pytest.raises(ConfigError, match="Config item 'lang_codes' must be a list"):
        build_config(lang_codes="not-a-list")


def test_lang_codes_list_items_must_be_strings(build_config):
    with pytest.raises(ConfigError, match="Config item 'lang_codes item' must be a str"):
        build_config(lang_codes=[123, "SWE"])


def test_lang_codes_cannot_be_empty(build_config):
    with pytest.raises(ConfigError, match="Config item 'lang_codes' must be a non-empty list"):
        build_config(lang_codes=[])


def test_qbittorrent_config_must_be_dict(build_config):
    with pytest.raises(ConfigError, match="Config item 'qbittorrent' must be a dict"):
        build_config(qbittorrent="not-a-dict")


def test_qbittorrent_config_requires_host(build_config):
    with pytest.raises(ConfigError, match="Config item 'host' is missing"):
        build_config(qbittorrent={"username": "admin", "password": "adminadmin", "port": 8080})


def test_qbittorrent_config_requires_username(build_config):
    with pytest.raises(ConfigError, match="Config item 'username' is missing"):
        build_config(
            qbittorrent={"host": "http://localhost", "password": "adminadmin", "port": 8080}
        )


def test_qbittorrent_config_requires_password(build_config):
    with pytest.raises(ConfigError, match="Config item 'password' is missing"):
        build_config(qbittorrent={"host": "http://localhost", "username": "admin", "port": 8080})


def test_qbittorrent_config_requires_port(build_config):
    with pytest.raises(ConfigError, match="Config item 'port' is missing"):
        build_config(
            qbittorrent={"host": "http://localhost", "username": "admin", "password": "adminadmin"}
        )


def test_qbittorrent_host_trims_trailing_slash(build_config):
    config = build_config(
        qbittorrent={
            "host": "http://localhost/",
            "username": "admin",
            "password": "adminadmin",
            "port": 8080,
            "verify_cert": False,
            "category": "murid",
        }
    )
    assert config.get("qbittorrent")["host"] == "http://localhost"


def test_qbittorrent_verify_cert_must_be_boolean(build_config):
    with pytest.raises(ConfigError, match="Config item 'qbittorrent.verify_cert' must be a bool"):
        build_config(
            qbittorrent={
                "host": "http://localhost",
                "username": "admin",
                "password": "adminadmin",
                "port": 8080,
                "verify_cert": "yes",
            }
        )


def test_qbittorrent_category_must_be_string(build_config):
    with pytest.raises(ConfigError, match="Config item 'qbittorrent.category' must be a str"):
        build_config(
            qbittorrent={
                "host": "http://localhost",
                "username": "admin",
                "password": "adminadmin",
                "port": 8080,
                "verify_cert": False,
                "category": 123,
            }
        )


def test_qbittorrent_category_can_be_set(build_config):
    config = build_config(
        qbittorrent={
            "host": "http://localhost",
            "username": "admin",
            "password": "adminadmin",
            "port": 8080,
            "verify_cert": False,
            "category": "books",
        }
    )
    assert config.get("qbittorrent")["category"] == "books"


def test_qbittorrent_verify_cert_can_be_set(build_config):
    config = build_config(
        qbittorrent={
            "host": "http://localhost",
            "username": "admin",
            "password": "adminadmin",
            "port": 8080,
            "category": "murid",
            "verify_cert": False,
        }
    )
    assert config.get("qbittorrent")["verify_cert"] is False


def test_schedule_defaults_to_once_an_hour(build_config):
    config = build_config()
    assert config.get("schedule") == "0 * * * *"


def test_schedule_must_be_valid_cron(build_config):
    with pytest.raises(ConfigError, match="Config item 'schedule' must be a valid cron expression"):
        build_config(schedule="not-a-cron")

    with pytest.raises(ConfigError, match="Config item 'schedule' must be a valid cron expression"):
        build_config(schedule="* * *")


def test_schedule_can_be_set(build_config):
    config = build_config(schedule="*/15 * * * *")
    assert config.get("schedule") == "*/15 * * * *"


def test_filetypes_defaults_to_epub_mobi_azw3_azw(build_config):
    config = build_config()
    assert config.get("filetypes") == ["epub", "mobi", "azw3", "azw"]


def test_filetypes_must_be_list(build_config):
    with pytest.raises(ConfigError, match="Config item 'filetypes' must be a list"):
        build_config(filetypes="not-a-list")


def test_filetypes_list_items_must_be_strings(build_config):
    with pytest.raises(ConfigError, match="Config item 'filetypes item' must be a str"):
        build_config(filetypes=[123, "epub"])


def test_filetypes_can_be_overridden(build_config):
    config = build_config(filetypes=["pdf", "epub"])
    assert config.get("filetypes") == ["pdf", "epub"]


def test_hardcover_api_keys_must_be_present(build_config):
    with pytest.raises(ConfigError, match="Config item 'hardcover_api_keys' is missing"):
        build_config(hardcover_api_keys=missing)


def test_hardcover_api_keys_must_be_list(build_config):
    with pytest.raises(ConfigError, match="Config item 'hardcover_api_keys' must be a list"):
        build_config(hardcover_api_keys="not-a-list")


def test_hardcover_api_keys_must_not_be_empty(build_config):
    with pytest.raises(
        ConfigError,
        match="Config item 'hardcover_api_keys' must be a non-empty list",
    ):
        build_config(hardcover_api_keys=[])


def test_hardcover_api_keys_list_items_must_be_strings(build_config):
    with pytest.raises(ConfigError, match="Config item 'hardcover_api_keys item' must be a str"):
        build_config(hardcover_api_keys=[123, "Bearer secret123"])


def test_hardcover_api_keys_can_be_set(build_config):
    config = build_config(hardcover_api_keys=["Bearer newsecret"])
    assert config.get("hardcover_api_keys") == ["Bearer newsecret"]


def test_hardcover_api_keys_must_start_with_bearer(build_config):
    with pytest.raises(
        ConfigError, match="Config item 'hardcover_api_keys item' must start with 'Bearer '"
    ):
        build_config(hardcover_api_keys=["not-a-bearer-token"])


def test_editing_copy_does_not_modify_original(build_config):
    config = build_config()
    copy = config.copy()
    copy["new_key"] = "new_value"

    assert "new_key" not in config
    assert copy["new_key"] == "new_value"


def test_blacklisted_torrent_ids_must_be_list(build_config):
    with pytest.raises(ConfigError, match="Config item 'blacklisted_torrent_ids' must be a list"):
        build_config(blacklisted_torrent_ids="not-a-list")


def test_blacklisted_torrent_ids_list_items_must_be_int(build_config):
    with pytest.raises(
        ConfigError, match="Config item 'blacklisted_torrent_ids item' must be an int"
    ):
        build_config(blacklisted_torrent_ids=[123, "not-an-int"])


def test_blacklisted_torrent_ids_can_be_set(build_config):
    config = build_config(blacklisted_torrent_ids=[123, 456])
    assert config.get("blacklisted_torrent_ids") == [123, 456]


def test_torrent_timeout_seconds_must_be_int(build_config):
    with pytest.raises(ConfigError, match="Config item 'torrent_timeout_seconds' must be an int"):
        build_config(torrent_timeout_seconds="not-an-int")


@pytest.mark.parametrize("value", [-0.01, 1.01, float("nan"), float("inf"), -float("inf")])
def test_threshold_must_be_finite_and_in_range(build_config, value):
    with pytest.raises(ConfigError, match="matcher_threshold.*between 0 and 1"):
        build_config(matcher_threshold=value)


@pytest.mark.parametrize("value", [0.0, 1.0])
def test_threshold_boundaries_are_valid(build_config, value):
    assert build_config(matcher_threshold=value).matcher_threshold == value


@pytest.mark.parametrize("value", [0, -1, 65536, True])
def test_port_must_be_valid(build_config, value):
    with pytest.raises(ConfigError, match="qbittorrent.port"):
        build_config(qbittorrent=base["qbittorrent"] | {"port": value})


@pytest.mark.parametrize("value", [1, 65535])
def test_port_boundaries_are_valid(build_config, value):
    config = build_config(qbittorrent=base["qbittorrent"] | {"port": value})
    assert config.qbittorrent["port"] == value


@pytest.mark.parametrize("value", [0, -1, True, 1.5])
@pytest.mark.parametrize("key", ["torrent_timeout_seconds", "calibre.command_timeout_seconds"])
def test_timeouts_must_be_positive_integers(build_config, key, value):
    overrides = (
        {"calibre": {"library": "metadata.db", "command_timeout_seconds": value}}
        if key.startswith("calibre.")
        else {key: value}
    )
    with pytest.raises(ConfigError, match=key):
        build_config(**overrides)


def test_calibre_timeout_default_and_override(build_config):
    assert build_config().calibre["command_timeout_seconds"] == 120
    config = build_config(calibre={"library": "metadata.db", "command_timeout_seconds": 5})
    assert config.calibre["command_timeout_seconds"] == 5


def test_hardcover_per_user_lists_and_legacy_tokens(build_config):
    entries = [
        "Bearer legacy",
        {"api_key": "Bearer first", "list": "download-queue"},
        {"api_key": "Bearer second"},
    ]
    config = build_config(hardcover_api_keys=entries)
    assert config.hardcover_api_keys == entries
    assert all(
        token not in str(config) for token in ("Bearer legacy", "Bearer first", "Bearer second")
    )


@pytest.mark.parametrize(
    "entry",
    [
        {"list": "books"},
        {"api_key": "not-bearer"},
        {"api_key": 123},
        {"api_key": "Bearer secret", "list": None},
        {"api_key": "Bearer secret", "list": ""},
        {"api_key": "Bearer secret", "list": "My Books"},
        {"api_key": "Bearer secret", "list": "https://hardcover.app/@user/lists/books"},
        {"api_key": "Bearer secret", "list_slug": "typo"},
    ],
)
def test_hardcover_invalid_per_user_settings_rejected(build_config, entry):
    with pytest.raises(ConfigError):
        build_config(hardcover_api_keys=[entry])

@pytest.mark.parametrize(
    "key,value",
    [
        ("scan_timeout_seconds", 0),
        ("scan_timeout_seconds", -1),
        ("scan_timeout_seconds", True),
        ("scan_timeout_seconds", 1.5),
        ("staging_path", "relative/staging"),
        ("folder_id", ""),
        ("folder_id", 123),
    ],
)
def test_invalid_audiobook_import_settings(build_config, key, value):
    with pytest.raises(ConfigError, match="audiobookshelf"):
        build_config(audiobookshelf=audiobook_settings(**{key: value}))


def test_audiobook_scan_timeout_is_independent_of_download_timeout(build_config):
    config = build_config(audiobookshelf=audiobook_settings(), torrent_timeout_seconds=1800)
    assert config.audiobookshelf["scan_timeout_seconds"] == 120
    config = build_config(audiobookshelf=audiobook_settings(scan_timeout_seconds=7))
    assert config.audiobookshelf["scan_timeout_seconds"] == 7
