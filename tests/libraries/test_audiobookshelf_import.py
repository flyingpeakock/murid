import json
import os
from dataclasses import replace
from unittest.mock import Mock

import pytest

from murid.clients.audiobookshelf import AudiobookshelfError
from murid.domain.book import Book
from murid.domain.book_matcher import BookMatcher
from murid.libraries.audiobook_store import AudiobookStore
from murid.libraries.audiobookshelf import AudiobookLibraryConfig, AudiobookshelfLibrary
from murid.libraries.import_filesystem import publish_directory
from murid.libraries.library import LibraryError, LibraryImportPending


@pytest.fixture
def work(tmp_path, monkeypatch):
    library = tmp_path / "library"
    library.mkdir()
    source = tmp_path / "downloads" / "Dune"
    source.mkdir(parents=True)
    (source / "01.mp3").write_bytes(b"first audio track")
    (source / "02.mp3").write_bytes(b"second audio track")
    (source / "cover.jpg").write_bytes(b"cover")
    book = Book(
        "Dune", ["Frank Herbert"], 42, ["ebook-isbn"], "hardcover", series="Dune", series_number=0
    )
    folder = {"id": "folder", "fullPath": "/server/books"}
    client = Mock(library_id="library")
    client.get_library.return_value = {"id": "library", "folders": [folder]}
    client.get_libraries.return_value = [client.get_library.return_value]
    state = {"ingested": False, "auto_scan": True, "time": 0}
    client.verify_import.side_effect = lambda *args, **kwargs: state["ingested"]

    def scan(**kwargs):
        if state["auto_scan"]:
            state["ingested"] = True

    client.scan_library.side_effect = scan
    monkeypatch.setattr("murid.libraries.audiobookshelf.time.monotonic", lambda: state["time"])
    monkeypatch.setattr(
        "murid.libraries.audiobookshelf.time.sleep",
        lambda seconds: state.update(time=state["time"] + seconds),
    )
    config = AudiobookLibraryConfig(str(library), str(tmp_path / "staging"), scan_timeout_seconds=3)
    backend = AudiobookshelfLibrary(client, config)
    store = AudiobookStore(str(library), "library", config.staging_path)
    return book, source, backend, store, state


def run(work, **kwargs):
    book, source, backend, _, _ = work
    backend.import_book(book, str(source), BookMatcher(), **kwargs)


def manifest(work):
    book, _, _, store, _ = work
    return json.loads(store._journal(book).read_text())


def destination(work):
    return work[3].library / manifest(work)["destination"]


def test_complete_audio_copy_preserves_source_tracks_sidecars_and_metadata(work):
    book, source, backend, store, _ = work
    original = {p.name: p.read_bytes() for p in source.iterdir()}
    run(work)
    target = destination(work)
    assert manifest(work)["phase"] == "verified"
    assert {p.name: p.read_bytes() for p in source.iterdir()} == original
    for name, content in original.items():
        assert (target / name).read_bytes() == content
    metadata = json.loads((target / "metadata.json").read_text())
    assert metadata["tags"] == ["murid:hardcover:42"]
    assert metadata["series"] == ["Dune #0"]
    assert "isbn" not in metadata and "asin" not in metadata
    assert not list(store.staging.glob("*.partial"))
    backend.client.scan_library.assert_called_once()
    assert backend.client.verify_import.call_count == 2
    if os.name != "nt":
        assert target.stat().st_mode & 0o777 == 0o755
        assert (target / "01.mp3").stat().st_mode & 0o777 == 0o644
        assert (target / "metadata.json").stat().st_mode & 0o777 == 0o644


def test_preserves_disc_structure_and_duplicate_track_basenames(work):
    _, source, _, _, _ = work
    for index in (1, 2):
        disc = source / f"CD{index}"
        disc.mkdir()
        (source / f"0{index}.mp3").rename(disc / "01.mp3")
    run(work)
    target = destination(work)
    assert (target / "CD1/01.mp3").read_bytes() == b"first audio track"
    assert (target / "CD2/01.mp3").read_bytes() == b"second audio track"
    assert {f["path"] for f in manifest(work)["files"] if f["audio"]} == {
        "CD1/01.mp3",
        "CD2/01.mp3",
    }


def test_single_m4b_keeps_its_filename_and_sidecars(work):
    book, source, backend, store, _ = work
    audio = source / "The original filename.m4b"
    audio.write_bytes(b"audio book")
    (source / "01.mp3").unlink()
    (source / "02.mp3").unlink()
    backend.import_book(book, str(audio), BookMatcher())
    assert (destination(work) / audio.name).read_bytes() == b"audio book"
    assert (destination(work) / "cover.jpg").read_bytes() == b"cover"
    assert audio.read_bytes() == b"audio book"


def test_merges_tags_without_overwriting_supplied_audiobook_metadata(work):
    _, source, _, _, _ = work
    metadata = {
        "title": "Dune",
        "isbn": "audio-edition-isbn",
        "tags": ["original"],
        "metadata": {"tags": ["legacy"], "narrators": ["Narrator"]},
    }
    original = json.dumps(metadata)
    (source / "metadata.json").write_text(original)
    run(work)
    copied = json.loads((destination(work) / "metadata.json").read_text())
    assert copied["isbn"] == "audio-edition-isbn"
    assert copied["tags"] == ["original", "legacy", "murid:hardcover:42"]
    assert copied["metadata"]["tags"] == copied["tags"]
    assert copied["metadata"]["narrators"] == ["Narrator"]
    assert (source / "metadata.json").read_text() == original


@pytest.mark.parametrize("kind", ["book_subfolders", "mixed_formats", "unnamed_pack", "zero_track"])
def test_ambiguous_or_incomplete_sources_are_rejected(work, kind):
    _, source, _, _, _ = work
    if kind == "book_subfolders":
        (source / "Another Book").mkdir()
        (source / "02.mp3").rename(source / "Another Book/02.mp3")
    elif kind == "mixed_formats":
        (source / "extra.m4b").write_bytes(b"alternate encoding")
    elif kind == "unnamed_pack":
        (source / "01.mp3").rename(source / "Different Book.mp3")
    else:
        (source / "01.mp3").write_bytes(b"")
    with pytest.raises(LibraryError):
        run(work)
    assert not list(work[3].library.rglob("*.mp3"))
    work[2].client.scan_library.assert_not_called()


def test_dry_run_does_not_create_state_copy_or_scan(work):
    work[2].config.dry_run = True
    run(work)
    assert not work[3].staging.exists()
    assert list(work[3].library.iterdir()) == []
    work[2].client.scan_library.assert_not_called()
    work[2].client.verify_import.assert_not_called()


@pytest.mark.parametrize("empty", [False, True])
def test_existing_unrelated_destinations_are_preserved(work, empty):
    book, source, backend, store, _ = work
    planned = store.plan(book, str(source), BookMatcher(), ["mp3"], "folder")
    target = store.library / planned["destination"]
    target.mkdir(parents=True)
    if not empty:
        (target / "unrelated.txt").write_text("keep me")
    before = list(target.iterdir())
    with pytest.raises(LibraryError, match="Unrelated content"):
        run(work)
    assert list(target.iterdir()) == before
    backend.client.scan_library.assert_not_called()


def test_atomic_publish_does_not_replace_an_empty_directory(tmp_path):
    source, target = tmp_path / "source", tmp_path / "target"
    source.mkdir()
    target.mkdir()
    (source / "audio").write_bytes(b"content")
    with pytest.raises(FileExistsError):
        publish_directory(source, target)
    assert (source / "audio").exists()
    assert list(target.iterdir()) == []


def test_interrupted_copy_reuses_completed_staged_tracks(work, monkeypatch):
    book, _, _, store, _ = work
    copy = AudiobookStore._copy
    copied = []

    def interrupt(source, target, entry):
        copied.append(entry["path"])
        if len(copied) == 2:
            raise OSError("simulated interrupted copy")
        copy(source, target, entry)

    monkeypatch.setattr(AudiobookStore, "_copy", staticmethod(interrupt))
    with pytest.raises(LibraryError, match="interrupted copy"):
        run(work)
    pending = manifest(work)
    assert pending["phase"] == "copying"
    first = store._partial(pending) / copied[0]
    timestamp = first.stat().st_mtime_ns
    monkeypatch.setattr(AudiobookStore, "_copy", staticmethod(copy))
    run(work)
    assert (destination(work) / copied[0]).stat().st_mtime_ns == timestamp
    assert manifest(work)["phase"] == "verified"


def test_delayed_scan_retries_without_source_recopy_or_new_destination(work, monkeypatch):
    book, _, backend, store, state = work
    state["auto_scan"] = False
    with pytest.raises(LibraryImportPending, match="copied but ingestion is not verified"):
        run(work)
    assert manifest(work)["phase"] == "copied"
    target = destination(work)
    original = (target / "01.mp3").stat().st_mtime_ns
    state["ingested"] = True
    monkeypatch.setattr(
        AudiobookStore, "_copy", Mock(side_effect=AssertionError("must not recopy"))
    )
    backend.import_book(replace(book, title="Changed metadata"), "/source-is-gone", BookMatcher())
    assert (target / "01.mp3").stat().st_mtime_ns == original
    assert manifest(work)["phase"] == "verified"
    assert len(list(store.library.rglob(".murid-import.json"))) == 1
    backend.client.scan_library.assert_called_once()


def test_crash_after_publish_recovers_from_the_marker(work, monkeypatch):
    _, _, backend, _, state = work
    save = AudiobookStore.save

    def interrupt(self, pending):
        if pending["phase"] == "copied":
            raise OSError("crash after atomic rename")
        save(self, pending)

    monkeypatch.setattr(AudiobookStore, "save", interrupt)
    with pytest.raises(LibraryError, match="crash after atomic rename"):
        run(work)
    assert manifest(work)["phase"] == "copying"
    target = destination(work)
    assert (target / "01.mp3").exists()
    monkeypatch.setattr(AudiobookStore, "save", save)
    monkeypatch.setattr(
        AudiobookStore, "_copy", Mock(side_effect=AssertionError("must not recopy"))
    )
    state["ingested"] = True
    work[2].import_book(work[0], "/source-is-gone", BookMatcher())
    assert manifest(work)["phase"] == "verified"


def test_second_import_uses_a_released_os_lock_and_existing_destination(work, monkeypatch):
    run(work)
    monkeypatch.setattr(
        AudiobookStore, "_copy", Mock(side_effect=AssertionError("must not recopy"))
    )
    run(work)
    work[2].client.scan_library.assert_called_once()
    assert len(list(work[3].library.rglob(".murid-import.json"))) == 1


def test_concurrent_import_is_rejected_before_copy(work):
    with work[3].lock(work[0]):
        with pytest.raises(LibraryError, match="already active"):
            run(work)
    run(work)
    assert manifest(work)["phase"] == "verified"


def test_scan_permission_failure_copies_nothing(work):
    work[2].client.require_scan_access.side_effect = AudiobookshelfError("not an admin")
    with pytest.raises(AudiobookshelfError, match="not an admin"):
        run(work)
    assert not work[3].staging.exists()
    assert not list(work[3].library.rglob("*.mp3"))


def test_multiple_roots_require_explicit_mapping(work):
    backend = work[2]
    backend.client.get_library.return_value["folders"].append({"id": "other", "fullPath": "/other"})
    with pytest.raises(LibraryError, match="folder_id"):
        run(work)
    assert not work[3].staging.exists()
    backend.config.folder_id = "folder"
    run(work)
    assert manifest(work)["folder_id"] == "folder"


def test_staging_inside_another_scanned_library_is_rejected(work):
    work[2].client.get_libraries.return_value.append(
        {"folders": [{"id": "other", "fullPath": "/"}]}
    )
    with pytest.raises(LibraryError, match="inside an Audiobookshelf scanned library"):
        run(work)
    assert not work[3].staging.exists()


def test_changed_published_audio_is_never_overwritten(work):
    run(work)
    target = destination(work) / "01.mp3"
    target.write_bytes(b"user changed this")
    with pytest.raises(LibraryError, match="Published audio changed"):
        run(work)
    assert target.read_bytes() == b"user changed this"


@pytest.mark.parametrize(
    "key,value",
    [
        ("destination", "../outside"),
        ("destination", None),
        ("destination", "/outside"),
        ("destination", "C:/outside"),
        ("source_root", "relative"),
        ("metadata", []),
    ],
)
def test_corrupt_journal_cannot_redirect_a_retry(work, key, value):
    run(work)
    pending = manifest(work)
    pending[key] = value
    work[3].save(pending)
    with pytest.raises(LibraryError, match="journal"):
        run(work)


def test_scan_failure_keeps_a_complete_recoverable_copy(work):
    work[2].client.scan_library.side_effect = AudiobookshelfError("scan unavailable")
    with pytest.raises(AudiobookshelfError, match="scan unavailable"):
        run(work)
    assert manifest(work)["phase"] == "copied"
    assert (destination(work) / "02.mp3").exists()
    work[4]["ingested"] = True
    run(work)
    assert manifest(work)["phase"] == "verified"


def test_staging_on_another_filesystem_is_rejected_before_copy(work, monkeypatch):
    from pathlib import Path
    from types import SimpleNamespace

    stat = Path.stat

    def filesystem(path, *args, **kwargs):
        result = stat(path, *args, **kwargs)
        if path == work[3].library:
            return SimpleNamespace(st_dev=result.st_dev + 1, st_mode=result.st_mode)
        return result

    monkeypatch.setattr(Path, "stat", filesystem)
    with pytest.raises(LibraryError, match="same filesystem"):
        run(work)
    assert not work[3].staging.exists()
    work[2].client.scan_library.assert_not_called()


@pytest.mark.parametrize("target_name", ["metadata.json", ".murid-import.json"])
def test_interrupted_json_write_removes_temporary_files_on_retry(work, monkeypatch, target_name):
    import tempfile

    from murid.libraries import audiobook_store

    (work[1] / ".murid-notes.txt").write_text("keep this source sidecar")
    write_json = audiobook_store.write_json
    leftover = None

    def interrupt(path, payload, **kwargs):
        nonlocal leftover
        if path.name == target_name:
            with tempfile.NamedTemporaryFile(
                dir=path.parent, prefix=".murid-", delete=False
            ) as out:
                out.write(b'{"interrupted":')
                leftover = out.name
            raise OSError("crash during JSON write")
        write_json(path, payload, **kwargs)

    monkeypatch.setattr(audiobook_store, "write_json", interrupt)
    with pytest.raises(LibraryError, match="crash during JSON write"):
        run(work)
    pending = manifest(work)
    assert pending["phase"] == "copying"
    partial = work[3]._partial(pending)
    timestamp = (partial / "01.mp3").stat().st_mtime_ns
    assert leftover is not None
    assert list(partial.glob(".murid-*"))
    monkeypatch.setattr(audiobook_store, "write_json", write_json)
    run(work)
    target = destination(work)
    assert manifest(work)["phase"] == "verified"
    assert (target / "01.mp3").stat().st_mtime_ns == timestamp
    assert (target / ".murid-notes.txt").read_text() == "keep this source sidecar"
    assert {p.name for p in target.glob(".murid-*")} == {
        ".murid-notes.txt",
        ".murid-import.json",
    }


@pytest.mark.parametrize("single_file", [False, True])
@pytest.mark.parametrize(
    "metadata,accepted",
    [
        ({"title": "Dune", "metadata": {"title": "Another Book"}}, False),
        ({"title": "Another Book", "metadata": {"title": "Dune"}}, True),
        ({"metadata": {"title": "Another Book"}}, False),
        ({"metadata": {"title": "Dune"}}, True),
        ({"title": "Dune", "metadata": {"title": "Dune"}}, True),
    ],
)
def test_sidecar_title_uses_server_nested_precedence(work, single_file, metadata, accepted):
    book, source, backend, store, _ = work
    path = source
    if single_file:
        for track in source.glob("*.mp3"):
            track.unlink()
        path = source / "Dune.m4b"
        path.write_bytes(b"complete audiobook")
    sidecar = source / "metadata.json"
    original = json.dumps(metadata)
    sidecar.write_text(original)
    if accepted:
        backend.import_book(book, str(path), BookMatcher())
        assert manifest(work)["phase"] == "verified"
        published = json.loads((destination(work) / "metadata.json").read_text())
        assert published["metadata"]["title"] == "Dune"
    else:
        with pytest.raises(LibraryError, match="metadata identifies a different book"):
            backend.import_book(book, str(path), BookMatcher())
        assert list(store.library.iterdir()) == []
        assert not list(store.staging.glob("*.json"))
        backend.client.scan_library.assert_not_called()
    assert sidecar.read_text() == original


@pytest.mark.parametrize("folder", ["CD_1", "CD-2", "Disc 1000", "CD1/Disc 2", "CD١"])
def test_server_unsupported_disc_layouts_fail_before_copy(work, folder):
    source = work[1]
    disc = source / folder
    disc.mkdir(parents=True)
    for track in source.glob("*.mp3"):
        track.rename(disc / track.name)
    with pytest.raises(LibraryError, match="Unsupported audio folders"):
        run(work)
    assert list(work[3].library.iterdir()) == []
    assert not list(work[3].staging.glob("*.json"))
    assert len(list(disc.glob("*.mp3"))) == 2
    work[2].client.scan_library.assert_not_called()


@pytest.mark.parametrize("folder", ["CD1", "Disc 2", "disk003", "cD 999"])
def test_server_supported_disc_layouts_preserve_track_paths(work, folder):
    source = work[1]
    disc = source / folder
    disc.mkdir()
    for track in source.glob("*.mp3"):
        track.rename(disc / track.name)
    run(work)
    assert manifest(work)["phase"] == "verified"
    assert (destination(work) / folder / "01.mp3").read_bytes() == b"first audio track"
    assert (destination(work) / folder / "02.mp3").read_bytes() == b"second audio track"


@pytest.mark.parametrize("source_change", ["missing", "changed"])
@pytest.mark.parametrize("interruption", ["marker", "publish"])
def test_generated_staged_metadata_resumes_without_source_sidecar(
    work, monkeypatch, source_change, interruption
):
    from murid.libraries import audiobook_store

    sidecar = work[1] / "metadata.json"
    sidecar.write_text(json.dumps({"title": "Dune", "tags": ["original"], "narrators": ["Reader"]}))
    function_name = "write_json" if interruption == "marker" else "publish_directory"
    original = getattr(audiobook_store, function_name)

    def interrupt(*args, **kwargs):
        if interruption == "publish" or args[0].name == ".murid-import.json":
            raise OSError("crash after generated metadata")
        return original(*args, **kwargs)

    monkeypatch.setattr(audiobook_store, function_name, interrupt)
    with pytest.raises(LibraryError, match="crash after generated metadata"):
        run(work)
    pending = manifest(work)
    partial = work[3]._partial(pending)
    assert json.loads((partial / "metadata.json").read_text()) == pending["metadata"]
    assert pending["phase"] == "copying"
    if source_change == "missing":
        sidecar.unlink()
    else:
        sidecar.write_text('{"title": "Another Book"}')
    monkeypatch.setattr(audiobook_store, function_name, original)
    monkeypatch.setattr(
        AudiobookStore, "_copy", Mock(side_effect=AssertionError("must not recopy"))
    )
    run(work)
    assert manifest(work)["phase"] == "verified"
    metadata = json.loads((destination(work) / "metadata.json").read_text())
    assert metadata["tags"] == ["original", "murid:hardcover:42"]
    assert metadata["narrators"] == ["Reader"]
    assert metadata == pending["metadata"]


@pytest.mark.parametrize("nested_staging", [False, True])
def test_parent_entries_are_synced_before_journaling_and_publication(
    work, monkeypatch, nested_staging
):
    from murid.libraries import audiobook_store, import_filesystem

    store = work[3]
    if nested_staging:
        store.staging = store.library.parent / "new-parent" / "nested" / "staging"
        work[2].config.staging_path = str(store.staging)
    expected = [store.staging.parent]
    if nested_staging:
        expected = [store.library.parent, store.staging.parent.parent, store.staging.parent]
    sync = import_filesystem.sync_directory
    save = AudiobookStore.save
    publish = audiobook_store.publish_directory
    synced = []

    def record_sync(path):
        sync(path)
        synced.append(path)

    def save_after_parents(self, pending):
        assert all(parent in synced for parent in expected)
        assert [synced.index(parent) for parent in expected] == sorted(
            synced.index(parent) for parent in expected
        )
        save(self, pending)

    def publish_after_parent(source, target):
        assert store.library in synced
        assert target.parent.is_dir()
        publish(source, target)

    monkeypatch.setattr(import_filesystem, "sync_directory", record_sync)
    monkeypatch.setattr(AudiobookStore, "save", save_after_parents)
    monkeypatch.setattr(audiobook_store, "publish_directory", publish_after_parent)
    run(work)
    assert manifest(work)["phase"] == "verified"


@pytest.mark.parametrize("failure", ["staging", "author"])
def test_parent_sync_failure_stops_import_and_retry_persists_existing_ancestor(
    work, monkeypatch, failure
):
    from murid.libraries import audiobook_store, import_filesystem

    store = work[3]
    if failure == "staging":
        store.staging = store.library.parent / "new-parent" / "nested" / "staging"
        work[2].config.staging_path = str(store.staging)
    failed_parent = store.library.parent if failure == "staging" else store.library
    sync = import_filesystem.sync_directory
    publish = audiobook_store.publish_directory
    failed = False
    synced_after_failure = []

    def fail_once(path):
        nonlocal failed
        if not failed and path == failed_parent:
            failed = True
            raise OSError("simulated parent fsync failure")
        sync(path)
        if failed:
            synced_after_failure.append(path)

    def publish_after_retry(source, target):
        assert failed_parent in synced_after_failure
        publish(source, target)

    publisher = Mock(side_effect=publish_after_retry)
    monkeypatch.setattr(import_filesystem, "sync_directory", fail_once)
    monkeypatch.setattr(audiobook_store, "publish_directory", publisher)
    with pytest.raises(LibraryError, match="parent fsync failure"):
        run(work)
    publisher.assert_not_called()
    work[2].client.scan_library.assert_not_called()
    if failure == "staging":
        assert not store.staging.exists()
        assert (store.library.parent / "new-parent").is_dir()
        assert not list(store.library.parent.rglob("*hardcover-42.json"))
    else:
        assert manifest(work)["phase"] == "copying"
        assert (store.library / "Frank Herbert").is_dir()
    run(work)
    assert manifest(work)["phase"] == "verified"
    publisher.assert_called_once()


@pytest.mark.skipif(os.name == "nt", reason="POSIX umask and directory permissions")
@pytest.mark.parametrize("interruption", ["permissions", "parent-sync"])
def test_author_permissions_recover_under_restrictive_umask(work, monkeypatch, interruption):
    from pathlib import Path

    from murid.libraries import import_filesystem

    store = work[3]
    author = store.library / "Frank Herbert"
    chmod = Path.chmod
    sync = import_filesystem.sync_directory
    failed = False

    def interrupt_chmod(path, mode, **kwargs):
        nonlocal failed
        if interruption == "permissions" and not failed and path.name.endswith(".author"):
            failed = True
            raise OSError("interrupted author permissions")
        chmod(path, mode, **kwargs)

    def interrupt_sync(path):
        nonlocal failed
        if interruption == "parent-sync" and not failed and path == store.library:
            failed = True
            raise OSError("interrupted author parent sync")
        sync(path)

    monkeypatch.setattr(Path, "chmod", interrupt_chmod)
    monkeypatch.setattr(import_filesystem, "sync_directory", interrupt_sync)
    previous_umask = os.umask(0o077)
    try:
        with pytest.raises(LibraryError, match="interrupted author"):
            run(work)
        assert manifest(work)["phase"] == "copying"
        work[2].client.scan_library.assert_not_called()
        if interruption == "permissions":
            assert not author.exists()
            staged_author = store.staging / (manifest(work)["key"] + ".author")
            assert staged_author.stat().st_mode & 0o777 == 0o700
        else:
            assert author.stat().st_mode & 0o777 == 0o755
        run(work)
    finally:
        os.umask(previous_umask)
    assert author.stat().st_mode & 0o777 == 0o755
    assert manifest(work)["phase"] == "verified"
    assert not list(store.staging.glob("*.author"))


@pytest.mark.skipif(os.name == "nt", reason="POSIX directory permissions")
@pytest.mark.parametrize("concurrent_creation", [False, True])
def test_existing_author_permissions_and_content_are_preserved(
    work, monkeypatch, concurrent_creation
):
    from murid.libraries import import_filesystem

    author = work[3].library / "Frank Herbert"

    def create_existing_author():
        author.mkdir()
        author.chmod(0o700)
        (author / "unrelated.txt").write_text("keep me")

    if concurrent_creation:
        publish = import_filesystem.publish_directory

        def competing_author(source, target):
            if target == author:
                create_existing_author()
            publish(source, target)

        monkeypatch.setattr(import_filesystem, "publish_directory", competing_author)
    else:
        create_existing_author()
    run(work)
    assert author.stat().st_mode & 0o777 == 0o700
    assert (author / "unrelated.txt").read_text() == "keep me"
    assert manifest(work)["phase"] == "verified"


def test_recovered_publication_syncs_parent_before_advancing_journal(work, monkeypatch):
    import shutil

    from murid.libraries import audiobook_store, import_filesystem

    author = work[3].library / "Frank Herbert"
    sync = import_filesystem.sync_directory
    save = AudiobookStore.save
    failures = 0
    parent_synced = False

    def interrupted_parent_sync(path):
        nonlocal failures, parent_synced
        if path == author and failures < 2:
            failures += 1
            raise OSError("interrupted destination parent sync")
        sync(path)
        if path == author:
            parent_synced = True

    def save_after_parent_sync(self, pending):
        if pending["phase"] in {"copied", "verified"}:
            assert parent_synced
        save(self, pending)

    monkeypatch.setattr(import_filesystem, "sync_directory", interrupted_parent_sync)
    monkeypatch.setattr(audiobook_store, "sync_directory", interrupted_parent_sync)
    monkeypatch.setattr(AudiobookStore, "save", save_after_parent_sync)
    with pytest.raises(LibraryError, match="interrupted destination parent sync"):
        run(work)
    assert manifest(work)["phase"] == "copying"
    assert (destination(work) / "01.mp3").exists()
    shutil.rmtree(work[1])
    monkeypatch.setattr(
        AudiobookStore, "_copy", Mock(side_effect=AssertionError("must not recopy"))
    )
    with pytest.raises(LibraryError, match="interrupted destination parent sync"):
        run(work)
    assert failures == 2
    assert manifest(work)["phase"] == "copying"
    work[2].client.scan_library.assert_not_called()
    run(work)
    assert parent_synced
    assert manifest(work)["phase"] == "verified"
    work[2].client.scan_library.assert_called_once()


def test_import_connection_check_is_read_only(work):
    backend = work[2]
    backend.client.server_version.return_value = "2.37.1"
    backend.client.get_books.return_value = set()
    assert "v2.37.1" in backend.check_connection()
    assert list(work[3].library.iterdir()) == []
    assert not work[3].staging.exists()
    backend.client.scan_library.assert_not_called()


def test_unwritable_staging_ancestor_fails_preflight_without_creating_state(work, monkeypatch):
    access = os.access
    monkeypatch.setattr(
        os, "access", lambda path, mode: path == work[3].library and access(path, mode)
    )
    with pytest.raises(LibraryError, match="staging_path.*writable"):
        work[2].check_connection()
    assert not work[3].staging.exists()
    work[2].client.scan_library.assert_not_called()
