"""Offline external boundaries; Murid's CLI, clients, and services remain real."""

import json
import logging
import subprocess
import sys
import time
from functools import partial
from pathlib import Path
from types import SimpleNamespace

import pytest
import requests
import yaml

from murid import ui
from murid.clients.calibre import Calibre
from murid.clients.myanonamouse import MyAnonamouse
from murid.main import main


class FakeQbittorrentAPI:
    """Share download and tag state across clients created by ServiceFactory."""

    app = SimpleNamespace(version="5.0", web_api_version="2.11")

    def __init__(self, downloads):
        self.downloads = downloads
        self.torrents = []
        self.added_files = []

    def auth_log_in(self):
        pass

    def auth_log_out(self):
        pass

    def torrents_add(self, *, torrent_files, category, tags):
        self.added_files.append(torrent_files)
        self.torrents.append(
            SimpleNamespace(
                hash="test-hash",
                name="Dune",
                state="uploading",
                category=category,
                tags=tags,
                progress=1.0,
                content_path=f"/remote/downloads/{self.downloads.name}",
                comment="https://www.myanonamouse.net/t/101 MID=101",
            )
        )
        return "Ok."

    def torrents_info(self, *, category=None, tag=None, torrent_hashes=None):
        return [
            torrent
            for torrent in self.torrents
            if (category is None or torrent.category == category)
            and (tag is None or tag in torrent.tags.split(","))
            and (torrent_hashes is None or torrent.hash == torrent_hashes)
        ]

    def torrents_add_tags(self, *, tags, torrent_hashes):
        for torrent in self.torrents_info(torrent_hashes=torrent_hashes):
            torrent.tags = ",".join(sorted(set(torrent.tags.split(",")) | {tags}))

    def torrents_remove_tags(self, *, tags, torrent_hashes):
        for torrent in self.torrents_info(torrent_hashes=torrent_hashes):
            torrent.tags = ",".join(tag for tag in torrent.tags.split(",") if tag != tags)


@pytest.fixture
def workflow(tmp_path, monkeypatch, capsys):
    library = tmp_path / "library with spaces"
    library.mkdir()
    database = library / "books.json"
    database.write_text("[]")
    downloads = tmp_path / "downloads" / "Dune"
    downloads.mkdir(parents=True)
    (downloads / "Dune.epub").write_bytes(b"fixture ebook")
    (downloads / "Dune.mobi").write_bytes(b"fixture alternate format")
    (downloads / "README.txt").write_text("not an ebook")

    script = Path(__file__).with_name("fake_calibredb.py")

    def run_calibredb(command, **kwargs):
        # Keep real subprocess execution without an OS-specific shell launcher.
        return subprocess.run([command[0], str(script), *command[1:]], **kwargs)

    monkeypatch.setattr(
        "murid.services.service_factory.Calibre", partial(Calibre, run=run_calibredb)
    )
    config = {
        "hardcover_api_keys": ["Bearer integration-token"],
        "mam_id": "integration-cookie",
        "calibre": {"calibredb_executable": sys.executable, "library": str(library)},
        "qbittorrent": {
            "host": "http://qbittorrent.invalid",
            "port": 8080,
            "username": "integration",
            "password": "integration",
            "mapping": {
                "qbit_path": "/remote/downloads",
                "murid_path": str(downloads.parent),
            },
        },
        "filetypes": ["epub", "mobi"],
    }
    config_file = tmp_path / "config.yaml"
    api = FakeQbittorrentAPI(downloads)
    state = SimpleNamespace(
        config=config,
        config_file=config_file,
        library=library,
        database=database,
        downloads=downloads,
        api=api,
        requests=[],
        hardcover_error=False,
        audio_items=[],
        audio_library_path=tmp_path / "audio-library",
        audio_auto_scan=True,
        audio_scans=0,
        audio_status=200,
        notifications=[],
        notification_status=200,
        torrent_rows=[
            {
                "id": 101,
                "title": "Dune",
                "author_info": '{"1": "Frank Herbert"}',
                "lang_code": "ENG",
                "filetypes": "epub mobi",
                "seeders": 10,
                "size": "1 MB",
                "dl": "fixture-download-hash",
            }
        ],
    )

    def request(_session, method, url, **kwargs):
        state.requests.append((method, url, kwargs))
        response = requests.Response()
        response.status_code = 200
        response.url = url
        if url == "https://api.hardcover.app/v1/graphql":
            assert kwargs["headers"]["Authorization"] == "Bearer integration-token"
            if state.hardcover_error:
                data = {"errors": [{"message": "reading list unavailable"}]}
            elif "GetListBooks" in kwargs["json"]["query"]:
                assert kwargs["json"]["variables"]["slug"] in {"download-queue", "audiobooks"}
                assert kwargs["json"]["variables"]["user_id"] == 1
                data = {
                    "data": {
                        "lists": [
                            {
                                "list_books": [
                                    {
                                        "book": {
                                            "id": 42,
                                            "title": "Dune",
                                            "contributions": [
                                                {"author": {"name": "Frank Herbert"}}
                                            ],
                                        }
                                    }
                                ]
                            }
                        ]
                    }
                }
            elif "GetBook(" in kwargs["json"]["query"]:
                data = {
                    "data": {
                        "books": [
                            {
                                "id": kwargs["json"]["variables"]["book_id"],
                                "title": "Dune",
                                "contributions": [{"author": {"name": "Frank Herbert"}}],
                            }
                        ]
                    }
                }
            elif "GetUserBooks" in kwargs["json"]["query"]:
                data = {
                    "data": {
                        "user_books": [
                            {
                                "book": {
                                    "id": 42,
                                    "title": "Dune",
                                    "contributions": [{"author": {"name": "Frank Herbert"}}],
                                }
                            }
                        ]
                    }
                }
            else:
                data = {"data": {"me": [{"id": 1, "name": "Integration Reader"}]}}
        elif url.startswith("https://audio.example.com/"):
            assert _session.headers["Authorization"] == "Bearer private-audio-key"
            response.status_code = state.audio_status
            library_data = {
                "id": "audio-id",
                "mediaType": "book",
                "folders": [{"id": "folder", "fullPath": "/server/books"}],
            }
            if url.endswith("/api/libraries/audio-id/scan"):
                assert method.lower() == "post"
                state.audio_scans += 1
                if state.audio_auto_scan and state.audio_status == 200:
                    state.audio_items = []
                    for marker in state.audio_library_path.rglob(".murid-import.json"):
                        folder = marker.parent
                        metadata = json.loads((folder / "metadata.json").read_text())
                        tracks = [
                            {
                                "duration": 120,
                                "metadata": {
                                    "relPath": entry["path"],
                                    "size": entry["size"],
                                },
                            }
                            for entry in json.loads(marker.read_text())["audio_files"]
                        ]
                        state.audio_items.append(
                            {
                                "id": "imported-item",
                                "libraryId": "audio-id",
                                "folderId": "folder",
                                "relPath": folder.relative_to(state.audio_library_path).as_posix(),
                                "mediaType": "book",
                                "isMissing": False,
                                "isInvalid": False,
                                "media": {
                                    "numTracks": len(tracks),
                                    "tracks": tracks,
                                    "tags": metadata["tags"],
                                    "metadata": {
                                        "title": metadata["title"],
                                        "authors": [{"name": name} for name in metadata["authors"]],
                                    },
                                },
                            }
                        )
                data = {}
            else:
                assert method.lower() == "get"
                if url.endswith("/status"):
                    data = {"serverVersion": "2.37.1"}
                elif url.endswith("/api/me"):
                    data = {"type": "admin", "isActive": True}
                elif url.endswith("/api/libraries"):
                    data = {"libraries": [library_data]}
                elif url.endswith("/api/libraries/audio-id"):
                    data = library_data
                elif url.endswith("/api/libraries/audio-id/items"):
                    assert kwargs["params"]["page"] == 0
                    data = {"results": state.audio_items, "total": len(state.audio_items)}
                else:
                    data = next(
                        item for item in state.audio_items if url.endswith("/" + item["id"])
                    )
        elif url == MyAnonamouse.SEARCH_URL:
            assert _session.cookies.get("mam_id") == "integration-cookie"
            data = {"data": state.torrent_rows}
        elif url == f"{MyAnonamouse.DOWNLOAD_URL}/?tid=101":
            response._content = b"fixture torrent bytes"
            return response
        elif url == "http://notifications.invalid/notify":
            state.notifications.append(json.loads(kwargs["data"]))
            response.status_code = state.notification_status
            response._content = b""
            return response
        else:
            raise AssertionError(f"Unexpected external request: {method} {url}")
        response._content = json.dumps(data).encode()
        return response

    monkeypatch.setattr(requests.Session, "request", request)
    monkeypatch.setattr("murid.services.service_factory.qbittorrentapi.Client", lambda **_: api)
    monkeypatch.setattr(MyAnonamouse, "_MIN_REQUEST_INTERVAL", 0)
    monkeypatch.setattr(time, "sleep", lambda _: None)
    # main configures process-wide output and logging; restore them after each test.
    logger = logging.getLogger("murid")
    monkeypatch.setattr(logger, "handlers", [])
    monkeypatch.setattr(logger, "level", logger.level)
    monkeypatch.setattr(ui, "OUTPUT_FORMAT", ui.OUTPUT_FORMAT)
    monkeypatch.setattr(ui, "console", ui.console)
    monkeypatch.delenv("JOURNAL_STREAM", raising=False)

    def run(*args):
        config_file.write_text(yaml.safe_dump(config))
        monkeypatch.setattr(
            sys, "argv", ["murid", *args, "--config", str(config_file), "--format", "json"]
        )
        code = main()
        captured = capsys.readouterr()
        return SimpleNamespace(
            code=code,
            records=[json.loads(line) for line in captured.out.splitlines()],
            errors=[json.loads(line) for line in captured.err.splitlines()],
        )

    state.run = run
    return state
