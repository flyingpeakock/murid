from murid import Book, Torrent, TorrentMetadata, TorrentSelector


class DummyMatcher:
    def __init__(self, result, threshold=0.9, match=True):
        self.result = result
        self.threshold = threshold
        self.match = match

    def similarity(self, book, candidate):
        return self.result[1] if candidate == self.result[0] else 0.0

    def is_match(self, book, candidate):
        return self.match


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
    id=1,
):
    return Torrent(
        book=make_book(title=title, book_id=id),
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


def test_select_rejects_candidate_failing_match_rules():
    torrent = make_torrent(title="Little Men")
    matcher = DummyMatcher((torrent.book, 1.0), match=False)
    selector = TorrentSelector({"en"})

    assert selector.select(make_book(title="Little Women"), [torrent], matcher) is None


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


def test_blacklist_filters_torrents():
    torrent = make_torrent(title="Dune", id=123)

    matcher = DummyMatcher((torrent.book, 1.0))

    selector = TorrentSelector({"en"}, blacklist={123})
    result = selector.select(
        make_book(),
        [torrent],
        matcher,
    )

    assert result is None


def test_blacklist_does_not_filter_non_matching_torrents():
    torrent = make_torrent(title="Dune", id=1234)

    matcher = DummyMatcher((torrent.book, 1.0))

    selector = TorrentSelector({"en"}, blacklist={123})
    result = selector.select(
        make_book(),
        [torrent],
        matcher,
    )

    assert result is torrent


def test_ranking_prefers_seeded_torrent_over_higher_scoring_unseeded():
    from murid import BookMatcher

    target = make_book()
    unseeded = make_torrent(id=1)
    unseeded.metadata.seeders = 0
    seeded = make_torrent(title="Dune: A Novel", id=2)
    seeded.metadata.seeders = 1
    matcher = BookMatcher()
    assert matcher.similarity(target, unseeded.book) > matcher.similarity(target, seeded.book)
    assert TorrentSelector({"en"}).select(target, [unseeded, seeded], matcher) is seeded


def test_ranking_respects_format_order_before_freeleech_and_seeder_count():
    from murid import BookMatcher

    epub = make_torrent(id=2)
    mobi = make_torrent(file_types=["mobi"], id=1)
    mobi.metadata.freeleech = True
    mobi.metadata.seeders = 100
    matcher = BookMatcher()
    assert (
        TorrentSelector({"en"}, ["epub", "mobi"]).select(make_book(), [mobi, epub], matcher) is epub
    )
    assert (
        TorrentSelector({"en"}, ["mobi", "epub"]).select(make_book(), [epub, mobi], matcher) is mobi
    )


def test_ranking_freeleech_then_seeders_then_stable_id():
    from murid import BookMatcher

    first, second, third = (make_torrent(id=i) for i in (1, 2, 3))
    first.metadata.seeders = 100
    second.metadata.freeleech = third.metadata.freeleech = True
    third.metadata.seeders = 20
    selector, matcher = TorrentSelector({"en"}), BookMatcher()
    assert selector.select(make_book(), [first, second, third], matcher) is third
    third.metadata.seeders = second.metadata.seeders
    for candidates in ([first, second, third], [third, second, first]):
        assert selector.select(make_book(), candidates, matcher) is second


def test_unseeded_fallback_and_matching_rules_are_preserved():
    from murid import BookMatcher

    matching = make_torrent(id=1)
    matching.metadata.seeders = 0
    wrong = make_torrent(title="Little Women", id=2)
    wrong.metadata.seeders = 1000
    wrong.metadata.freeleech = True
    assert TorrentSelector({"en"}).select(make_book(), [wrong, matching], BookMatcher()) is matching


def test_filtered_torrent_cannot_be_selected_with_same_book_metadata():
    from murid import BookMatcher

    rejected = make_torrent(language="sv")
    eligible = make_torrent(language="en")
    assert (
        TorrentSelector({"en"}).select(make_book(), [rejected, eligible], BookMatcher()) is eligible
    )
