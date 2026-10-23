from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from murid.clients.calibre import CalibreConfig, CalibreError
from murid.config import ConfigError
from murid.domain.book import Book
from murid.libraries.audiobookshelf import AudiobookshelfLibrary
from murid.services.service_factory import ServiceFactory


def test_wanted_requests_normalize_and_combine_lists(args, config, monkeypatch):
    config["hardcover_api_keys"] = [
        "Bearer legacy",
        {"api_key": "Bearer both", "media_types": ["ebook", "audiobook"]},
        {"api_key": "Bearer audio", "list": "audio", "media_types": ["audiobook"]},
    ]
    book = Book("Title", ["Author"], 42, [], "Hardcover")
    clients = []

    def create(token, list_slug):
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
    constructor.assert_any_call("Bearer key", list_slug="want-to-read")
    constructor.assert_any_call("Bearer key", list_slug="audio")
    with pytest.raises(ConfigError, match="Audiobook execution is not supported"):
        factory.sync_service().run()


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
    constructor.assert_any_call("Bearer key", list_slug="want-to-read")
    constructor.assert_any_call("Bearer key", list_slug="a")


@pytest.mark.parametrize(
    "operation",
    [
        "hardcover",
        "retry_service",
        "torrent_import",
    ],
)
def test_audiobook_workflows_fail_before_constructing_clients(args, config, monkeypatch, operation):
    config["hardcover_api_keys"] = [{"api_key": "Bearer key", "media_types": ["audiobook"]}]
    config.pop("calibre")
    client = Mock(side_effect=AssertionError("No network calls expected"))
    monkeypatch.setattr("murid.services.service_factory.Hardcover", client)
    factory = ServiceFactory(args, config, initialize_notifier=False)
    with pytest.raises(ConfigError, match="Audiobook execution is not supported yet"):
        getattr(factory, operation)()
    client.assert_not_called()


def test_audio_only_factory_does_not_initialize_calibre(args, config, monkeypatch):
    config["hardcover_api_keys"] = [{"api_key": "Bearer key", "media_types": ["audiobook"]}]
    config.pop("calibre")
    client = Mock()
    monkeypatch.setattr("murid.services.service_factory.Calibre", client)
    with pytest.raises(ConfigError, match="requires an ebook request"):
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
        {"api_key": "Bearer key", "media_types": ["ebook", "audiobook"]},
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
        "hardcover_api_keys": ["Bearer secret"],
        "mam_id": "mam-cookie",
        "lang_codes": ["eng"],
        "schedule": "0 * * * *",
        "qbittorrent": {
            "host": "localhost",
            "port": 8080,
            "verify_cert": False,
            "category": "books",
        },
        "apprise": {"urls": ["discord://foo"]},
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

    def fake_hardcover(api_key):
        # created.append((api_key, user_id))
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


def test_notifier_disabled(args, config):
    config.pop("apprise")

    factory = ServiceFactory(args, config)

    notify = factory.notifier()

    assert callable(notify)
    assert notify("a", "b") is None


def test_notifier_enabled(args, config, monkeypatch):
    notify_mock = Mock()

    monkeypatch.setattr(
        "murid.services.service_factory.apprise",
        lambda logger, cfg: notify_mock,
    )

    factory = ServiceFactory(args, config)

    assert factory.notifier() is notify_mock


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


def test_retry_service_loads_all_hardcover_accounts_lazily(args, config, monkeypatch):
    factory = ServiceFactory(args, config, initialize_notifier=False)
    clients = [Mock(), Mock()]
    clients[0].get_books.return_value = ["first-book"]
    clients[1].get_books.return_value = ["second-book"]
    load_clients = Mock(return_value=clients)
    monkeypatch.setattr(factory, "hardcover", load_clients)
    monkeypatch.setattr(factory, "qbittorrent", Mock())
    monkeypatch.setattr(factory, "torrent_import", Mock())
    monkeypatch.setattr(factory, "myanonamouse", Mock())

    service = factory.retry_service()
    load_clients.assert_not_called()
    assert list(service.hardcover_books()) == ["first-book", "second-book"]
    load_clients.assert_called_once_with()
    for client in clients:
        client.get_books.assert_called_once_with()


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
        "Bearer legacy",
        {"api_key": "Bearer custom", "list": "download-queue"},
        {"api_key": "Bearer default"},
    ]
    constructor = Mock(side_effect=lambda *args, **kwargs: Mock())
    monkeypatch.setattr("murid.services.service_factory.Hardcover", constructor)
    clients = ServiceFactory(args, config, initialize_notifier=False).hardcover()
    assert len(clients) == 3
    constructor.assert_any_call("Bearer legacy")
    constructor.assert_any_call("Bearer custom", list_slug="download-queue")
    constructor.assert_any_call("Bearer default", list_slug="want-to-read")
    assert all(client.lang_codes == ["eng"] for client in clients)
