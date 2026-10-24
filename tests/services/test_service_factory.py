import logging
from io import StringIO
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

import pytest

from murid.clients.calibre import CalibreConfig, CalibreError
from murid.config import ConfigError
from murid.domain.book import Book
from murid.libraries.audiobookshelf import AudiobookshelfLibrary
from murid.notifications.apprise import AppriseHandler
from murid.services.service_factory import ServiceFactory


def test_wanted_requests_normalize_and_combine_lists(args, config, monkeypatch):
    config["hardcover_api_keys"] = [
        {"api_key": "Bearer legacy", "reading_list": {"want-to-read": {}}},
        {
            "api_key": "Bearer both",
            "reading_list": {"want-to-read": {"type": ["ebook", "audiobook"]}},
        },
        {"api_key": "Bearer audio", "reading_list": {"audio": {"type": ["audiobook"]}}},
    ]
    book = Book("Title", ["Author"], 42, [], "Hardcover")
    clients = []

    def create(token, list_slug, lang_codes):
        assert lang_codes == ["eng"]
        client = Mock()
        client.get_books.return_value = [book]
        clients.append((token, list_slug))
        return client

    monkeypatch.setattr("murid.services.service_factory.Hardcover", create)
    requests = ServiceFactory(args, config, initialize_notifier=False).wanted_requests()
    assert {request.identity for request in requests} == {(42, "ebook"), (42, "audiobook")}
    assert ("Bearer legacy", "want-to-read") in clients
    assert ("Bearer audio", "audio") in clients


def test_grouped_lists_expand_to_independent_requests(args, config, monkeypatch):
    config["hardcover_api_keys"] = [
        {
            "api_key": "Bearer key",
            "reading_list": {
                "want-to-read": {},
                "audio": {"type": "audiobook"},
            },
        }
    ]
    book = Book("Title", ["Author"], 42, [], "Hardcover")
    constructor = Mock(side_effect=lambda *args, **kwargs: Mock(get_books=lambda: [book]))
    monkeypatch.setattr("murid.services.service_factory.Hardcover", constructor)
    factory = ServiceFactory(args, config, initialize_notifier=False)
    assert {request.identity for request in factory.wanted_requests()} == {
        (42, "ebook"),
        (42, "audiobook"),
    }
    constructor.assert_any_call("Bearer key", list_slug="want-to-read", lang_codes=["eng"])
    constructor.assert_any_call("Bearer key", list_slug="audio", lang_codes=["eng"])


def test_grouped_ebook_lists_all_reach_legacy_workflow(args, config, monkeypatch):
    config["hardcover_api_keys"] = [
        {
            "api_key": "Bearer key",
            "reading_list": {
                "want-to-read": {},
                "a": {},
            },
        }
    ]
    constructor = Mock(side_effect=lambda *args, **kwargs: Mock())
    monkeypatch.setattr("murid.services.service_factory.Hardcover", constructor)
    assert len(ServiceFactory(args, config, initialize_notifier=False).hardcover()) == 2
    constructor.assert_any_call("Bearer key", list_slug="want-to-read", lang_codes=["eng"])
    constructor.assert_any_call("Bearer key", list_slug="a", lang_codes=["eng"])


def test_audio_only_factory_does_not_initialize_calibre(args, config, monkeypatch):
    config["hardcover_api_keys"] = [
        {"api_key": "Bearer key", "reading_list": {"want-to-read": {"type": ["audiobook"]}}}
    ]
    config.pop("calibre")
    client = Mock()
    monkeypatch.setattr("murid.services.service_factory.Calibre", client)
    with pytest.raises(ConfigError, match="requires Calibre configuration"):
        ServiceFactory(args, config, initialize_notifier=False).calibre()
    client.assert_not_called()


def test_audio_library_construction_never_initializes_calibre(args, config, monkeypatch):
    config.pop("calibre")
    config["audiobookshelf"] = {
        "url": "https://audio.example.com",
        "api_key": "secret",
        "library_id": "library-id",
    }
    audio = Mock()
    calibre = Mock(side_effect=AssertionError("Calibre must not be initialized"))
    monkeypatch.setattr("murid.services.service_factory.Audiobookshelf", audio)
    monkeypatch.setattr("murid.services.service_factory.Calibre", calibre)
    factory = ServiceFactory(args, config, initialize_notifier=False)

    backend = factory.library("audiobook")

    assert isinstance(backend, AudiobookshelfLibrary)
    assert backend.client is audio.return_value
    audio.assert_called_once_with("https://audio.example.com", "secret", "library-id")
    calibre.assert_not_called()


def test_unknown_library_type_fails_explicitly(args, config):
    with pytest.raises(ConfigError, match="Unknown media type"):
        ServiceFactory(args, config, initialize_notifier=False).library("video")


def test_discovery_uses_independent_media_format_preferences(args, config, monkeypatch):
    config.update(
        filetypes=["epub", "mobi"],
        blacklisted_torrent_ids=[],
        audiobookshelf={"filetypes": ["mp3", "m4b"]},
    )
    config["hardcover_api_keys"] = [
        {
            "api_key": "Bearer key",
            "reading_list": {"want-to-read": {"type": ["ebook", "audiobook"]}},
        },
    ]
    factory = ServiceFactory(args, config, initialize_notifier=False)
    monkeypatch.setattr(factory, "myanonamouse", Mock())
    monkeypatch.setattr(factory, "qbittorrent", Mock())
    discovery = factory.torrent_discovery()
    assert list(discovery.torrent_selectors["ebook"].filetype_priority) == ["epub", "mobi"]
    assert list(discovery.torrent_selectors["audiobook"].filetype_priority) == ["mp3", "m4b"]


@pytest.fixture
def args(tmp_path):
    return SimpleNamespace(
        config_file=str(tmp_path / "config.yaml"),
        dry_run=False,
    )


@pytest.fixture
def config():
    return {
        "matcher_threshold": 0.9,
        "calibre": {
            "library": "/tmp/metadata.db",
            "calibredb_executable": "calibredb",
        },
        "hardcover_api_keys": [{"api_key": "Bearer secret", "reading_list": {"want-to-read": {}}}],
        "mam_id": "mam-cookie",
        "lang_codes": ["eng"],
        "schedule": "0 * * * *",
        "qbittorrent": {
            "host": "localhost",
            "port": 8080,
            "verify_cert": False,
            "category": "books",
        },
        "apprise": None,
    }


def test_matcher(args, config):
    factory = ServiceFactory(args, config)

    matcher = factory.matcher()

    assert matcher.threshold == 0.9


def test_calibre(args, config, monkeypatch):
    factory = ServiceFactory(args, config)

    created = Mock()

    def fake_calibre(config):
        created(config)
        return "CALIBRE"

    monkeypatch.setattr(
        "murid.services.service_factory.Calibre",
        fake_calibre,
    )

    assert factory.calibre() == "CALIBRE"

    created.assert_called_once_with(
        CalibreConfig(
            executable="calibredb",
            library="/tmp/metadata.db",
        )
    )


def test_calibre_error_exits(args, config, monkeypatch):
    factory = ServiceFactory(args, config)

    def fail(*args):
        raise CalibreError("boom")

    monkeypatch.setattr(
        "murid.services.service_factory.Calibre",
        fail,
    )

    with pytest.raises(CalibreError, match="boom"):
        factory.calibre()


def test_hardcover(args, config, monkeypatch):
    factory = ServiceFactory(args, config)

    created = []

    def fake_hardcover(api_key, list_slug, lang_codes):
        assert list_slug == "want-to-read"
        assert lang_codes == ["eng"]
        created.append(api_key)
        return f"user-{api_key}"

    monkeypatch.setattr(
        "murid.services.service_factory.Hardcover",
        fake_hardcover,
    )

    result = factory.hardcover()

    assert result == {"user-Bearer secret"}
    assert created == ["Bearer secret"]


def test_myanonamouse(args, config, monkeypatch):
    factory = ServiceFactory(args, config)

    monkeypatch.setattr(
        "murid.services.service_factory.MyAnonamouse",
        lambda mam_id: ("mam", mam_id),
    )

    assert factory.myanonamouse() == ("mam", "mam-cookie")


@pytest.mark.parametrize("disabled_config", [None, [], {}])
def test_notifier_disabled(args, config, disabled_config):
    config["apprise"] = disabled_config

    factory = ServiceFactory(args, config)

    assert factory.notifier()("a", "b") is None


def test_notifier_omitted(args, config):
    config.pop("apprise")

    factory = ServiceFactory(args, config)

    notify = factory.notifier()

    assert callable(notify)
    assert notify("a", "b") is None


def test_notifier_enabled(args, config, monkeypatch):
    config["apprise"] = {"urls": ["json://notifications.invalid/notify"]}
    notify_mock = Mock()

    monkeypatch.setattr(
        "murid.services.service_factory.apprise",
        lambda logger, cfg: notify_mock,
    )

    factory = ServiceFactory(args, config)

    assert factory.notifier() is notify_mock


@pytest.mark.parametrize("remove_apprise", [False, True], ids=["null", "removed"])
def test_reload_disabling_notifications_removes_and_closes_handler(
    args, config, monkeypatch, remove_apprise
):
    config["apprise"] = {"urls": ["json://notifications.invalid/notify"]}
    logger = logging.Logger("test_reload_notifications")
    output = StringIO()
    other_handler = logging.StreamHandler(output)
    logger.addHandler(other_handler)
    monkeypatch.setattr("murid.services.service_factory.logger", logger)
    transport = MagicMock()
    transport.__len__.return_value = 1
    monkeypatch.setattr("murid.notifications.apprise.apprise.Apprise", lambda **_: transport)
    factory = ServiceFactory(args, config)
    handler = next(h for h in logger.handlers if isinstance(h, AppriseHandler))
    close = Mock(wraps=handler.close)
    monkeypatch.setattr(handler, "close", close)
    logger.error("before reload")
    transport.notify.assert_called_once()
    transport.notify.reset_mock()

    reloaded_config = config.copy()
    if remove_apprise:
        reloaded_config.pop("apprise")
    else:
        reloaded_config["apprise"] = None
    monkeypatch.setattr(factory, "_load_config", lambda: reloaded_config)

    factory.reload()
    logger.error("after reload")
    assert factory.notifier()(title="disabled", body="disabled") is None

    assert logger.handlers == [other_handler]
    close.assert_called_once_with()
    transport.notify.assert_not_called()
    assert "after reload" in output.getvalue()


def test_notifier_can_be_skipped_for_connection_check(args, config, monkeypatch):
    init_apprise = Mock(side_effect=RuntimeError("bad notification destination"))
    monkeypatch.setattr("murid.services.service_factory.apprise", init_apprise)

    factory = ServiceFactory(args, config, initialize_notifier=False)

    assert factory.notifier()("unused") is None
    init_apprise.assert_not_called()


def test_cron_iter(args, config, monkeypatch):
    factory = ServiceFactory(args, config)

    marker = object()

    monkeypatch.setattr(
        "murid.services.service_factory.croniter",
        lambda schedule, base: (schedule, base, marker),
    )

    result = factory.cron_iter("base-time")

    assert result == (
        "0 * * * *",
        "base-time",
        marker,
    )


def test_sync_service(args, config, monkeypatch):
    factory = ServiceFactory(args, config)

    monkeypatch.setattr(
        "murid.services.service_factory.SyncService",
        lambda f: ("sync", f),
    )

    result = factory.sync_service()

    assert result == ("sync", factory)


def test_retry_service_loads_hardcover_requests_lazily(args, config, monkeypatch):
    factory = ServiceFactory(args, config, initialize_notifier=False)
    requests = Mock(return_value=[])
    monkeypatch.setattr(factory, "wanted_requests", requests)
    monkeypatch.setattr(factory, "qbittorrent", Mock())
    monkeypatch.setattr(factory, "myanonamouse", Mock())
    service = factory.retry_service()
    requests.assert_not_called()
    assert list(service.hardcover_books()) == []
    requests.assert_called_once_with()


def test_qbittorrent_without_dry_run_option(config, monkeypatch):
    args = SimpleNamespace(config_file="/tmp/config.yaml")
    factory = ServiceFactory(args, config)
    created = []
    monkeypatch.setattr(
        "murid.services.service_factory.qbittorrentapi.Client",
        lambda **kwargs: object(),
    )
    monkeypatch.setattr(
        "murid.services.service_factory.Qbittorrent",
        lambda qbt_config: created.append(qbt_config) or "QBITTORRENT",
    )

    assert factory.qbittorrent() == "QBITTORRENT"
    assert created[0].dry_run is False


def test_torrent_import_without_dry_run_option(config, monkeypatch):
    config.update(torrent_timeout_seconds=1800, filetypes=["epub"])
    factory = ServiceFactory(SimpleNamespace(config_file="/tmp/config.yaml"), config)
    monkeypatch.setattr(factory, "qbittorrent", lambda: "QBITTORRENT")
    monkeypatch.setattr(factory, "calibre", lambda: "CALIBRE")
    monkeypatch.setattr(
        "murid.services.service_factory.TorrentImportService", lambda import_config: import_config
    )

    assert factory.torrent_import().dry_run is False


def test_hardcover_per_user_list_settings(args, config, monkeypatch):
    config["hardcover_api_keys"] = [
        {"api_key": "Bearer legacy", "reading_list": {"want-to-read": {}}},
        {"api_key": "Bearer custom", "reading_list": {"download-queue": {}}},
        {"api_key": "Bearer default", "reading_list": {"want-to-read": {}}},
    ]
    constructor = Mock(side_effect=lambda *args, **kwargs: Mock())
    monkeypatch.setattr("murid.services.service_factory.Hardcover", constructor)
    clients = ServiceFactory(args, config, initialize_notifier=False).hardcover()
    assert len(clients) == 3
    constructor.assert_any_call("Bearer legacy", list_slug="want-to-read", lang_codes=["eng"])
    constructor.assert_any_call("Bearer custom", list_slug="download-queue", lang_codes=["eng"])
    constructor.assert_any_call("Bearer default", list_slug="want-to-read", lang_codes=["eng"])


def test_audio_sync_import_and_retry_do_not_construct_calibre(args, config, monkeypatch):
    config["torrent_timeout_seconds"] = 1800
    config["hardcover_api_keys"] = [
        {"api_key": "Bearer key", "reading_list": {"want-to-read": {"type": ["audiobook"]}}}
    ]
    config.pop("calibre")
    config["audiobookshelf"] = {
        "url": "https://audio.example.com",
        "api_key": "secret",
        "library_id": "library",
        "library_path": "/shared/books",
    }
    calibre = Mock(side_effect=AssertionError("Calibre must not be initialized"))
    hardcover = Mock(side_effect=AssertionError("Recovery must load work metadata lazily"))
    monkeypatch.setattr("murid.services.service_factory.Calibre", calibre)
    monkeypatch.setattr("murid.services.service_factory.Hardcover", hardcover)
    factory = ServiceFactory(args, config, initialize_notifier=False)
    monkeypatch.setattr(factory, "qbittorrent", Mock())
    monkeypatch.setattr(factory, "myanonamouse", Mock())
    retry = factory.retry_service()
    importer = retry._importer("audiobook")
    assert importer.media_type == "audiobook"
    assert isinstance(importer.library, AudiobookshelfLibrary)
    calibre.assert_not_called()
    hardcover.assert_not_called()


def test_manual_audio_preferences_require_a_configured_backend(args, config):
    config["audiobookshelf"] = None
    factory = ServiceFactory(args, config, initialize_notifier=False)
    with pytest.raises(ConfigError, match="audiobookshelf"):
        factory.torrent_selector("audiobook")


@pytest.mark.parametrize("media", ["ebook", "audiobook"])
def test_wanted_requests_filter_before_fetching_unrelated_lists(args, config, monkeypatch, media):
    args.media_type = media
    config["hardcover_api_keys"] = [
        {
            "api_key": "Bearer key",
            "reading_list": {
                "ebooks": {"type": "ebook"},
                "audio": {"type": "audiobook"},
                "both": {"type": ["ebook", "audiobook"]},
            },
        }
    ]
    book = Book("Title", ["Author"], 42, [], "Hardcover")
    called = []

    def create(_token, list_slug, lang_codes):
        assert lang_codes == ["eng"]
        called.append(list_slug)
        return Mock(get_books=lambda: [book])

    monkeypatch.setattr("murid.services.service_factory.Hardcover", create)
    factory = ServiceFactory(args, config, initialize_notifier=False)
    assert {request.identity for request in factory.wanted_requests()} == {(42, media)}
    assert set(called) == {"both", "ebooks" if media == "ebook" else "audio"}


def test_media_filter_with_no_matching_lists_does_not_initialize_clients(args, config, monkeypatch):
    args.media_type = "audiobook"
    config["hardcover_api_keys"] = [
        {"api_key": "Bearer ebooks", "reading_list": {"want-to-read": {}}}
    ]
    client = Mock(side_effect=AssertionError("Unrelated list fetched"))
    monkeypatch.setattr("murid.services.service_factory.Hardcover", client)
    assert ServiceFactory(args, config, initialize_notifier=False).wanted_requests() == set()
    client.assert_not_called()


def test_factory_snapshots_list_settings_until_reload(args, config, monkeypatch):
    media = ["ebook"]
    entry = {"api_key": "Bearer first"}
    entry["reading_list"] = {"selected": {"type": media}}
    config["hardcover_api_keys"] = [entry]
    factory = ServiceFactory(args, config, initialize_notifier=False)
    media.append("audiobook")
    entry["api_key"] = "Bearer changed"
    book = Book("Title", ["Author"], 42, [], "hardcover")
    client = Mock()
    client.get_books.return_value = [book]
    client.get_book.return_value = book
    constructor = Mock(return_value=client)
    monkeypatch.setattr("murid.services.service_factory.Hardcover", constructor)

    assert factory.hardcover() == {client}
    assert {request.identity for request in factory.wanted_requests()} == {(42, "ebook")}
    assert factory.recovery_book(42) is book
    constructor.assert_called_with("Bearer first", list_slug="selected", lang_codes=["eng"])

    monkeypatch.setattr(factory, "_load_config", lambda: config)
    monkeypatch.setattr(factory, "_init_apprise", lambda: None)
    factory.reload()

    assert {request.identity for request in factory.wanted_requests()} == {
        (42, "ebook"),
        (42, "audiobook"),
    }
    assert factory.recovery_book(42) is book
    constructor.assert_called_with("Bearer changed", list_slug="selected", lang_codes=["eng"])


@pytest.mark.parametrize("media", ["ebook", "audiobook"])
def test_recovery_uses_account_for_selected_medium(args, config, monkeypatch, media):
    args.media_type = media
    other = "ebook" if media == "audiobook" else "audiobook"
    config["hardcover_api_keys"] = [
        {"api_key": "Bearer expired", "reading_list": {"unrelated": {"type": other}}},
        {"api_key": "Bearer active", "reading_list": {"selected": {"type": media}}},
    ]
    book = Book("Dune", ["Frank Herbert"], 42, [], "hardcover")
    client = Mock(get_book=Mock(return_value=book))

    def create(token, **kwargs):
        assert token == "Bearer active", "Recovery used an unrelated expired account"
        return client

    monkeypatch.setattr("murid.services.service_factory.Hardcover", create)
    factory = ServiceFactory(args, config, initialize_notifier=False)

    assert factory.recovery_book(42) is book
    client.get_book.assert_called_once_with(42)


def test_recovery_can_use_an_account_after_its_audio_lists_are_removed(args, config, monkeypatch):
    args.media_type = "audiobook"
    book = Book("Dune", ["Frank Herbert"], 42, [], "hardcover")
    client = Mock(get_book=Mock(return_value=book))
    constructor = Mock(return_value=client)
    monkeypatch.setattr("murid.services.service_factory.Hardcover", constructor)
    factory = ServiceFactory(args, config, initialize_notifier=False)

    assert factory.recovery_book(42) is book
    constructor.assert_called_once_with(
        "Bearer secret", list_slug="want-to-read", lang_codes=["eng"]
    )
