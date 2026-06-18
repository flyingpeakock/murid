from murid import Book, Torrent, TorrentMetadata, TorrentSelector


class DummyMatcher:
    def __init__(self, result, threshold=0.9):
        self.result = result
        self.threshold = threshold

    def best_match(self, book, candidates):
        return self.result


def make_book(
    title="Dune",
    authors=None,
    book_id=1,
):
    return Book(
        title=title,
        authors=authors or ["Frank Herbert"],
        id=book_id,
        isbn=[],
        source="test",
    )


def make_torrent(
    title="Dune",
    language="en",
    file_types=None,
):
    return Torrent(
        book=make_book(title=title),
        metadata=TorrentMetadata(
            category=1,
            size=100,
            seeders=10,
            leechers=0,
            freeleech=False,
            vip=False,
        ),
        language=language,
        file_types=file_types or ["epub"],
    )


def test_select_returns_best_match():
    torrent = make_torrent()

    matcher = DummyMatcher(
        result=(torrent.book, 0.95),
        threshold=0.9,
    )

    selector = TorrentSelector({"en"})

    result = selector.select(
        make_book(),
        [torrent],
        matcher,
    )

    assert result is torrent


def test_select_returns_none_when_score_too_low():
    torrent = make_torrent()

    matcher = DummyMatcher(
        result=(torrent.book, 0.5),
        threshold=0.9,
    )

    selector = TorrentSelector({"en"})

    assert (
        selector.select(
            make_book(),
            [torrent],
            matcher,
        )
        is None
    )


def test_language_filtering():
    torrent = make_torrent(language="sv")

    matcher = DummyMatcher(
        result=(torrent.book, 1.0),
    )

    selector = TorrentSelector({"en"})

    assert (
        selector.select(
            make_book(),
            [torrent],
            matcher,
        )
        is None
    )


def test_none_language_is_allowed():
    torrent = make_torrent(language=None)

    matcher = DummyMatcher(
        result=(torrent.book, 1.0),
    )

    selector = TorrentSelector({"en"})

    assert (
        selector.select(
            make_book(),
            [torrent],
            matcher,
        )
        is torrent
    )


def test_filetype_filtering():
    torrent = make_torrent(file_types=["cbz"])

    matcher = DummyMatcher(
        result=(torrent.book, 1.0),
    )

    selector = TorrentSelector({"en"})

    assert (
        selector.select(
            make_book(),
            [torrent],
            matcher,
        )
        is None
    )


def test_custom_filetypes():
    torrent = make_torrent(file_types=["cbz"])

    matcher = DummyMatcher(
        result=(torrent.book, 1.0),
    )

    selector = TorrentSelector(
        {"en"},
        wanted_filetypes={"cbz"},
    )

    assert (
        selector.select(
            make_book(),
            [torrent],
            matcher,
        )
        is torrent
    )


def test_no_torrents_pass_filters():
    torrent = make_torrent(
        language="sv",
        file_types=["cbz"],
    )

    matcher = DummyMatcher((None, 0.0))

    selector = TorrentSelector({"en"})

    assert (
        selector.select(
            make_book(),
            [torrent],
            matcher,
        )
        is None
    )


def test_returns_matching_torrent():
    torrent1 = make_torrent(title="Dune")
    torrent2 = make_torrent(title="Hyperion")

    matcher = DummyMatcher(
        result=(torrent2.book, 1.0),
    )

    selector = TorrentSelector({"en"})

    result = selector.select(
        make_book(),
        [torrent1, torrent2],
        matcher,
    )

    assert result is torrent2
