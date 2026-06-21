from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from murid import ServiceFactory
from murid.clients.calibre import CalibreError


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
        "calibre_db_path": "/tmp/metadata.db",
        "calibredb_executable": "calibredb",
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


def test_matcher(args, config, monkeypatch):
    factory = ServiceFactory(args)

    monkeypatch.setattr(factory, "_load_config", lambda: config)

    matcher = factory.matcher()

    assert matcher.threshold == 0.9


def test_calibre(args, config, monkeypatch):
    factory = ServiceFactory(args)

    created = Mock()

    monkeypatch.setattr(factory, "_load_config", lambda: config)

    def fake_calibre(db, exe):
        created(db, exe)
        return "CALIBRE"

    monkeypatch.setattr(
        "murid.services.service_factory.Calibre",
        fake_calibre,
    )

    assert factory.calibre() == "CALIBRE"

    created.assert_called_once_with(
        "/tmp/metadata.db",
        "calibredb",
    )


def test_calibre_error_exits(args, config, monkeypatch):
    factory = ServiceFactory(args)

    monkeypatch.setattr(factory, "_load_config", lambda: config)

    def fail(*args):
        raise CalibreError("boom")

    monkeypatch.setattr(
        "murid.services.service_factory.Calibre",
        fail,
    )

    with pytest.raises(SystemExit):
        factory.calibre()


def test_hardcover(args, config, monkeypatch):
    factory = ServiceFactory(args)

    monkeypatch.setattr(factory, "_load_config", lambda: config)

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
    factory = ServiceFactory(args)

    monkeypatch.setattr(factory, "_load_config", lambda: config)

    monkeypatch.setattr(
        "murid.services.service_factory.MyAnonamouse",
        lambda mam_id: ("mam", mam_id),
    )

    assert factory.myanonamouse() == ("mam", "mam-cookie")


def test_notifier_disabled(args, config, monkeypatch):
    config.pop("apprise")

    factory = ServiceFactory(args)

    monkeypatch.setattr(factory, "_load_config", lambda: config)

    notify = factory.notifier()

    assert callable(notify)
    assert notify("a", "b") is None


def test_notifier_enabled(args, config, monkeypatch):
    factory = ServiceFactory(args)

    monkeypatch.setattr(factory, "_load_config", lambda: config)

    notify_mock = Mock()

    monkeypatch.setattr(
        "murid.services.service_factory.apprise",
        lambda logger, cfg: notify_mock,
    )

    assert factory.notifier() is notify_mock


def test_cron_iter(args, config, monkeypatch):
    factory = ServiceFactory(args)

    monkeypatch.setattr(factory, "_load_config", lambda: config)

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


def test_sync_service(args, monkeypatch):
    factory = ServiceFactory(args)

    monkeypatch.setattr(
        "murid.services.service_factory.SyncService",
        lambda f: ("sync", f),
    )

    result = factory.sync_service()

    assert result == ("sync", factory)
