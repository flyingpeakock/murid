from types import SimpleNamespace
from unittest.mock import Mock

from murid.services.connection_service import check_connections


def make_factory():
    calibre = SimpleNamespace(get_books=Mock(return_value={"book"}))
    mam = SimpleNamespace(check_connection=Mock())
    qbittorrent = SimpleNamespace(category="murid", get_torrents=Mock(return_value=["torrent"]))
    return SimpleNamespace(
        config={"hardcover_api_keys": ["Bearer first", "Bearer second"]},
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
