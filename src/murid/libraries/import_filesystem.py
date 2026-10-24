"""Filesystem primitives for durable audiobook staging and exclusive publication."""

import ctypes
import importlib
import json
import os
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path

from .library import LibraryError


@contextmanager
def import_lock(path: Path):
    """Keep the lock inode stable; OS locks release automatically after a crash."""
    module = importlib.import_module("msvcrt" if os.name == "nt" else "fcntl")
    with path.open("a+b") as stream:
        if os.name == "nt":
            if path.stat().st_size == 0:
                stream.write(b"\0")
                stream.flush()
            stream.seek(0)
        try:
            if os.name == "nt":
                module.locking(stream.fileno(), module.LK_NBLCK, 1)
            else:
                module.flock(stream.fileno(), module.LOCK_EX | module.LOCK_NB)
        except OSError:
            raise LibraryError("This audiobook import is already active; retry later") from None
        try:
            yield
        finally:
            if os.name == "nt":
                stream.seek(0)
                module.locking(stream.fileno(), module.LK_UNLCK, 1)
            else:
                module.flock(stream.fileno(), module.LOCK_UN)


@contextmanager
def atomic_write(
    path: Path,
    *,
    mode: int = 0o600,
    binary: bool = False,
    prefix: str = ".murid-",
    suffix: str = "",
):
    """Publish a flushed temporary file only after its writer finishes successfully."""
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w+b" if binary else "w",
            encoding=None if binary else "utf-8",
            dir=path.parent,
            prefix=prefix,
            suffix=suffix,
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            yield stream
            stream.flush()
            os.chmod(temporary, mode)
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        sync_directory(path.parent)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def write_json(path: Path, payload: dict, *, mode: int = 0o600) -> None:
    """Replace our own journal/metadata atomically, after flushing its contents."""
    with atomic_write(path, mode=mode) as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2)


def sync_directory(path: Path) -> None:
    """Flush directory entries on POSIX after journal updates and publication."""
    if os.name != "nt":
        descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def durable_mkdir(path: Path) -> None:
    """Persist each new ancestor before creating children, including on retries."""
    missing = []
    ancestor = path
    while not ancestor.exists():
        missing.append(ancestor)
        ancestor = ancestor.parent
    if not ancestor.is_dir():
        raise NotADirectoryError(str(ancestor))
    # A previous attempt may have created this ancestor but failed to sync its entry.
    sync_directory(ancestor.parent)
    for directory in reversed(missing):
        directory.mkdir(exist_ok=True)
        sync_directory(directory.parent)


def publish_directory(source: Path, destination: Path) -> None:
    """Atomically rename without replacing even an empty destination directory."""
    if os.name == "nt":
        os.rename(source, destination)  # Windows rename refuses any existing destination.
        return
    libc = ctypes.CDLL(None, use_errno=True)
    if sys.platform.startswith("linux") and hasattr(libc, "renameat2"):
        rename = libc.renameat2
        rename.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        rename.restype = ctypes.c_int
        result = rename(-100, os.fsencode(source), -100, os.fsencode(destination), 1)
    elif sys.platform == "darwin" and hasattr(libc, "renamex_np"):
        rename = libc.renamex_np
        rename.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
        rename.restype = ctypes.c_int
        result = rename(os.fsencode(source), os.fsencode(destination), 4)
    else:
        raise LibraryError("This platform does not support atomic, non-replacing audiobook imports")
    if result != 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error), str(destination))
    sync_directory(destination.parent)
    sync_directory(source.parent)


def ensure_shared_directory(destination: Path, staging: Path) -> None:
    """Initialize permissions privately so an interrupted mkdir cannot expose mode 0700."""
    if destination.is_symlink() or staging.is_symlink():
        raise LibraryError("Shared directory and its staging path cannot be symlinks")
    if destination.exists():
        durable_mkdir(destination)
        return
    staging.mkdir(exist_ok=True)
    if any(staging.iterdir()):
        raise LibraryError("Unexpected author staging content; inspect it before retrying")
    staging.chmod(0o755)
    sync_directory(staging)
    try:
        publish_directory(staging, destination)
    except FileExistsError:
        # Another work may have created this author while we prepared our empty directory.
        staging.rmdir()
        if destination.is_symlink():
            raise LibraryError("Shared directory cannot be a symlink") from None
        durable_mkdir(destination)
