from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from murid.clients.myanonamouse import MAMError
from murid.domain.book import Book
from murid.domain.torrent import Torrent, TorrentMetadata
from murid.services.retry_service import RetryService


@pytest.fixture
def torrent_client():
    return Mock()


@pytest.fixture
def import_service():
    return Mock()


@pytest.fixture
def mam():
    return Mock()


@pytest.fixture
def service(torrent_client, import_service, mam):
    return RetryService(
        torrent_client=torrent_client,
        import_service=import_service,
        myanonamouse=mam,
    )


@pytest.fixture
def book():
    return Book(
        title="Dune",
        authors=["Frank Herbert"],
        id=1,
        isbn=[],
        source="test",
    )


def test_fetch_previous_torrents_empty(service, torrent_client):
    torrent_client.get_torrents_with_tag.return_value = []

    assert list(service.fetch_previous_torrents()) == []


def test_fetch_previous_torrents_valid_mid(service, torrent_client):
    torrent_client.get_torrents_with_tag.return_value = [
        SimpleNamespace(
            hash="torrent1",
            comment="something MID=123 something",
        )
    ]

    assert list(service.fetch_previous_torrents()) == [("torrent1", 123)]


def test_fetch_previous_torrents_ignores_missing_mid(
    service,
    torrent_client,
):
    torrent_client.get_torrents_with_tag.return_value = [
        SimpleNamespace(
            hash="torrent1",
            comment="no mam id here",
        )
    ]

    assert list(service.fetch_previous_torrents()) == []


def test_fetch_previous_torrents_mixed(service, torrent_client):
    torrent_client.get_torrents_with_tag.return_value = [
        SimpleNamespace(hash="a", comment="MID=111"),
        SimpleNamespace(hash="b", comment="nothing"),
        SimpleNamespace(hash="c", comment="MID=222"),
    ]

    assert list(service.fetch_previous_torrents()) == [
        ("a", 111),
        ("c", 222),
    ]


def make_torrent(book):
    return Torrent(
        book=book,
        metadata=TorrentMetadata(
            category=1,
            size=100,
            seeders=1,
            leechers=0,
            freeleech=False,
            vip=False,
        ),
    )


def test_get_book_by_mam_id_success(service, mam, book):
    mam.search.return_value = [make_torrent(book)]

    result = service.get_book_by_mam_id(123)

    assert result == book


def test_get_book_by_mam_id_no_results(service, mam):
    mam.search.return_value = []

    assert service.get_book_by_mam_id(123) is None


def test_get_book_by_mam_id_multiple_results(service, mam, book):
    mam.search.return_value = [
        make_torrent(book),
        make_torrent(book),
    ]

    assert service.get_book_by_mam_id(123) is None


def test_get_book_by_mam_id_mam_error(service, mam):
    mam.search.side_effect = MAMError("boom")

    assert service.get_book_by_mam_id(123) is None


def test_retry_torrents_success(
    service,
    import_service,
    torrent_client,
    book,
):
    service.fetch_previous_torrents = Mock(return_value=[("torrent1", 123)])

    service.get_book_by_mam_id = Mock(return_value=book)

    import_service.process_torrent.return_value = True

    service.retry_torrents()

    torrent_client.remove_tag.assert_called_once_with(
        "torrent1",
        "murid_timeout",
    )


def test_retry_torrents_import_failed(
    service,
    import_service,
    torrent_client,
    book,
):
    service.fetch_previous_torrents = Mock(return_value=[("torrent1", 123)])

    service.get_book_by_mam_id = Mock(return_value=book)

    import_service.process_torrent.return_value = False

    service.retry_torrents()

    torrent_client.remove_tag.assert_not_called()


def test_retry_torrents_book_not_found(
    service,
    import_service,
    torrent_client,
):
    service.fetch_previous_torrents = Mock(return_value=[("torrent1", 123)])

    service.get_book_by_mam_id = Mock(return_value=None)

    service.retry_torrents()

    import_service.process_torrent.assert_not_called()
    torrent_client.remove_tag.assert_not_called()
