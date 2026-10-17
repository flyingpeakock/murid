from murid.domain.book import Book
from murid.domain.torrent import Torrent, TorrentMetadata


def make_book():
    return Book(
        title="Dune",
        authors=["Frank Herbert"],
        id=123,
        isbn=[],
        source="test",
    )


def make_metadata():
    return TorrentMetadata(
        category=14,
        size=1024,
        seeders=10,
        leechers=0,
        freeleech=False,
        vip=False,
    )


def test_download_url():
    torrent = Torrent(
        book=make_book(),
        metadata=make_metadata(),
        download_hash="abcdef",
    )

    assert torrent.download_url == "https://www.myanonamouse.net/tor/download.php/abcdef"


def test_download_url_none():
    torrent = Torrent(
        book=make_book(),
        metadata=make_metadata(),
        download_hash=None,
    )

    assert torrent.download_url is None


def test_str():
    torrent = Torrent(
        book=make_book(),
        metadata=make_metadata(),
    )

    assert str(torrent) == "https://www.myanonamouse.net/t/123"


def test_metadata_changes_preserve_set_membership_and_deduplication():
    torrent = Torrent(make_book(), make_metadata())
    torrents = {torrent}
    torrent.book.series = "Dune"
    torrent.book.series_number = 1
    torrent.book.alternative_titles.append("Dune: Book One")
    torrent.language = "ENG"
    torrent.file_types = ["epub"]
    torrent.download_hash = "new-download-token"

    assert torrent in torrents
    duplicate = Torrent(make_book(), make_metadata(), download_hash="another-token")
    assert duplicate == torrent
    assert hash(duplicate) == hash(torrent)
    torrents.add(duplicate)
    assert len(torrents) == 1
    torrents.remove(torrent)
    assert not torrents


def test_different_torrent_ids_remain_distinct():
    first = Torrent(make_book(), make_metadata(), download_hash="same-token")
    second = Torrent(make_book(), make_metadata(), download_hash="same-token")
    second.book.id = 456
    assert first != second
    assert len({first, second}) == 2
