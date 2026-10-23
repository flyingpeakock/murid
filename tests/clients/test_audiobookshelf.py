from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import requests

from murid.clients.audiobookshelf import Audiobookshelf, AudiobookshelfError
from murid.domain.book import Book
from murid.domain.book_matcher import BookMatcher
from murid.domain.book_request import BookRequest
from murid.libraries.audiobookshelf import AudiobookshelfLibrary
from murid.libraries.library import LibraryError
from murid.services.sync_service import SyncService


def item(item_id="item-1", **overrides):
    return {
        "id": item_id, "libraryId": "library", "mediaType": "book",
        "isMissing": False, "isInvalid": False,
        "media": {
            "numTracks": 1, "numAudioFiles": 1,
            "metadata": {"title": "Dune", "authors": [{"name": "Frank Herbert"}],
                         "isbn": "9780441172719", "asin": "edition-asin"},
            "tags": ["murid:hardcover:42"], "tracks": [{"duration": 120}],
        }, **overrides,
    }


def make_client(*payloads):
    session = Mock(headers={})
    session.get.side_effect = [Mock(status_code=200, json=Mock(return_value=p)) for p in payloads]
    return Audiobookshelf("https://audio.example.com/abs/", "secret", "library", session=session)


def library():
    return {"id": "library", "mediaType": "book"}


def test_reads_paginated_audio_and_preserves_work_identity(monkeypatch):
    first, second = item(), item("item-2")
    second["media"]["metadata"]["authors"] = [{"name": "Le Guin, Ursula K."}]
    client = make_client(library(), {"results": [first], "total": 2},
                         {"results": [second], "total": 2}, first, second)
    monkeypatch.setattr(client, "PAGE_SIZE", 1)
    books = client.get_books()
    assert len(books) == 2
    assert any(book.authors == ["Le Guin, Ursula K."] for book in books)
    assert all(book.isbn == [] and book.identifiers == {"hardcover": ["42"]} for book in books)
    assert client.session.headers == {"Authorization": "Bearer secret"}
    calls = client.session.get.call_args_list
    assert calls[0].args[0] == "https://audio.example.com/abs/api/libraries/library"
    assert [call.kwargs["params"]["page"] for call in calls[1:3]] == [0, 1]
    assert all(
        call.kwargs["timeout"] == 30 and not call.kwargs["allow_redirects"] for call in calls
    )


@pytest.mark.parametrize("overrides", [
    {"isMissing": True}, {"isInvalid": True},
    {"media": {"numTracks": 0, "numAudioFiles": 3, "ebookFormat": "epub"}},
])
def test_unusable_items_never_satisfy_audio_requests(overrides):
    client = make_client(library(), {"results": [item(**overrides)], "total": 1})
    assert client.get_books() == set()
    assert client.session.get.call_count == 2


@pytest.mark.parametrize("tracks", [[], [{"duration": 0}], [{"duration": -1}],
                                    [{"duration": float("nan")}], [{"duration": True}],
                                    [{"duration": 20, "exclude": True}]])
def test_expanded_item_requires_playable_tracks(tracks):
    detail = item()
    detail["media"]["tracks"] = tracks
    client = make_client(library(), {"results": [item()], "total": 1}, detail)
    assert client.get_books() == set()


@pytest.mark.parametrize("status", [301, 401, 403, 404, 500])
def test_http_errors_are_not_empty_libraries_and_do_not_expose_credentials(status):
    client = make_client()
    client.session.get.side_effect = None
    client.session.get.return_value = Mock(status_code=status, text="secret")
    with pytest.raises(AudiobookshelfError, match=f"HTTP {status}") as error:
        client.get_books()
    assert "secret" not in str(error.value)


def test_transport_error_does_not_expose_request_credentials():
    client = make_client()
    client.session.get.side_effect = requests.ConnectionError("Authorization: Bearer secret")
    with pytest.raises(AudiobookshelfError) as error:
        client.get_books()
    assert "secret" not in str(error.value)


@pytest.mark.parametrize("payloads", [
    [library(), {"results": [], "total": 1}],
    [library(), {"results": [item()], "total": 0}],
    [library(), {"results": [item()], "total": 2}, {"results": [item()], "total": 2}],
    [library(), {"results": [item()], "total": 2}, {"results": [], "total": 3}],
    [library(), {"results": [], "total": True}],
    [library(), {"results": "wrong", "total": 0}],
    [library(), {"results": [{}], "total": 1}],
    [{"id": "library", "mediaType": "podcast"}],
    [{"id": "other", "mediaType": "book"}],
    [None],
])
def test_bad_responses_and_inconsistent_pagination_fail(payloads):
    with pytest.raises(AudiobookshelfError):
        make_client(*payloads).get_books()


def test_invalid_json_is_a_library_error():
    client = make_client(library())
    client.session.get.side_effect = [Mock(status_code=200, json=Mock(side_effect=ValueError))]
    with pytest.raises(AudiobookshelfError, match="invalid JSON"):
        client.get_books()


@pytest.mark.parametrize("change", [
    {"isMissing": None}, {"libraryId": "another"}, {"media": {}}, {"media": {"numTracks": True}},
])
def test_missing_or_invalid_item_contract_raises(change):
    with pytest.raises(AudiobookshelfError):
        make_client(library(), {"results": [item(**change)], "total": 1}).get_books()


def test_audio_presence_uses_hardcover_work_tag_without_reusing_edition_identifiers():
    audio = item()
    audio["media"]["metadata"]["title"] = "Dune: The Desert Planet"
    client = make_client(library(), {"results": [audio], "total": 1}, audio)
    backend = AudiobookshelfLibrary(client)
    wanted = Book("Dune", ["Frank Herbert"], 42, ["different-ebook-isbn"], "hardcover")
    assert backend.contains_book(wanted, BookMatcher())
    client.session.get.reset_mock()
    with pytest.raises(LibraryError, match="requires a configured shared library_path"):
        backend.import_book(wanted, "/downloads/book", BookMatcher())
    client.session.get.assert_not_called()


def test_audio_without_work_tag_can_match_by_title_and_authors():
    audio = item()
    audio["media"]["tags"] = []
    client = make_client(library(), {"results": [audio], "total": 1}, audio)
    wanted = Book("Dune", ["Frank Herbert"], 42, [], "hardcover")
    assert AudiobookshelfLibrary(client).contains_book(wanted, BookMatcher())


@pytest.mark.parametrize("sequence,expected", [
    ("2", 2.0), (0, 0.0), ("0", 0.0), ("0.5", 0.5), (None, None),
    ("", None), ("un-numbered", None), (True, None), ("NaN", None), (float("inf"), None),
])
def test_audio_mapping_preserves_series_and_numeric_positions(sequence, expected):
    audio = item()
    audio["media"]["metadata"]["series"] = [
        {"id": "series-id", "name": "Collected Stories", "sequence": sequence},
    ]
    client = make_client(library(), {"results": [audio], "total": 1}, audio)
    mapped = next(iter(client.get_books()))
    assert mapped.series == "Collected Stories"
    assert mapped.series_number == expected


@pytest.mark.parametrize("position,present", [(1, False), (2, True)])
@pytest.mark.parametrize("operation", ["presence", "missing"])
def test_audio_volumes_with_identical_titles_keep_series_distinctions(position, present, operation):
    audio = item()
    audio["media"]["tags"] = []
    audio["media"]["metadata"]["title"] = "Collected Stories"
    audio["media"]["metadata"]["series"] = [
        {"id": "series-id", "name": "Collected Stories", "sequence": "2"},
    ]
    backend = AudiobookshelfLibrary(make_client(
        library(), {"results": [audio], "total": 1}, audio,
    ))
    wanted = Book("Collected Stories", ["Frank Herbert"], 42, [], "hardcover",
                  series="Collected Stories", series_number=position)
    if operation == "presence":
        assert backend.contains_book(wanted, BookMatcher()) is present
    else:
        request = BookRequest(wanted, "audiobook")
        factory = SimpleNamespace(wanted_requests=lambda: {request}, library=lambda media: backend)
        assert SyncService(factory).get_wanted_requests(BookMatcher()) == (
            set() if present else {request}
        )


def test_ebook_isbn_and_asin_cannot_match_unrelated_audio():
    audio = deepcopy(item())
    audio["media"]["tags"] = []
    audio["media"]["metadata"]["title"] = "Another work"
    wanted = Book("Dune", ["Frank Herbert"], 42, ["9780441172719"], "hardcover",
                  identifiers={"amazon": "edition-asin"})
    backend = AudiobookshelfLibrary(make_client(
        library(), {"results": [audio], "total": 1}, audio,
    ))
    assert backend.contains_book(wanted, BookMatcher()) is False


def verification_data():
    manifest = {
        "hardcover_id": "42",
        "folder_id": "folder",
        "destination": "Author/Dune",
        "files": [
            {"path": "CD1/01.mp3", "size": 10, "audio": True},
            {"path": "CD2/01.mp3", "size": 20, "audio": True},
        ],
    }
    audio = item(folderId="folder", relPath="Author/Dune")
    audio["media"]["numTracks"] = 2
    audio["media"]["tracks"] = [
        {
            "duration": 120,
            "metadata": {
                "relPath": entry["path"],
                "size": entry["size"],
                "path": "/different-server-mount/" + entry["path"],
            },
        }
        for entry in manifest["files"]
    ]
    return manifest, audio


def test_import_verifies_all_disc_relative_paths_sizes_and_identity():
    manifest, audio = verification_data()
    client = make_client(library(), {"results": [audio], "total": 1}, audio)
    assert client.verify_import(manifest)


@pytest.mark.parametrize(
    "change",
    [
        "missing-track",
        "wrong-disc",
        "wrong-size",
        "bad-duration",
        "excluded",
        "no-tag",
        "duplicate-track",
        "wrong-count",
        "ebook-only",
    ],
)
def test_incomplete_or_wrong_import_is_not_verified(change):
    manifest, audio = verification_data()
    listed = deepcopy(audio)
    media = audio["media"]
    if change == "missing-track":
        media["tracks"].pop()
    elif change == "wrong-disc":
        media["tracks"][0]["metadata"]["relPath"] = "01.mp3"
    elif change == "wrong-size":
        media["tracks"][0]["metadata"]["size"] = 999
    elif change == "bad-duration":
        media["tracks"][0]["duration"] = float("nan")
    elif change == "excluded":
        media["tracks"][0]["exclude"] = True
    elif change == "no-tag":
        media["tags"] = []
    elif change == "duplicate-track":
        media["tracks"][1] = deepcopy(media["tracks"][0])
    elif change == "wrong-count":
        media["numTracks"] = 1
    else:
        media["numTracks"] = 0
    client = make_client(library(), {"results": [listed], "total": 1}, audio)
    assert not client.verify_import(manifest)


@pytest.mark.parametrize("change", [{"folderId": "other"}, {"relPath": "Other/Dune"}])
def test_same_title_at_another_destination_cannot_verify_import(change):
    manifest, audio = verification_data()
    audio.update(change)
    client = make_client(library(), {"results": [audio], "total": 1})
    assert not client.verify_import(manifest)
    assert client.session.get.call_count == 2


def test_scan_acceptance_does_not_require_json_or_imply_verification():
    client = make_client()
    client.session.post.return_value = Mock(status_code=200)
    client.scan_library()
    client.session.post.assert_called_once_with(
        "https://audio.example.com/abs/api/libraries/library/scan",
        timeout=30,
        allow_redirects=False,
    )
    client.session.post.return_value.json.assert_not_called()


@pytest.mark.parametrize("status", [301, 401, 403, 500])
def test_scan_failures_do_not_expose_credentials(status):
    client = make_client()
    client.session.post.return_value = Mock(status_code=status, text="secret")
    with pytest.raises(AudiobookshelfError, match=f"HTTP {status}") as error:
        client.scan_library()
    assert "secret" not in str(error.value)


def test_verification_deadline_bounds_each_request(monkeypatch):
    monkeypatch.setattr("murid.clients.audiobookshelf.time.monotonic", lambda: 100)
    manifest, audio = verification_data()
    client = make_client(library(), {"results": [audio], "total": 1}, audio)
    assert client.verify_import(manifest, deadline=101)
    assert all(call.kwargs["timeout"] == 1 for call in client.session.get.call_args_list)
    client.session.get.reset_mock()
    with pytest.raises(AudiobookshelfError, match="deadline expired"):
        client.verify_import(manifest, deadline=100)
    client.session.get.assert_not_called()
