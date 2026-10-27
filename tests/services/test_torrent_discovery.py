from concurrent.futures import Future, ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import Mock, call

import pytest

from murid.clients.myanonamouse import MAMError, MAMSearchError
from murid.domain.book_request import BookRequest
from murid.services.torrent_discovery import TorrentDiscoveryService


def test_rejected_title_does_not_discard_alternate_title_results(mam, caplog):
    book = SimpleNamespace(
        title="-Rejected",
        alternative_titles=["Alternate"],
        authors=["Author"],
        series=None,
        series_number=None,
    )
    torrent = Mock()
    mam.search_title.side_effect = [MAMSearchError("negative-only query"), {torrent}]
    mam.search_author.return_value = []
    _, results = TorrentDiscoveryService(mam, {"ebook": None}).find_torrents(BookRequest(book))
    assert results == {torrent}
    assert "-Rejected" in caplog.text
    assert "Alternate" == mam.search_title.call_args.args[0]


def test_rejected_search_does_not_abort_other_book_downloads(mam, matcher, caplog):
    service = TorrentDiscoveryService(mam, {"ebook": SimpleNamespace(select=lambda *args: torrent)})
    rejected, accepted = Future(), Future()
    book = FakeBook("Rejected", ["Author"])
    other = FakeBook("Working", ["Author"])
    torrent = FakeTorrent(other)
    rejected.set_exception(MAMSearchError("all title queries rejected"))
    accepted.set_result((other, {torrent}))
    mam.download_torrent.return_value = b"torrent"
    with ThreadPoolExecutor(max_workers=1) as executor:
        downloads = service.submit_downloads(
            executor, {rejected: BookRequest(book), accepted: BookRequest(other)}, matcher
        )
        assert service.collect_downloads(downloads) == [(b"torrent", BookRequest(other))]
    assert service.last_counts["search_failed"] == 1
    assert service.last_counts["failed"] == 1
    assert "continuing with other books" in caplog.text


@pytest.mark.parametrize(
    "error", [MAMError("invalid session"), RuntimeError("broken"), SystemExit(1)]
)
def test_search_errors_do_not_abort_discovery(mam, error, caplog):
    future = Future()
    future.set_exception(error)
    service = TorrentDiscoveryService(mam, {"ebook": None})
    with ThreadPoolExecutor(max_workers=1) as executor:
        assert not service.submit_downloads(
            executor, {future: BookRequest(FakeBook("Book"))}, Mock()
        )
    assert service.last_counts["failed"] == service.last_counts["search_failed"] == 1
    assert "search failed" in caplog.text


class FakeBook:
    def __init__(self, title, authors=None, series=None, series_number=None):
        self.id = id(self)
        self.title = title
        self.authors = authors or []
        self.series = series
        self.series_number = series_number


class FakeTorrent:
    def __init__(self, book):
        self.book = book


@pytest.fixture
def mam():
    return Mock()


@pytest.fixture
def matcher():
    return Mock()


def test_find_torrents_sets_series_and_returns(mam):
    book = SimpleNamespace(
        id=42,
        title="Dune",
        authors=["Frank Herbert"],
        series="Dune Saga",
        series_number=1,
    )

    torrent_book = SimpleNamespace(series=None, series_number=None)
    torrent = Mock()
    torrent.book = torrent_book

    mam.search_title.return_value = [torrent]

    service = TorrentDiscoveryService(mam, {"ebook": None})

    result_book, torrents = service.find_torrents(BookRequest(book))

    assert result_book == BookRequest(book)
    assert torrents == {torrent}

    mam.search_title.assert_called_once_with("Dune", "ebook")

    assert torrent.book.series == "Dune Saga"
    assert torrent.book.series_number == 1


def test_find_torrents_searches_main_and_alternate_titles_without_author(mam):
    book = SimpleNamespace(
        title="Main title",
        authors=["Author"],
        series=None,
        series_number=None,
        alternative_titles=["Alternate title"],
    )
    torrent = Mock()
    torrent.book = SimpleNamespace(series=None, series_number=None)
    mam.search_title.side_effect = [[torrent], []]

    service = TorrentDiscoveryService(mam, {"ebook": None})

    _, torrents = service.find_torrents(BookRequest(book))

    assert torrents == {torrent}
    assert mam.search_title.call_args_list == [
        call("Main title", "ebook"),
        call("Alternate title", "ebook"),
    ]
    mam.search_author.assert_not_called()


def test_find_torrents_searches_author_before_alternate_title_on_title_miss(mam):
    book = SimpleNamespace(
        title="Main title",
        authors=["Author"],
        series=None,
        series_number=None,
        alternative_titles=["Alternate title"],
    )
    torrent = Mock()
    torrent.book = SimpleNamespace(series=None, series_number=None)
    mam.search_title.side_effect = [[], []]
    mam.search_author.return_value = [torrent]

    _, torrents = TorrentDiscoveryService(mam, {"ebook": None}).find_torrents(BookRequest(book))

    assert torrents == {torrent}
    assert mam.search_title.call_args_list == [
        call("Main title", "ebook"),
        call("Alternate title", "ebook"),
    ]
    mam.search_author.assert_called_once_with("Author", "ebook")


def test_collect_downloads_filters_none():
    service = TorrentDiscoveryService(Mock(), {"ebook": None})

    future1 = Future()
    future1.set_result(b"file1")

    future2 = Future()
    future2.set_result(None)

    book1 = FakeBook(title="A")
    book2 = FakeBook(title="B")

    download_futures = {
        future1: BookRequest(book1),
        future2: BookRequest(book2),
    }

    result = service.collect_downloads(download_futures)

    assert result == [(b"file1", BookRequest(book1))]


def test_collect_downloads_deduplicates_without_reordering():
    service = TorrentDiscoveryService(Mock(), {"ebook": None})
    first_book, second_book = FakeBook("First"), FakeBook("Second")
    futures = {}
    for data, book in [(b"first", first_book), (b"second", second_book), (b"first", first_book)]:
        future = Future()
        future.set_result(data)
        futures[future] = BookRequest(book)
    assert service.collect_downloads(futures) == [
        (b"first", BookRequest(first_book)),
        (b"second", BookRequest(second_book)),
    ]


def test_submit_downloads_uses_submission_order_not_completion_order(mam, matcher):
    service = TorrentDiscoveryService(mam, {"ebook": None})
    first_book = FakeBook(title="A", authors=["Author"])
    second_book = FakeBook(title="B", authors=["Author"])
    first_torrent = FakeTorrent(first_book)
    second_torrent = FakeTorrent(second_book)
    torrents_by_book = {first_book: first_torrent, second_book: second_torrent}
    service.torrent_selectors["ebook"] = SimpleNamespace(
        select=lambda book, *_: torrents_by_book[book],
    )
    mam.download_torrent = Mock(return_value=b"torrent-file")

    first_future = Future()
    second_future = Future()
    # The second search completes first, but the first still must be selected first.
    second_future.set_result((second_book, [second_torrent]))
    first_future.set_result((first_book, [first_torrent]))

    with ThreadPoolExecutor(max_workers=1) as executor:
        service.submit_downloads(
            executor,
            {first_future: BookRequest(first_book), second_future: BookRequest(second_book)},
            matcher,
        )

    assert mam.download_torrent.call_args_list == [call(first_torrent), call(second_torrent)]


def test_submit_downloads_happy_path(mam, matcher):
    service = TorrentDiscoveryService(mam, {"ebook": None})
    service.torrent_selectors["ebook"] = SimpleNamespace(select=lambda *a, **k: torrent)

    book = SimpleNamespace(title="Dune", authors=["Frank"])
    torrent_book = SimpleNamespace()
    torrent = SimpleNamespace(book=torrent_book)

    search_future = Future()
    search_future.set_result((book, [torrent]))

    search_futures = {search_future: BookRequest(book)}

    executor = ThreadPoolExecutor(max_workers=1)

    mam.download_torrent = Mock(return_value=b"torrent-file")

    result = service.submit_downloads(executor, search_futures, matcher)

    assert len(result) == 1
    future = list(result.keys())[0]
    assert result[future].book is book


def test_submit_downloads_skips_torrent_tagged_import_failed(mam, matcher):
    failed_torrent = Mock()
    failed_torrent.book.id = 123
    available_torrent = Mock()
    available_torrent.book.id = 456

    torrent_client = Mock()
    torrent_client.get_torrents_with_tag.side_effect = lambda tag: (
        [SimpleNamespace(comment="MyAnonamouse MID=123")] if tag == "murid-import-failed" else []
    )
    service = TorrentDiscoveryService(mam, {"ebook": None}, torrent_client)
    service.torrent_selectors["ebook"] = SimpleNamespace(
        select=Mock(return_value=available_torrent)
    )
    mam.download_torrent.return_value = b"torrent-file"

    book = SimpleNamespace(title="Dune", authors=["Frank"])
    search_future = Future()
    search_future.set_result((book, {failed_torrent, available_torrent}))

    with ThreadPoolExecutor(max_workers=1) as executor:
        result = service.submit_downloads(executor, {search_future: BookRequest(book)}, matcher)

    torrent_client.get_torrents_with_tag.assert_called_once_with("murid-import-failed")
    service.torrent_selectors["ebook"].select.assert_called_once_with(
        book, {available_torrent}, matcher
    )
    assert len(result) == 1
    mam.download_torrent.assert_called_once_with(available_torrent)


def test_download_torrents_skips_books_with_incomplete_timed_out_torrent(mam, matcher):
    service = TorrentDiscoveryService(mam, {"ebook": None})
    service.find_torrents = Mock()
    matcher.threshold = 0.9
    matcher.similarity.return_value = 0.99

    book = SimpleNamespace(id=456, title="Dune", authors=["Frank"])
    timed_out_book = SimpleNamespace(id=456, title="Dune", authors=["Frank"])

    result = service.download_torrents([BookRequest(book)], matcher, [BookRequest(timed_out_book)])

    assert result == []
    service.find_torrents.assert_not_called()
    mam.search_title.assert_not_called()
    matcher.similarity.assert_not_called()
    mam.download_torrent.assert_not_called()


def test_submit_downloads_does_not_retry_after_selector_rejects(mam, matcher):
    original_torrent = Mock()
    original_torrent.book.id = 111

    service = TorrentDiscoveryService(mam, {"ebook": None})
    service.torrent_selectors["ebook"] = SimpleNamespace(select=Mock(return_value=None))
    book = SimpleNamespace(title="Dune", authors=["Frank"])
    search_future = Future()
    search_future.set_result((book, {original_torrent}))

    with ThreadPoolExecutor(max_workers=1) as executor:
        result = service.submit_downloads(executor, {search_future: BookRequest(book)}, matcher)

    assert result == {}
    service.torrent_selectors["ebook"].select.assert_called_once_with(
        book, {original_torrent}, matcher
    )
    mam.search_title.assert_not_called()
    mam.download_torrent.assert_not_called()


def test_submit_downloads_does_not_repeat_title_searches_when_matcher_rejects(mam, matcher):
    service = TorrentDiscoveryService(mam, {"ebook": None})
    original_torrent = Mock()
    service.torrent_selectors["ebook"] = SimpleNamespace(select=Mock(return_value=None))

    book = SimpleNamespace(
        title="Main title",
        authors=["Author"],
        alternative_titles=["Alternate title"],
    )
    search_future = Future()
    search_future.set_result((book, [original_torrent]))

    with ThreadPoolExecutor(max_workers=1) as executor:
        result = service.submit_downloads(executor, {search_future: BookRequest(book)}, matcher)
        assert result == {}

    service.torrent_selectors["ebook"].select.assert_called_once_with(
        book, [original_torrent], matcher
    )
    mam.search_title.assert_not_called()


def test_submit_downloads_skips_empty():
    service = TorrentDiscoveryService(Mock(), {"ebook": None})

    book = SimpleNamespace(title="Dune")

    search_future = Future()
    search_future.set_result((book, []))

    executor = ThreadPoolExecutor(max_workers=1)

    result = service.submit_downloads(executor, {search_future: BookRequest(book)}, Mock())

    assert result == {}


def test_submit_downloads_rejected_by_selector(mam):
    service = TorrentDiscoveryService(mam, {"ebook": None})
    service.torrent_selectors["ebook"] = SimpleNamespace(select=lambda *a, **k: None)
    mam.search_title.return_value = []

    book = FakeBook(title="Dune")
    torrent = SimpleNamespace(book=SimpleNamespace())

    search_future = Future()
    search_future.set_result((book, [torrent]))

    executor = ThreadPoolExecutor(max_workers=1)

    result = service.submit_downloads(executor, {search_future: BookRequest(book)}, Mock())

    assert result == {}


def test_download_torrents_happy_path(mam, matcher):
    service = TorrentDiscoveryService(mam, {"ebook": None})
    service.find_torrents = Mock(return_value=(SimpleNamespace(), ["torrent"]))
    service.submit_downloads = Mock(return_value={"future": "torrent"})
    service.collect_downloads = Mock(return_value=[(b"file", SimpleNamespace())])

    books = [SimpleNamespace(id=42, title="Dune")]

    result = service.download_torrents([BookRequest(book) for book in books], matcher)

    assert result == [(b"file", SimpleNamespace())]


def test_downloads_keep_requested_hardcover_metadata(mam):
    from murid.domain.book import Book
    from murid.domain.book_matcher import BookMatcher
    from murid.domain.torrent import Torrent, TorrentMetadata
    from murid.domain.torrent_selector import TorrentSelector

    requested = Book(
        title="Dune",
        authors=["Frank Herbert"],
        id=42,
        source="hardcover",
        isbn=["9780441172719"],
        identifiers={"Goodreads": ["44767458"]},
    )
    candidate = Torrent(
        book=Book(title="Dune", authors=["Frank Herbert"], id=99, source="myanonamouse", isbn=[]),
        metadata=TorrentMetadata(14, 100, 10, 0, False, False),
        language="ENG",
        file_types=["epub"],
    )
    mam.search_title.return_value = {candidate}
    mam.download_torrent.return_value = b"torrent"
    service = TorrentDiscoveryService(mam, {"ebook": TorrentSelector({"ENG"})})
    downloads = service.download_torrents([BookRequest(requested)], BookMatcher())
    assert downloads == [(b"torrent", BookRequest(requested))]
    assert downloads[0][1].book is requested
    mam.download_torrent.assert_called_once_with(candidate)


@pytest.mark.parametrize("medium", ["ebook", "audiobook"])
def test_title_author_and_alternate_searches_keep_medium(mam, medium):
    from murid.domain.book import Book

    book = Book("Main", ["Author"], 42, [], "hardcover", alternative_titles=["Alternate"])
    mam.search_title.return_value = set()
    mam.search_author.return_value = set()
    request = BookRequest(book, medium)
    result, torrents = TorrentDiscoveryService(mam, {}).find_torrents(request)
    assert result is request
    assert torrents == set()
    assert mam.search_title.call_args_list == [call("Main", medium), call("Alternate", medium)]
    mam.search_author.assert_called_once_with("Author", medium)


def test_discovery_keeps_series_evidence_for_a_different_audio_volume(mam):
    from murid.domain.book import Book
    from murid.domain.book_matcher import BookMatcher
    from murid.domain.torrent import Torrent, TorrentMetadata
    from murid.domain.torrent_selector import TorrentSelector

    book = Book(
        "Collected Stories", ["Author"], 42, [], "hardcover", series="Stories", series_number=1
    )
    candidate = Torrent(
        Book(book.title, book.authors, 100, [], "myanonamouse", series="Stories", series_number=2),
        TorrentMetadata(0, 100, 10, 0, False, False),
        language="ENG",
        file_types=["m4b"],
        media_type="audiobook",
    )
    mam.search_title.return_value = {candidate}
    selector = TorrentSelector({"ENG"}, media_type="audiobook")
    service = TorrentDiscoveryService(mam, {"audiobook": selector})
    _, results = service.find_torrents(BookRequest(book, "audiobook"))
    assert candidate.book.series_number == 2
    assert selector.select(book, results, BookMatcher()) is None


@pytest.mark.parametrize("incomplete_medium", ["ebook", "audiobook"])
def test_incomplete_work_suppresses_only_the_same_medium(mam, incomplete_medium):
    from murid.domain.book import Book
    from murid.domain.book_matcher import BookMatcher

    book = Book("Dune", ["Author"], 42, [], "hardcover")
    requests = {BookRequest(book, medium) for medium in ("ebook", "audiobook")}
    incomplete = BookRequest(book, incomplete_medium)
    service = TorrentDiscoveryService(mam, {})
    service.find_torrents = Mock(side_effect=lambda request: (request, set()))
    assert service.download_torrents(requests, BookMatcher(), [incomplete]) == []
    searched = service.find_torrents.call_args.args[0]
    assert searched.book is book
    assert searched.media_type != incomplete_medium
    assert service.last_counts["searched"] == 1
    assert service.last_counts["skipped"] == 1


def test_overlapping_requests_deduplicate_by_work_and_medium(mam):
    from dataclasses import replace

    from murid.domain.book import Book
    from murid.domain.book_matcher import BookMatcher
    from murid.domain.torrent import Torrent, TorrentMetadata
    from murid.domain.torrent_selector import TorrentSelector

    book = Book("Dune", ["Frank Herbert"], 42, [], "hardcover")
    selectors = {
        medium: TorrentSelector({"ENG"}, media_type=medium) for medium in ("ebook", "audiobook")
    }
    candidates = {
        medium: Torrent(
            Book("Dune", book.authors, index, [], "myanonamouse"),
            TorrentMetadata(0, 100, 10, 0, False, False),
            language="ENG",
            file_types=[fmt],
            media_type=medium,
        )
        for index, (medium, fmt) in enumerate([("ebook", "epub"), ("audiobook", "m4b")], 100)
    }
    mam.search_title.side_effect = lambda title, medium: {candidates[medium]}
    mam.download_torrent.return_value = b"torrent"
    requests = [
        BookRequest(book),
        BookRequest(replace(book, alternative_titles=["Dune!"])),
        BookRequest(book, "audiobook"),
    ]
    service = TorrentDiscoveryService(mam, selectors)
    downloads = service.download_torrents(requests, BookMatcher())
    assert {request.identity for _, request in downloads} == {(42, "ebook"), (42, "audiobook")}
    assert len(downloads) == 2
    assert service.last_counts["searched"] == service.last_counts["selected"] == 2
    assert mam.search_title.call_count == 2
    assert mam.download_torrent.call_count == 2


@pytest.mark.parametrize("medium", ["ebook", "audiobook"])
def test_failed_import_filter_is_scoped_to_media(mam, medium):
    from murid.domain.book import Book

    tagged = [
        SimpleNamespace(
            comment="MID=100", tags="murid_media_audiobook,murid_hardcover_42,murid-import-failed"
        ),
        SimpleNamespace(comment="MID=200", tags="murid-import-failed"),
    ]
    torrent_client = Mock()
    torrent_client.get_torrents_with_tag.return_value = tagged
    candidates = {Mock(book=SimpleNamespace(id=100)), Mock(book=SimpleNamespace(id=200))}
    selector = Mock(select=Mock(return_value=None))
    request = BookRequest(Book("Dune", ["Author"], 42, [], "hardcover"), medium)
    search = Future()
    search.set_result((request, candidates))
    service = TorrentDiscoveryService(mam, {medium: selector}, torrent_client)
    with ThreadPoolExecutor(max_workers=1) as executor:
        assert service.submit_downloads(executor, {search: request}, Mock()) == {}
    selected_ids = {torrent.book.id for torrent in selector.select.call_args.args[1]}
    assert selected_ids == ({200} if medium == "audiobook" else {100})


@pytest.mark.parametrize("medium,expected_ids", [("ebook", {"200"}), ("audiobook", {"300"})])
@pytest.mark.parametrize(
    "tags,comment",
    [
        ("murid-import-failed,murid_media_audiobook", "MID=100"),
        ("murid-import-failed", "MID=100\n[murid:1]invalid-json"),
    ],
)
def test_failed_import_filter_reports_invalid_identity_and_keeps_valid_ids(
    mam, caplog, medium, expected_ids, tags, comment
):
    invalid = SimpleNamespace(hash="invalid-torrent", tags=tags, comment=comment)
    original = vars(invalid).copy()
    client = Mock()
    client.get_torrents_with_tag.return_value = [
        invalid,
        SimpleNamespace(tags="murid-import-failed", comment="MID=200"),
        SimpleNamespace(
            tags="murid-import-failed,murid_media_audiobook,murid_hardcover_42", comment="MID=300"
        ),
    ]
    service = TorrentDiscoveryService(mam, {}, client)

    assert service.mam_ids_with_tag("murid-import-failed", medium) == expected_ids

    assert "invalid-torrent" in caplog.text
    assert "invalid" in caplog.text.lower()
    assert vars(invalid) == original
    client.add_tag.assert_not_called()
    client.remove_tag.assert_not_called()


@pytest.mark.parametrize("stage", ["search", "selection", "download"])
@pytest.mark.parametrize("error", [RuntimeError("unexpected"), SystemExit(1)])
def test_book_failure_does_not_discard_other_downloads(mam, matcher, stage, error, caplog):
    bad, good = BookRequest(FakeBook("Bad")), BookRequest(FakeBook("Good"))
    bad_torrent, good_torrent = FakeTorrent(bad.book), FakeTorrent(good.book)
    first, second = Future(), Future()
    if stage == "search":
        first.set_exception(error)
    else:
        first.set_result((bad, {bad_torrent}))
    second.set_result((good, {good_torrent}))
    selector = Mock()
    selector.select.side_effect = (
        [error, good_torrent]
        if stage == "selection"
        else ([good_torrent] if stage == "search" else [bad_torrent, good_torrent])
    )
    mam.download_torrent.side_effect = [error, b"ok"] if stage == "download" else [b"ok"]
    service = TorrentDiscoveryService(mam, {"ebook": selector})
    with ThreadPoolExecutor(max_workers=1) as executor:
        downloads = service.submit_downloads(executor, {first: bad, second: good}, matcher)
        assert service.collect_downloads(downloads) == [(b"ok", good)]
    assert service.last_counts["failed"] == 1
    assert f"{stage if stage != 'selection' else 'torrent selection'} failed" in caplog.text


def test_keyboard_interrupt_still_stops_discovery(mam):
    future = Future()
    future.set_exception(KeyboardInterrupt())
    with ThreadPoolExecutor(max_workers=1) as executor:
        with pytest.raises(KeyboardInterrupt):
            TorrentDiscoveryService(mam, {"ebook": None}).submit_downloads(
                executor, {future: BookRequest(FakeBook("Book"))}, Mock()
            )
