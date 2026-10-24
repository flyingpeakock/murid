"""Shared valid metainfo and a stateful qBittorrent boundary for recovery tests."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from murid.domain.torrent_metadata import TorrentMetainfo


@pytest.fixture
def torrent_file():
    return (
        b"d7:comment7:MID=1234:infod6:lengthi1e4:name4:Dune"
        b"12:piece lengthi16384e6:pieces20:aaaaaaaaaaaaaaaaaaaaee"
    )


@pytest.fixture
def qbit_api():
    api = Mock()
    api.app.version = "5.2.0"
    api.app.web_api_version = "2.12.1"
    api.items = []
    api.tag_definitions = set()

    def info(*, category=None, tag=None, torrent_hashes=None):
        return [
            item
            for item in api.items
            if (
                (category is None or item.category == category)
                and (tag is None or tag in item.tags.split(","))
                and (torrent_hashes is None or item.hash in torrent_hashes.split("|"))
            )
        ]

    def add(*, torrent_files, category, tags):
        metainfo = TorrentMetainfo(torrent_files)
        api.items.append(
            SimpleNamespace(
                hash=metainfo.hashes[0],
                comment=metainfo.comment,
                category=category,
                tags=tags,
                progress=1,
                content_path="/downloads/Dune",
                name="Dune",
                state="uploading",
            )
        )
        api.tag_definitions.update(tags.split(","))
        return "Ok."

    def add_tags(*, tags, torrent_hashes):
        api.tag_definitions.update(tags.split(","))
        for item in info(torrent_hashes=torrent_hashes):
            item.tags = ",".join(sorted(set(item.tags.split(",")) | set(tags.split(","))))

    def remove_tags(*, tags, torrent_hashes):
        for item in info(torrent_hashes=torrent_hashes):
            item.tags = ",".join(tag for tag in item.tags.split(",") if tag not in tags.split(","))

    def set_comment(*, comment, torrent_hashes):
        for item in info(torrent_hashes=torrent_hashes):
            item.comment = comment.strip()

    api.torrents_info.side_effect = info
    api.torrents_add.side_effect = add
    api.torrents_add_tags.side_effect = add_tags
    api.torrents_remove_tags.side_effect = remove_tags
    api.torrents_set_comment.side_effect = set_comment
    api.torrents_properties.side_effect = lambda *, torrent_hash: SimpleNamespace(
        comment=getattr(info(torrent_hashes=torrent_hash)[0], "comment", "")
    )
    api.torrents_tags.side_effect = lambda: sorted(api.tag_definitions)
    api.torrents_delete_tags.side_effect = lambda *, tags: api.tag_definitions.difference_update(
        tags.split(",")
    )
    return api
