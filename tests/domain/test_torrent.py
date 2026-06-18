from murid import Book, Torrent, TorrentMetadata


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
