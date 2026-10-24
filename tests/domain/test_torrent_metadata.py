"""Torrent identity stays recoverable without changing download hashes or tracker data."""

import hashlib
from types import SimpleNamespace

import pytest

from murid.domain.torrent_metadata import TorrentMetainfo
from murid.domain.torrent_request import read_request, read_request_comment, write_request_comment


@pytest.mark.parametrize("media", ["ebook", "audiobook"])
def test_comment_round_trip_preserves_original_and_is_idempotent(media):
    original = "Original MaM comment\r\nMID=123\nCopyright notice\n"
    comment = write_request_comment(original, (media, 42))
    assert comment.startswith(original)
    assert read_request_comment(comment) == (media, 42)
    assert write_request_comment(comment, (media, 42)) == comment


@pytest.mark.parametrize(
    "comment",
    [
        "[murid:1]{}",
        '[murid:2]{"media_type":"ebook","hardcover_id":42}',
        '[murid:1]{"media_type":"audio","hardcover_id":42}',
        '[murid:1]{"media_type":"audiobook","hardcover_id":null}',
        '[murid:1]{"media_type":[],"hardcover_id":42}',
        '[murid:1]{"media_type":"ebook","hardcover_id":true}',
        '[murid:1]{"media_type":"ebook","hardcover_id":"42"}',
        '[murid:1]{"media_type":"ebook","hardcover_id":0}',
        '[murid:1]{"media_type":"ebook","hardcover_id":42,"extra":1}',
        "[murid:1]not json",
        "[murid:1][]",
        "[murid:1]null",
        "[murid:1]{}\n[murid:1]{}",
    ],
)
def test_invalid_comment_metadata_never_falls_back_to_ebook(comment):
    with pytest.raises(ValueError):
        read_request(SimpleNamespace(comment=comment, tags="murid,murid_hardcover_42"))


@pytest.mark.parametrize(
    "tags",
    [
        "murid",
        "murid,murid_media_audiobook",
        "murid,murid_hardcover_42",
        "murid,murid_media_audiobook,murid_hardcover_42",
    ],
)
def test_partially_removed_legacy_tags_use_verified_comment(tags):
    torrent = SimpleNamespace(
        tags=tags, comment=write_request_comment("MID=123", ("audiobook", 42))
    )
    assert read_request(torrent) == ("audiobook", 42)


@pytest.mark.parametrize(
    "tags",
    [
        "murid_media_ebook",
        "murid_hardcover_43",
        "murid_media_video",
        "murid_hardcover_bad",
    ],
)
def test_conflicting_legacy_identity_is_rejected(tags):
    torrent = SimpleNamespace(tags=tags, comment=write_request_comment("", ("audiobook", 42)))
    with pytest.raises(ValueError):
        read_request(torrent)


def test_comment_cannot_overwrite_another_request():
    with pytest.raises(ValueError, match="conflicting"):
        write_request_comment(write_request_comment("MID=123", ("ebook", 42)), ("ebook", 43))


def test_metainfo_preserves_info_hash_and_every_other_outer_value(torrent_file):
    original = TorrentMetainfo(torrent_file)
    edited_bytes = original.with_identity(("ebook", 42))
    edited = TorrentMetainfo(edited_bytes)
    expected_hash = hashlib.sha1(original.values[b"info"]).hexdigest()
    assert original.hashes == edited.hashes == [expected_hash]
    assert {key: value for key, value in original.values.items() if key != b"comment"} == {
        key: value for key, value in edited.values.items() if key != b"comment"
    }
    assert edited.with_identity(("ebook", 42)) == edited_bytes


@pytest.mark.parametrize("hybrid", [True, False])
def test_v2_and_hybrid_hashes_and_piece_layers_survive_comment_edit(hybrid):
    pieces = b"6:pieces20:aaaaaaaaaaaaaaaaaaaa" if hybrid else b""
    info = b"d9:file treede12:meta versioni2e4:name4:Dune12:piece lengthi16384e" + pieces + b"e"
    data = b"d4:info" + info + b"12:piece layersdee"
    original = TorrentMetainfo(data)
    edited = TorrentMetainfo(original.with_identity(("audiobook", 42)))
    expected = [hashlib.sha256(info).hexdigest()[:40]]
    if hybrid:
        expected.insert(0, hashlib.sha1(info).hexdigest())
    assert original.hashes == edited.hashes == expected
    assert edited.values[b"piece layers"] == b"de"
    assert edited.values[b"info"] == info


def test_utf8_comment_precedence_is_preserved(torrent_file):
    data = torrent_file.replace(b"7:comment7:MID=123", b"7:comment3:old13:comment.utf-87:MID=123")
    edited = TorrentMetainfo(TorrentMetainfo(data).with_identity(("ebook", 42)))
    assert edited.comment.startswith("MID=123\n")
    assert edited.values[b"comment"] == edited.values[b"comment.utf-8"]


@pytest.mark.parametrize(
    "data",
    [
        b"",
        b"not a torrent",
        b"de",
        b"le",
        b"d4:infod6:lengthi01eee",
        b"d4:infodeejunk",
        b"d4:infode4:infodee",
        b"d4:infod4:name99:truncatedee",
        b"d4:infod4:name1:x6:lengthi1eee",
        b"d4:infol1:xe",
        b"d7:commenti1e4:infodee",
        b"d4:infod1:x" + b"l" * 110,
    ],
)
def test_malformed_metainfo_fails_before_upload(data):
    with pytest.raises(ValueError):
        TorrentMetainfo(data)
