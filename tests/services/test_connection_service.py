from types import SimpleNamespace
from unittest.mock import Mock

from murid.config import hardcover_list_settings
from murid.services.connection_service import check_connections


def make_factory():
    calibre = SimpleNamespace(get_books=Mock(return_value={"book"}))
    mam = SimpleNamespace(check_connection=Mock())
    qbittorrent = SimpleNamespace(category="murid", get_torrents=Mock(return_value=["torrent"]))
    return SimpleNamespace(
        config={
            "hardcover_accounts": [
                {"api_key": "Bearer first", "reading_list": {"want-to-read": {}}},
                {"api_key": "Bearer second", "reading_list": {"want-to-read": {}}},
            ]
        },
        hardcover_lists=hardcover_list_settings(
            [
                {"api_key": token, "reading_list": {"want-to-read": {}}}
                for token in ["Bearer first", "Bearer second"]
            ]
        ),
        calibre=lambda: calibre,
        myanonamouse=lambda: mam,
        qbittorrent=lambda: qbittorrent,
    ), mam


def test_connections_checks_each_service(monkeypatch, capsys):
    factory, mam = make_factory()
    tokens = []

    def hardcover(token):
        tokens.append(token)
        return SimpleNamespace(user=SimpleNamespace(name=f"User {len(tokens)}"))

    monkeypatch.setattr("murid.services.connection_service.Hardcover", hardcover)

    assert check_connections(factory) is True

    output = capsys.readouterr().out
    assert "OK Hardcover account 1: authenticated as User 1" in output
    assert "OK Hardcover account 2: authenticated as User 2" in output
    assert "OK Calibre: 1 book readable" in output
    assert "OK MyAnonamouse: search API responded" in output
    assert "OK qBittorrent: category 'murid' readable (1 torrent)" in output
    assert "Connections: 5 passed, 0 failed" in output
    assert tokens == ["Bearer first", "Bearer second"]
    mam.check_connection.assert_called_once_with()


def test_connections_reports_failures_without_stopping(monkeypatch, capsys):
    factory, mam = make_factory()

    def hardcover(token):
        if token == "Bearer first":
            raise RuntimeError("invalid token")
        return SimpleNamespace(user=SimpleNamespace(name="Working User"))

    monkeypatch.setattr("murid.services.connection_service.Hardcover", hardcover)
    mam.check_connection.side_effect = RuntimeError("search unavailable")

    assert check_connections(factory) is False

    output = capsys.readouterr().out
    assert "FAIL Hardcover account 1: invalid token" in output
    assert "OK Hardcover account 2: authenticated as Working User" in output
    assert "OK Calibre:" in output
    assert "FAIL MyAnonamouse: search unavailable" in output
    assert "OK qBittorrent:" in output


def test_connections_handles_client_initialization_failure(monkeypatch, capsys):
    factory, _ = make_factory()
    factory.qbittorrent = Mock(side_effect=SystemExit(1))
    monkeypatch.setattr(
        "murid.services.connection_service.Hardcover",
        lambda token: SimpleNamespace(user=SimpleNamespace(name="User")),
    )

    assert check_connections(factory) is False

    assert "FAIL qBittorrent: client initialization failed; see logs" in capsys.readouterr().out


def test_audio_only_connections_skip_calibre_and_check_import_access(monkeypatch, capsys):
    factory, _ = make_factory()
    factory.config["hardcover_accounts"] = [
        {"api_key": "Bearer audio", "reading_list": {"want-to-read": {"type": ["audiobook"]}}},
    ]
    factory.hardcover_lists = hardcover_list_settings(factory.config["hardcover_accounts"])
    factory.calibre = Mock(side_effect=AssertionError("Calibre must not be initialized"))
    hardcover = Mock(return_value=SimpleNamespace(user=SimpleNamespace(name="User")))
    monkeypatch.setattr("murid.services.connection_service.Hardcover", hardcover)

    audio = Mock()
    audio.check_connection.return_value = "audio library prerequisites checked"
    factory.library = Mock(return_value=audio)
    assert check_connections(factory) is True
    factory.library.assert_called_once_with("audiobook")
    audio.check_connection.assert_called_once_with()
    factory.calibre.assert_not_called()
    hardcover.assert_called_once_with("Bearer audio")
    assert "OK Audiobookshelf: audio library prerequisites checked" in (capsys.readouterr().out)


def test_grouped_lists_check_each_account_once_and_both_libraries(monkeypatch, capsys):
    factory, _ = make_factory()
    factory.config["hardcover_accounts"] = [
        {
            "api_key": "Bearer grouped",
            "reading_list": {"ebooks": {}, "audio": {"type": "audiobook"}},
        }
    ]
    factory.hardcover_lists = hardcover_list_settings(factory.config["hardcover_accounts"])
    audio = SimpleNamespace(check_connection=lambda: "audio accessible")
    factory.library = Mock(return_value=audio)
    hardcover = Mock(return_value=SimpleNamespace(user=SimpleNamespace(name="User")))
    monkeypatch.setattr("murid.services.connection_service.Hardcover", hardcover)

    assert check_connections(factory)

    hardcover.assert_called_once_with("Bearer grouped")
    factory.library.assert_called_once_with("audiobook")
    output = capsys.readouterr().out
    assert "OK Calibre:" in output
    assert "Connections: 5 passed, 0 failed" in output


def test_filtered_connection_skips_configured_other_library(monkeypatch):
    factory, _ = make_factory()
    factory.args = SimpleNamespace(media_type="ebook")
    factory.config["audiobookshelf"] = {"url": "https://unavailable.example"}
    factory.library = Mock(side_effect=AssertionError("Unrelated library initialized"))
    monkeypatch.setattr(
        "murid.services.connection_service.Hardcover",
        lambda token: SimpleNamespace(user=SimpleNamespace(name="User")),
    )
    assert check_connections(factory)
    factory.library.assert_not_called()
