import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from murid.domain.book import Book
from murid.domain.book_matcher import BookMatcher
from murid.domain.book_request import BookRequest
from murid.domain.torrent import Torrent, TorrentMetadata
from murid.domain.torrent_selector import TorrentSelector
from murid.services.book_lookup import BookLookupError
from murid.services.book_search import BookSearchError, search_book
from murid.services.torrent_import import ImportResult


def book(id, title="Dune", source="hardcover"):
    return Book(id=id, title=title, authors=["Frank Herbert"], isbn=[], source=source)


def torrent(id, title="Dune", language="ENG", file_types=None):
    return Torrent(
        book=book(id, title, "myanonamouse"),
        metadata=TorrentMetadata(14, 100, 5, 0, False, False),
        language=language,
        file_types=file_types if file_types is not None else ["epub"],
    )


def make_factory(hardcover_books, torrents, failed_ids=None):
    matcher = BookMatcher(0.92)
    selector = TorrentSelector({"ENG"}, {"epub"}, {104})
    mam = Mock()
    discovery = SimpleNamespace(
        find_torrents=Mock(return_value=(None, torrents)),
        mam_ids_with_tag=Mock(return_value=failed_ids or set()),
        torrent_selectors={"ebook": selector},
        mam=mam,
    )
    calibre = Mock()
    calibre.name = "Calibre"
    torrent_import = Mock()
    torrent_import.import_torrents.return_value = ImportResult(imported=1)
    factory = SimpleNamespace(
        matcher=lambda: matcher,
        hardcover=lambda: [SimpleNamespace(get_books=lambda: hardcover_books)],
        torrent_discovery=lambda media="ebook": discovery,
        library=lambda media: calibre,
        torrent_import=lambda media="ebook": torrent_import,
    )
    return factory, discovery


def test_search_book_previews_selection_and_rejections(capsys):
    target = book(1)
    results = {
        torrent(101),
        torrent(102, language="GER"),
        torrent(103, file_types=["pdf"]),
        torrent(104),
        torrent(105),
        torrent(106, title="Foundation"),
    }
    factory, discovery = make_factory({target}, results, {"105"})

    search_book("Dune", factory)

    output = capsys.readouterr().out
    assert "Hardcover: Dune by Frank Herbert" in output
    assert "MyAnonamouse candidates: 6" in output
    assert "SELECTED: Dune by Frank Herbert\n  ID 101" in output
    assert "Reason: language" in output
    assert "Reason: file type" in output
    assert "Reason: blacklisted ID" in output
    assert "Reason: previously failed import" in output
    assert "Reason: match score below threshold 0.920" in output
    assert output.index("SELECTED:") < output.index("REJECTED:")
    discovery.find_torrents.assert_called_once_with(BookRequest(target))
    discovery.mam_ids_with_tag.assert_called_once_with("murid-import-failed", "ebook")
    discovery.mam.download_torrent.assert_not_called()


def test_search_book_reports_no_results(capsys):
    factory, discovery = make_factory({book(1)}, set())

    search_book("Dune", factory)

    assert "No torrents found." in capsys.readouterr().out
    discovery.mam_ids_with_tag.assert_not_called()


def test_search_json_includes_candidate_metadata(monkeypatch, capsys):
    from murid import ui

    monkeypatch.setattr(ui, "OUTPUT_FORMAT", "json")
    factory, _ = make_factory({book(1)}, {torrent(101)})
    search_book("Dune", factory)
    records = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    candidate = next(record for record in records if record["type"] == "candidate")
    assert candidate["selected"]
    assert candidate["book"]["id"] == 101
    assert candidate["score"] == 1.0
    assert candidate["threshold"] == 0.92
    assert candidate["url"].endswith("/101")
    assert candidate["reasons"] == []


def test_search_explains_specific_matching_rule(capsys):
    target = book(1, "Dune Messiah")
    candidate = torrent(101, "Dune Messiah")
    target.series = candidate.book.series = "Dune"
    target.series_number, candidate.book.series_number = 2, 3
    factory, _ = make_factory({target}, {candidate})
    search_book("Dune Messiah", factory)
    assert "different series positions (2 vs 3)" in capsys.readouterr().out


def test_search_book_rejects_ambiguous_hardcover_name():
    factory, discovery = make_factory({book(1), book(2)}, set())

    with pytest.raises(BookLookupError, match="More than one Hardcover book"):
        search_book("Dune", factory)

    discovery.find_torrents.assert_not_called()


def test_search_book_adds_selected_torrent_and_checks_calibre(capsys):
    target = book(1)
    target.identifiers = {"Goodreads": ["44767458"]}
    target.isbn = ["9780441172719"]
    selected = torrent(101)
    factory, discovery = make_factory({target}, {selected})
    factory.library("ebook").contains_book.side_effect = [False, True]
    discovery.mam.download_torrent.return_value = b"torrent file"

    search_book("Dune", factory, add=True)

    discovery.mam.download_torrent.assert_called_once_with(selected)
    factory.torrent_import().import_torrents.assert_called_once_with([(b"torrent file", target)])
    assert factory.library("ebook").contains_book.call_count == 1
    assert "Imported Dune by Frank Herbert into Calibre" in capsys.readouterr().out


def test_search_book_add_rejects_existing_calibre_book():
    factory, discovery = make_factory({book(1)}, {torrent(101)})
    factory.library("ebook").contains_book.return_value = True

    with pytest.raises(BookSearchError, match="already in Calibre"):
        search_book("Dune", factory, add=True)

    discovery.mam.download_torrent.assert_not_called()
    factory.torrent_import().import_torrents.assert_not_called()


def test_search_book_add_rejects_no_selection():
    factory, discovery = make_factory({book(1)}, {torrent(102, language="GER")})

    with pytest.raises(BookSearchError, match="No torrent was selected"):
        search_book("Dune", factory, add=True)

    discovery.mam.download_torrent.assert_not_called()
    factory.torrent_import().import_torrents.assert_not_called()


def test_search_book_add_rejects_failed_torrent_download():
    factory, discovery = make_factory({book(1)}, {torrent(101)})
    factory.library("ebook").contains_book.return_value = False
    discovery.mam.download_torrent.return_value = None

    with pytest.raises(BookSearchError, match="Could not download torrent"):
        search_book("Dune", factory, add=True)

    factory.torrent_import().import_torrents.assert_not_called()


def test_search_book_add_reports_incomplete_import():
    factory, discovery = make_factory({book(1)}, {torrent(101)})
    factory.torrent_import().import_torrents.return_value = ImportResult(pending=1)
    factory.library("ebook").contains_book.return_value = False
    discovery.mam.download_torrent.return_value = b"torrent file"

    with pytest.raises(BookSearchError, match="not yet in Calibre"):
        search_book("Dune", factory, add=True)

    factory.torrent_import().import_torrents.assert_called_once()


def test_search_book_explains_vip_rejection_and_does_not_download(capsys):
    vip = torrent(101)
    vip.metadata.vip = True
    factory, discovery = make_factory({book(1)}, {vip})
    discovery.torrent_selectors["ebook"].exclude_vip = True

    with pytest.raises(BookSearchError, match="No torrent was selected"):
        search_book("Dune", factory, add=True)

    assert "Reason: VIP" in capsys.readouterr().out
    discovery.mam.download_torrent.assert_not_called()


@pytest.mark.parametrize("add", [False, True])
def test_explicit_selection_chooses_lower_ranked_candidate(add, capsys):
    selected = torrent(102)
    factory, discovery = make_factory({book(1)}, {torrent(101), selected})
    factory.library("ebook").contains_book.return_value = False
    discovery.mam.download_torrent.return_value = b"selected torrent"

    search_book("Dune", factory, torrent_id=102, add=add)

    assert "SELECTED: Dune by Frank Herbert\n  ID 102" in capsys.readouterr().out
    if add:
        discovery.mam.download_torrent.assert_called_once_with(selected)
    else:
        discovery.mam.download_torrent.assert_not_called()


@pytest.mark.parametrize(
    ("candidate", "failed_ids", "reason"),
    [
        (torrent(102, language="GER"), set(), "language"),
        (torrent(102, file_types=["pdf"]), set(), "file type"),
        (torrent(104), set(), "blacklisted ID"),
        (torrent(102), {"102"}, "previously failed import"),
        (torrent(102, title="Foundation"), set(), "match score below threshold"),
    ],
)
@pytest.mark.parametrize("add", [False, True])
def test_explicit_selection_preserves_rejections(candidate, failed_ids, reason, add):
    factory, discovery = make_factory({book(1)}, {torrent(101), candidate}, failed_ids)

    with pytest.raises(BookSearchError, match=reason):
        search_book("Dune", factory, torrent_id=candidate.book.id, add=add)

    discovery.mam.download_torrent.assert_not_called()
    factory.torrent_import().import_torrents.assert_not_called()


@pytest.mark.parametrize("results", [set(), {torrent(101)}])
def test_explicit_selection_requires_id_in_results(results):
    factory, discovery = make_factory({book(1)}, results)
    with pytest.raises(BookSearchError, match="102 was not found in search results"):
        search_book("Dune", factory, torrent_id=102, add=True)
    discovery.mam.download_torrent.assert_not_called()


@pytest.mark.parametrize("torrent_id", [0, -1])
def test_explicit_selection_requires_positive_id(torrent_id):
    factory, discovery = make_factory({book(1)}, {torrent(101)})
    with pytest.raises(BookSearchError, match="positive integer"):
        search_book("Dune", factory, torrent_id=torrent_id)
    discovery.find_torrents.assert_not_called()


def test_explicit_selection_preserves_vip_restriction():
    candidate = torrent(102)
    candidate.metadata.vip = True
    factory, discovery = make_factory({book(1)}, {torrent(101), candidate})
    discovery.torrent_selectors["ebook"].exclude_vip = True
    with pytest.raises(BookSearchError, match="VIP"):
        search_book("Dune", factory, torrent_id=102, add=True)
    discovery.mam.download_torrent.assert_not_called()


def test_explicit_audiobook_selection_json_dry_run(monkeypatch, capsys):
    from murid import ui

    monkeypatch.setattr(ui, "OUTPUT_FORMAT", "json")
    selected = torrent(102, file_types=["m4b"])
    factory, discovery = make_factory({book(1)}, {torrent(101), selected})
    discovery.torrent_selectors["audiobook"] = TorrentSelector(
        {"ENG"}, ["m4b"], media_type="audiobook"
    )
    factory.args = SimpleNamespace(dry_run=True)
    library = factory.library("audiobook")
    library.name = "Audiobookshelf"
    library.contains_book.return_value = False
    discovery.mam.download_torrent.return_value = b"selected audio torrent"

    search_book("Dune", factory, torrent_id=102, media_type="audiobook", add=True)

    discovery.find_torrents.assert_called_once_with(BookRequest(book(1), "audiobook"))
    discovery.mam.download_torrent.assert_called_once_with(selected)
    records = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    candidates = [record for record in records if record["type"] == "candidate"]
    assert [record["book"]["id"] for record in candidates if record["selected"]] == [102]
    assert all(record["media_type"] == "audiobook" for record in candidates)
    assert any(record["type"] == "planned" for record in records)
