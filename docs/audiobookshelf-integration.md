# Audiobookshelf integration contract

## Verification scope

Source review completed on 2026-10-23 against Audiobookshelf **v2.37.1**, commit
`3563d49424d50170324de9236a24c591b6d965e9`. This is the version in the local
`/home/philipj/Code/nixpkgs/pkgs/by-name/au/audiobookshelf/package.nix` checkout.
The user identified nixpkgs as the deployed version source. The running server
has not yet been queried; live checks are deferred until Murid can parse the
Audiobookshelf URL and API key. This is a source-verified target, not a claim of
successful live integration or compatibility with other versions.

The [published API reference](https://api.audiobookshelf.org/) is supplementary;
the tagged server source below determines this contract.

## Authentication and access

- Send an API key as `Authorization: Bearer <key>` over HTTPS. Do not put the
  key in URL query parameters or logs. No login/refresh workflow is needed for
  a configured API key.
- The key must be active and unexpired, and its associated user active.
- The user must have access to the configured library. Scanning additionally
  requires an `admin` or `root` user; the ordinary update permission is not enough.
- `GET /status` exposes `serverVersion`; use it to confirm the running version.
- Fail authentication, permission, transport, and malformed-response checks
  explicitly. An inaccessible library must never become an empty library.

Sources: [Auth.js](https://github.com/advplyr/audiobookshelf/blob/v2.37.1/server/Auth.js),
[TokenManager.js](https://github.com/advplyr/audiobookshelf/blob/v2.37.1/server/auth/TokenManager.js),
[User.js](https://github.com/advplyr/audiobookshelf/blob/v2.37.1/server/models/User.js),
[Server.js](https://github.com/advplyr/audiobookshelf/blob/v2.37.1/server/Server.js).

## Library lookup and usable audio

- Validate `GET /api/libraries/<library_id>` and require `mediaType: book`.
  Audiobookshelf uses this media type for both ebooks and audiobooks.
- List `GET /api/libraries/<library_id>/items?limit=100&page=0`, incrementing the
  zero-based page. Read `results` and `total`; leave series collapsing disabled.
  Detect inconsistent or prematurely empty pagination as a lookup error.
- In this version, the list implementation returns minified items even when
  `minified` is omitted. `media.numTracks` counts audio files that are not excluded;
  `numAudioFiles` also counts excluded files and is insufficient for presence.
- For presence, require a book item that is neither `isMissing` nor `isInvalid`
  and has `media.numTracks > 0`. An ebook-only item does not satisfy the request.
- For import verification, fetch `GET /api/items/<id>?expanded=1`. Verify the
  item's library and relative destination path, valid item flags, and the expected
  relative audio filenames in `media.tracks` (`metadata.relPath`). These tracks
  exclude disabled audio files. Require positive track durations. Mere item or
  folder existence is insufficient.

Sources: [LibraryController.js](https://github.com/advplyr/audiobookshelf/blob/v2.37.1/server/controllers/LibraryController.js),
[LibraryItem.js](https://github.com/advplyr/audiobookshelf/blob/v2.37.1/server/models/LibraryItem.js),
[LibraryItemController.js](https://github.com/advplyr/audiobookshelf/blob/v2.37.1/server/controllers/LibraryItemController.js),
[Book.js](https://github.com/advplyr/audiobookshelf/blob/v2.37.1/server/models/Book.js).

## Scans and completion

`POST /api/libraries/<library_id>/scan` starts a normal scan. HTTP 200 is sent
**before** scanning finishes. If the library is already scanning, the scanner
returns without starting another scan, also after HTTP 200. Do not force a full
rescan by default.

Poll library items and expanded destination details within a separate scan
verification timeout. The success condition is the destination item with all
expected usable tracks, rather than a successful scan request or a global scan
completion event. Retain copied-but-unverified state on timeout and retry
verification/scanning on a subsequent run without recopying or downloading.

Sources: [LibraryController.js](https://github.com/advplyr/audiobookshelf/blob/v2.37.1/server/controllers/LibraryController.js),
[LibraryScanner.js](https://github.com/advplyr/audiobookshelf/blob/v2.37.1/server/scanner/LibraryScanner.js).

## Metadata and destination decisions

- Use a flat `metadata.json` sidecar for known work metadata (`title`, `authors`,
  optional `series`) and a `murid:hardcover:<book_id>` tag in its `tags` array.
  The parser accepts tags but has no native Hardcover identifier field. Preserve
  existing metadata tags when merging; never replace an existing sidecar blindly.
- Keep authoritative import identity and expected files in a separate Murid
  manifest. Tags are useful for lookup, but users can edit them and library
  metadata precedence can override sidecar values. Validate that the target
  library's metadata precedence retains the Murid tag during the live smoke test.
- Do not write Hardcover ebook-edition ISBNs or inferred audiobook ASINs into the
  audiobook sidecar. Preserve supplied audio metadata and relevant sidecars.
- Use `<library_path>/<sanitized author>/<sanitized title> [hardcover-<id>]/`
  as the destination, preserving selected source filenames and track subfolders.
  The ID suffix separates same-title works; persist the chosen relative path so
  metadata changes do not rename an existing import on retries.
- Stage in a sibling directory outside every scanned library root on the same
  filesystem. Confirm atomic rename is possible before copying. Reject collisions
  with content not owned by the same request; leave source downloads intact.
- Resolve destination verification using the library's folder ID and item
  `relPath`, not Murid's absolute path: server and Murid mount paths can differ.
  If the library has multiple roots, require an explicit folder mapping before
  import rather than guessing which root matches `library_path`.

Sources: [metadata parser](https://github.com/advplyr/audiobookshelf/blob/v2.37.1/server/utils/generators/abmetadataGenerator.js),
[AbsMetadataFileScanner.js](https://github.com/advplyr/audiobookshelf/blob/v2.37.1/server/scanner/AbsMetadataFileScanner.js),
[BookScanner.js](https://github.com/advplyr/audiobookshelf/blob/v2.37.1/server/scanner/BookScanner.js),
[Library.js](https://github.com/advplyr/audiobookshelf/blob/v2.37.1/server/models/Library.js).

## Pending live verification

After configuration parsing supports Audiobookshelf, supply the URL, API key,
library ID, and shared library path. Confirm the running version, authenticated
pagination, admin scan access, library folder mapping, and filesystem permissions.
Then use one controlled import to verify metadata/tag retention, nested track
paths, scan completion, and idempotent recovery. Enable live audiobook acquisition
only after the end-to-end workflow passes.
