"""Read metainfo and edit outer comments without re-encoding the info dictionary."""

import hashlib
import re

from .torrent_request import write_request_comment


def _decode(data: bytes, start: int = 0, depth: int = 0):
    """Decode one bencoded value and return its end offset; bound recursion."""
    if depth > 100 or start >= len(data):
        raise ValueError("Truncated or excessively nested torrent metainfo")
    token = data[start : start + 1]
    if token == b"i":
        end = data.find(b"e", start + 1)
        number = data[start + 1 : end]
        if end < 0 or not re.fullmatch(rb"0|-?[1-9][0-9]*", number):
            raise ValueError("Invalid bencoded integer")
        return int(number), end + 1
    if token in (b"l", b"d"):
        values = [] if token == b"l" else {}
        position = start + 1
        previous = None
        while data[position : position + 1] != b"e":
            value, position = _decode(data, position, depth + 1)
            if token == b"l":
                values.append(value)
            else:
                if not isinstance(value, bytes) or (previous is not None and value <= previous):
                    raise ValueError("Unsorted or duplicate torrent dictionary keys")
                previous = value
                values[value], position = _decode(data, position, depth + 1)
        return values, position + 1
    colon = data.find(b":", start)
    length = data[start:colon]
    if colon < 0 or not re.fullmatch(rb"0|[1-9][0-9]*", length):
        raise ValueError("Invalid bencoded string length")
    end = colon + 1 + int(length)
    if end > len(data):
        raise ValueError("Truncated bencoded string")
    return data[colon + 1 : end], end


def _string(value: bytes) -> bytes:
    return str(len(value)).encode("ascii") + b":" + value


class TorrentMetainfo:  # pylint: disable=too-few-public-methods
    """Retain each original top-level value, including the exact hashed info bytes."""

    def __init__(self, data: bytes):
        decoded, end = _decode(data)
        if end != len(data) or not isinstance(decoded, dict):
            raise ValueError("Torrent metainfo must contain one dictionary")
        info = decoded.get(b"info")
        if not isinstance(info, dict):
            raise ValueError("Torrent metainfo has no info dictionary")
        self.values = {}
        position = 1
        for key in decoded:
            _, position = _decode(data, position)
            start = position
            _, position = _decode(data, position)
            self.values[key] = data[start:position]
        raw_info = self.values[b"info"]
        # qBittorrent/libtorrent uses the truncated v2 hash as its ID for v2/hybrid
        # torrents, but older builds may identify hybrids by their v1 hash.
        self.hashes = []
        if b"pieces" in info or info.get(b"meta version") != 2:
            self.hashes.append(hashlib.sha1(raw_info).hexdigest())
        if info.get(b"meta version") == 2:
            self.hashes.append(hashlib.sha256(raw_info).hexdigest()[:40])
        comment = decoded.get(b"comment.utf-8", decoded.get(b"comment", b""))
        if not isinstance(comment, bytes):
            raise ValueError("Torrent comment must be a string")
        self.comment = comment.decode("utf-8", errors="strict")

    def with_identity(self, identity) -> bytes:
        """Only the outer comment changes; hashes, trackers and piece layers survive."""
        comment = write_request_comment(self.comment, identity).encode("utf-8")
        values = {**self.values, b"comment": _string(comment)}
        if b"comment.utf-8" in values:
            values[b"comment.utf-8"] = _string(comment)
        return b"d" + b"".join(_string(key) + values[key] for key in sorted(values)) + b"e"
