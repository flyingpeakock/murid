# test_config.py

import logging
from copy import deepcopy
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import yaml

from murid.config import Config, ConfigError, env_constructor
from murid.services.service_factory import ServiceFactory

missing = object()
base = {
    "hardcover_api_keys": [{"api_key": "Bearer secret123", "reading_list": {"want-to-read": {}}}],
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
        "library_path": str(Path("audiobooks").absolute()),
        **overrides,
    }


def test_grouped_reading_lists_and_defaults(build_config):
    entries = [
        {
            "api_key": "Bearer key",
            "reading_list": {
                "want-to-read": {},
                "audio": {"type": "audiobook"},
                "both": {"type": ["ebook", "audiobook"]},
            },
        }
    ]
    config = build_config(hardcover_api_keys=entries, audiobookshelf=audiobook_settings())
    assert config.hardcover_lists == [
        {"api_key": "Bearer key", "list": "audio", "media_types": ["audiobook"]},
        {"api_key": "Bearer key", "list": "both", "media_types": ["ebook", "audiobook"]},
        {"api_key": "Bearer key", "list": "want-to-read", "media_types": ["ebook"]},
    ]


def test_reading_list_is_required(build_config):
    with pytest.raises(ConfigError, match="reading_list"):
        build_config(hardcover_api_keys=[{"api_key": "Bearer key"}])


def test_normalized_lists_preserve_raw_config_and_are_reused_by_factory(build_config, monkeypatch):
    entries = [{"api_key": "Bearer custom", "reading_list": {"selected": {}}}]
    config = build_config(hardcover_api_keys=entries)
    assert config.hardcover_api_keys == entries
    assert yaml.safe_load(str(config))["hardcover_api_keys"] == "**REDACTED**"
    normalize = Mock(side_effect=AssertionError("Loaded config must not be normalized again"))
    monkeypatch.setattr("murid.services.service_factory.hardcover_list_settings", normalize)
    factory = ServiceFactory(SimpleNamespace(), config, initialize_notifier=False)
    assert factory.hardcover_lists is config.hardcover_lists
    normalize.assert_not_called()


@pytest.mark.parametrize(
    "lists",
    [
        {},
        None,
        [],
        {"want to read": {}},
        {"": {}},
        {5: {}},
        {"audio": None},
        {"audio": {"format": "mp3"}},
        {"audio": {"type": "audiobooks"}},
        {"audio": {"type": []}},
        {"audio": {"type": True}},
        {"audio": {"type": ["video"]}},
    ],
)
def test_invalid_grouped_reading_lists(build_config, lists):
    with pytest.raises(ConfigError, match="reading_list"):
        build_config(hardcover_api_keys=[{"api_key": "Bearer key", "reading_list": lists}])


@pytest.mark.parametrize("legacy", [{"list": "a"}, {"media_types": ["ebook"]}])
def test_grouped_lists_reject_ambiguous_legacy_settings(build_config, legacy):
    with pytest.raises(ConfigError, match="Extra inputs are not permitted"):
        build_config(
            hardcover_api_keys=[
                {
                    "api_key": "Bearer key",
                    "reading_list": {"a": {}},
                    **legacy,
                }
            ]
        )


def test_grouped_audio_only_needs_no_calibre(build_config):
    config = build_config(
        calibre=missing,
        audiobookshelf=audiobook_settings(),
        hardcover_api_keys=[
            {
                "api_key": "Bearer key",
                "reading_list": {
                    "audio": {"type": "audiobook"},
                },
            }
        ],
    )
    assert config.audiobookshelf["library_id"] == "library-id"


@pytest.mark.parametrize("media_types", [[], "audiobook", ["video"], [None], [True]])
def test_reject_invalid_media_types(build_config, media_types):
    with pytest.raises(ConfigError, match="media_types"):
        build_config(hardcover_api_keys=[{"api_key": "Bearer key", "media_types": media_types}])


def test_audio_only_config_needs_no_calibre(build_config):
    config = build_config(
        calibre=missing,
        hardcover_api_keys=[
            {"api_key": "Bearer key", "reading_list": {"want-to-read": {"type": "audiobook"}}}
        ],
        audiobookshelf=audiobook_settings(),
    )
    assert config.audiobookshelf["filetypes"] == ["m4b", "mp3"]
    assert config.audiobookshelf["url"] == "https://audio.example.com/abs"


def test_audiobook_requests_require_backend(build_config):
    with pytest.raises(ConfigError, match="require audiobookshelf"):
        build_config(
            hardcover_api_keys=[
                {"api_key": "Bearer key", "reading_list": {"want-to-read": {"type": "audiobook"}}}
            ]
        )


def test_both_media_require_both_libraries(build_config):
    with pytest.raises(ConfigError, match="calibre.library"):
        build_config(
            calibre=missing,
            hardcover_api_keys=[
                {
                    "api_key": "Bearer key",
                    "reading_list": {"want-to-read": {"type": ["ebook", "audiobook"]}},
                }
            ],
            audiobookshelf=audiobook_settings(),
        )


@pytest.mark.parametrize("redact", [True, False])
def test_audiobookshelf_secret_always_redacted(build_config, redact):
    config = build_config(audiobookshelf=audiobook_settings(), redact_sensitive_data=redact)
    assert "audio-secret" not in str(config)
    assert config.audiobookshelf["api_key"] == "audio-secret"


@pytest.mark.parametrize(
    "key,value",
    [
        ("url", "ftp://example.com"),
        ("url", "https://user:secret@example.com"),
        ("url", "https://example.com?token=secret"),
        ("api_key", ""),
        ("url", "https://[broken"),
        ("url", "https://example.com:invalid"),
        ("library_id", ""),
        ("library_path", "relative/path"),
        ("filetypes", []),
        ("filetypes", ["epub"]),
        ("filetypes", "mp3"),
    ],
)
def test_invalid_audiobookshelf_settings(build_config, key, value):
    with pytest.raises(ConfigError, match=rf"audiobookshelf\.{key}[.:]"):
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
        data = deepcopy(base)
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

    assert config.get("hardcover_api_keys") == base["hardcover_api_keys"]
    assert config.get("redact_sensitive_data") is True


def test_default_redact_sensitive_data(build_config):
    config = build_config(redact_sensitive_data=missing)
    assert config.get("redact_sensitive_data") is True


def test_get_existing_key(build_config):
    config = build_config()
    assert config.get("hardcover_api_keys")[0]["api_key"] == "Bearer secret123"


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
        match="redact_sensitive_data",
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


@pytest.mark.parametrize("redact", [True, False])
def test_str_redacts_apprise_credentials(build_config, redact):
    apprise = {
        "urls": [
            "tgram://123456:bot-secret/123456",
            "https://hooks.example.com/webhook-secret",
            "mailto://user:smtp-secret@example.com",
        ]
    }
    config = build_config(apprise=apprise, redact_sensitive_data=redact)

    output = str(config)

    assert yaml.safe_load(output)["apprise"] == ("**REDACTED**" if redact else apprise)
    for secret in ("bot-secret", "webhook-secret", "smtp-secret"):
        assert (secret not in output) == redact
    assert config.get("apprise")["urls"] == apprise["urls"]


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
    with pytest.raises(ConfigError, match="matcher_threshold"):
        build_config(matcher_threshold="not-a-float")

    with pytest.raises(ConfigError, match="matcher_threshold"):
        build_config(matcher_threshold=1)


def test_matcher_threshold_can_be_set(build_config):
    config = build_config(matcher_threshold=0.92)
    assert config.get("matcher_threshold") == 0.92


def test_mam_id_must_exist(build_config):
    with pytest.raises(ConfigError, match="mam_id"):
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
    with pytest.raises(ConfigError, match="lang_codes"):
        build_config(lang_codes="not-a-list")


def test_lang_codes_list_items_must_be_strings(build_config):
    with pytest.raises(ConfigError, match="lang_codes.0"):
        build_config(lang_codes=[123, "SWE"])


def test_lang_codes_cannot_be_empty(build_config):
    with pytest.raises(ConfigError, match="lang_codes"):
        build_config(lang_codes=[])


def test_qbittorrent_config_must_be_dict(build_config):
    with pytest.raises(ConfigError, match="qbittorrent"):
        build_config(qbittorrent="not-a-dict")


def test_qbittorrent_config_requires_host(build_config):
    with pytest.raises(ConfigError, match="host"):
        build_config(qbittorrent={"username": "admin", "password": "adminadmin", "port": 8080})


def test_qbittorrent_config_requires_username(build_config):
    with pytest.raises(ConfigError, match="username"):
        build_config(
            qbittorrent={"host": "http://localhost", "password": "adminadmin", "port": 8080}
        )


def test_qbittorrent_config_requires_password(build_config):
    with pytest.raises(ConfigError, match="password"):
        build_config(qbittorrent={"host": "http://localhost", "username": "admin", "port": 8080})


def test_qbittorrent_config_requires_port(build_config):
    with pytest.raises(ConfigError, match="port"):
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
    with pytest.raises(ConfigError, match="qbittorrent.verify_cert"):
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
    with pytest.raises(ConfigError, match="qbittorrent.category"):
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
    with pytest.raises(ConfigError, match="schedule"):
        build_config(schedule="not-a-cron")

    with pytest.raises(ConfigError, match="schedule"):
        build_config(schedule="* * *")


def test_schedule_can_be_set(build_config):
    config = build_config(schedule="*/15 * * * *")
    assert config.get("schedule") == "*/15 * * * *"


def test_filetypes_defaults_to_epub_mobi_azw3_azw(build_config):
    config = build_config()
    assert config.get("filetypes") == ["epub", "mobi", "azw3", "azw"]


def test_filetypes_must_be_list(build_config):
    with pytest.raises(ConfigError, match="filetypes"):
        build_config(filetypes="not-a-list")


def test_filetypes_list_items_must_be_strings(build_config):
    with pytest.raises(ConfigError, match="filetypes.0"):
        build_config(filetypes=[123, "epub"])


def test_filetypes_can_be_overridden(build_config):
    config = build_config(filetypes=["pdf", "epub"])
    assert config.get("filetypes") == ["pdf", "epub"]


def test_hardcover_api_keys_must_be_present(build_config):
    with pytest.raises(ConfigError, match="hardcover_api_keys"):
        build_config(hardcover_api_keys=missing)


def test_hardcover_api_keys_must_be_list(build_config):
    with pytest.raises(ConfigError, match="hardcover_api_keys"):
        build_config(hardcover_api_keys="not-a-list")


def test_hardcover_api_keys_must_not_be_empty(build_config):
    with pytest.raises(
        ConfigError,
        match="hardcover_api_keys",
    ):
        build_config(hardcover_api_keys=[])


def test_hardcover_api_keys_list_items_must_be_accounts(build_config):
    with pytest.raises(ConfigError, match="hardcover_api_keys.0"):
        build_config(hardcover_api_keys=[123, "Bearer secret123"])


def test_hardcover_api_keys_can_be_set(build_config):
    entries = [{"api_key": "Bearer newsecret", "reading_list": {"want-to-read": {}}}]
    config = build_config(hardcover_api_keys=entries)
    assert config.get("hardcover_api_keys") == entries


def test_hardcover_api_keys_must_start_with_bearer(build_config):
    with pytest.raises(ConfigError, match="hardcover_api_keys.0"):
        build_config(
            hardcover_api_keys=[{"api_key": "not-a-bearer-token", "reading_list": {"books": {}}}]
        )


def test_editing_copy_does_not_modify_original(build_config):
    config = build_config()
    copy = config.copy()
    copy["new_key"] = "new_value"

    assert "new_key" not in config
    assert copy["new_key"] == "new_value"


def test_blacklisted_torrent_ids_must_be_list(build_config):
    with pytest.raises(ConfigError, match="blacklisted_torrent_ids"):
        build_config(blacklisted_torrent_ids="not-a-list")


def test_blacklisted_torrent_ids_list_items_must_be_int(build_config):
    with pytest.raises(ConfigError, match="blacklisted_torrent_ids.1"):
        build_config(blacklisted_torrent_ids=[123, "not-an-int"])


def test_blacklisted_torrent_ids_can_be_set(build_config):
    config = build_config(blacklisted_torrent_ids=[123, 456])
    assert config.get("blacklisted_torrent_ids") == [123, 456]


def test_torrent_timeout_seconds_must_be_int(build_config):
    with pytest.raises(ConfigError, match="torrent_timeout_seconds"):
        build_config(torrent_timeout_seconds="not-an-int")


@pytest.mark.parametrize("value", [-0.01, 1.01, float("nan"), float("inf"), -float("inf")])
def test_threshold_must_be_finite_and_in_range(build_config, value):
    with pytest.raises(ConfigError, match="matcher_threshold"):
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


def test_hardcover_grouped_accounts_and_redaction(build_config):
    entries = [
        {"api_key": "Bearer first", "reading_list": {"download-queue": {}}},
        {"api_key": "Bearer second", "reading_list": {"want-to-read": {}}},
    ]
    config = build_config(hardcover_api_keys=entries)
    assert config.hardcover_api_keys == entries
    assert all(token not in str(config) for token in ("Bearer first", "Bearer second"))


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
    with pytest.raises(ConfigError, match=rf"audiobookshelf\.{key}[.:]"):
        build_config(audiobookshelf=audiobook_settings(**{key: value}))


def test_audiobook_scan_timeout_is_independent_of_download_timeout(build_config):
    config = build_config(audiobookshelf=audiobook_settings(), torrent_timeout_seconds=1800)
    assert config.audiobookshelf["scan_timeout_seconds"] == 120
    config = build_config(audiobookshelf=audiobook_settings(scan_timeout_seconds=7))
    assert config.audiobookshelf["scan_timeout_seconds"] == 7


@pytest.mark.parametrize("document", ["[]", "true", "42", "text", "", "null"])
def test_invalid_or_empty_root_reports_config_error(document):
    with pytest.raises(ConfigError):
        make_config(document)


def test_null_uses_defaults_in_previously_merged_sections(build_config):
    config = build_config(
        matcher_threshold=None,
        lang_codes=None,
        schedule=None,
        qbittorrent=base["qbittorrent"] | {"verify_cert": None, "mapping": None},
        calibre={"library": "metadata.db", "command_timeout_seconds": None},
    )
    assert config.matcher_threshold == 0.92
    assert config.lang_codes == ["ENG"]
    assert config.schedule == "0 * * * *"
    assert config.qbittorrent["verify_cert"] is True
    assert config.qbittorrent["mapping"] == {"qbit_path": None, "murid_path": None}
    assert config.calibre["command_timeout_seconds"] == 120


def test_nested_null_does_not_hide_invalid_reading_list_options(build_config):
    with pytest.raises(ConfigError, match="reading_list"):
        build_config(
            hardcover_api_keys=[
                {
                    "api_key": "Bearer key",
                    "reading_list": {"books": {"type": None}},
                }
            ]
        )


@pytest.mark.parametrize(
    "entry",
    [
        "Bearer legacy",
        {"api_key": "Bearer legacy", "list": "books"},
        {"api_key": "Bearer legacy", "media_types": ["ebook"]},
    ],
)
def test_legacy_hardcover_formats_are_rejected(build_config, entry):
    with pytest.raises(ConfigError, match="hardcover_api_keys"):
        build_config(hardcover_api_keys=[entry])


def test_qbittorrent_passthrough_options_are_preserved(build_config):
    config = build_config(qbittorrent=base["qbittorrent"] | {"REQUESTS_ARGS": {"timeout": 7}})
    assert config.qbittorrent["REQUESTS_ARGS"] == {"timeout": 7}


@pytest.mark.parametrize(
    "overrides,path",
    [
        ({"qbittorrent": base["qbittorrent"] | {"port": "8080"}}, "qbittorrent.port"),
        ({"torrent_timeout_seconds": True}, "torrent_timeout_seconds"),
        ({"matcher_threshold": 1}, "matcher_threshold"),
        ({"blacklisted_torrent_ids": [True]}, "blacklisted_torrent_ids.0"),
        ({"lang_codes": [123]}, "lang_codes.0"),
    ],
)
def test_values_are_not_coerced(build_config, overrides, path):
    with pytest.raises(ConfigError, match=path):
        build_config(**overrides)


def test_validation_errors_do_not_disclose_input_secrets(build_config, caplog):
    secret = "sensitive-value-do-not-log"
    with pytest.raises(ConfigError) as error:
        build_config(
            hardcover_api_keys=[
                {
                    "api_key": secret,
                    "reading_list": {"books": {}},
                    "unexpected": secret,
                }
            ],
            qbittorrent=base["qbittorrent"] | {"port": secret},
            audiobookshelf=audiobook_settings(url=f"https://user:{secret}@example.com"),
        )
    assert "api_key" in str(error.value)
    assert "qbittorrent.port" in str(error.value)
    assert "audiobookshelf.url" in str(error.value)
    assert secret not in str(error.value)
    assert secret not in caplog.text
    assert error.value.__cause__ is None


def test_defaults_do_not_share_mutable_values(build_config):
    first = build_config()
    first.lang_codes.append("SWE")
    first.qbittorrent["mapping"]["qbit_path"] = "/downloads"
    second = build_config()
    assert second.lang_codes == ["ENG"]
    assert second.qbittorrent["mapping"]["qbit_path"] is None


def test_yaml_env_and_inline_env_are_trimmed(monkeypatch, tmp_path):
    monkeypatch.setenv("TEST_CONFIG_KEY", "  Bearer env-key  ")
    monkeypatch.setenv("TEST_CONFIG_PORT", "8080")
    data = deepcopy(base)
    data["calibre"]["library"] = str(tmp_path)
    document = yaml.safe_dump(data).replace("Bearer secret123", "!ENV TEST_CONFIG_KEY")
    # The YAML tag is handled by the constructor.
    config = make_config(document)
    assert config.hardcover_api_keys[0]["api_key"] == "Bearer env-key"
    # The quoted inline form is handled by sanitization.
    document = document.replace("api_key: !ENV TEST_CONFIG_KEY", 'api_key: "!ENV TEST_CONFIG_KEY"')
    assert make_config(document).hardcover_api_keys[0]["api_key"] == "Bearer env-key"
    data["qbittorrent"]["port"] = "!ENV TEST_CONFIG_PORT"
    with pytest.raises(ConfigError, match="qbittorrent.port"):
        make_config(yaml.safe_dump(data))


@pytest.mark.parametrize(
    "mapping",
    [
        {"qbit_path": "/downloads"},
        {"murid_path": "/"},
        {"qbit_path": "/downloads", "murid_path": "/murid-nonexistent-download-mount"},
        {"qbit_path": 123, "murid_path": "/"},
    ],
)
def test_invalid_torrent_path_mapping(build_config, mapping):
    with pytest.raises(ConfigError, match="qbittorrent.mapping"):
        build_config(qbittorrent=base["qbittorrent"] | {"mapping": mapping})


def test_valid_torrent_path_mapping(build_config, tmp_path):
    mapping = {"qbit_path": "/downloads", "murid_path": str(tmp_path)}
    config = build_config(qbittorrent=base["qbittorrent"] | {"mapping": mapping})
    assert config.qbittorrent["mapping"] == mapping


@pytest.mark.parametrize(
    "overrides,path",
    [
        ({"audiobookshelf": audiobook_settings(unknown=True)}, "audiobookshelf.unknown"),
        ({"audiobookshelf": audiobook_settings(scan_timeout_seconds=None)}, "scan_timeout_seconds"),
        ({"qbittorrent": base["qbittorrent"] | {"password": None}}, "qbittorrent.password"),
    ],
)
def test_section_specific_extra_and_null_policies(build_config, overrides, path):
    with pytest.raises(ConfigError, match=path):
        build_config(**overrides)
