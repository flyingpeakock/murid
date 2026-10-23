# Audiobookshelf integration contract

## Verification scope

Source review completed on 2026-10-23 against Audiobookshelf **v2.37.1**, commit
`3563d49424d50170324de9236a24c591b6d965e9`. This is the version in the local
`/home/philipj/Code/nixpkgs/pkgs/by-name/au/audiobookshelf/package.nix` checkout.
The user identified nixpkgs as the deployed version source. Subsequent read-only
checks confirmed that the running server is v2.37.1 and that library inspection
works against it. Copying, scanning, and ingestion remain unverified; compatibility
with other versions has not been established.

The [published API reference](https://api.audiobookshelf.org/) is supplementary;
the tagged server source below determines this contract.

Murid implements library inspection and a shared-folder import backend against this
contract. Automated tests cover copying, crash recovery, scans, and API verification
with offline fixtures; live checks so far are read-only. Acquisition remains guarded
until torrent restart recovery is connected.

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

## Live inspection verification (2026-10-23)

Read-only checks using working-tree code and credentials from ignored
`config.yaml` confirmed:

- Server version v2.37.1; API key authenticates as an active admin user.
- The configured library is accessible, has book media type and one library root.
- All five existing items have usable audio; none have Murid Hardcover tags.
- One-item pagination returns the same five item IDs as the normal page size.
- The configured local library directory exists and passes read/write access
  checks for the user running this session. Service-user access and matching
  server/local mount contents still need import-time verification.
- After the user created the Hardcover audiobook list, its one requested book
  matched existing audio. Combined missing detection reported zero missing
  audiobooks and 15 missing ebooks. Detailed match review completed successfully
  for 455 requests across both media types.

The test harness allowed only HTTP GETs and read-only Hardcover GraphQL queries;
it disabled notifications. No downloads, library writes, or scans were performed.
An initial plural media type and incorrect library ID were corrected in the
ignored live configuration before verification.

## Import backend verification (step 5)

Offline tests exercise all-track copies, repeated filenames across disc folders,
metadata/tag merging, source preservation, interrupted-copy recovery, a crash after
publication, concurrent import locking, existing destination collisions (including
empty folders), changed destination audio, scan failures, and delayed scans without
recopying even when the original source is gone. API fixtures require exact folder
and item-relative paths, expected track counts, track-relative filenames and sizes,
positive finite durations, and the work tag. An existing title elsewhere cannot
satisfy verification. Each polling request is bounded by the remaining scan timeout.

The journal records source fingerprints and the original destination before copying.
Staging remains on the destination filesystem outside scanned roots. Publication
uses an atomic non-replacing rename; unsupported platforms/filesystems fail rather
than falling back to a replacing operation. Filesystem behavior was tested on Linux;
macOS/Windows branches have not been exercised here. Server root path checks cannot
prove physical bind-mount alias placement; deployment must ensure staging is truly
outside every scanned root. Source files are never moved, linked, or modified.

## Remaining live verification

The admin role meets the source-defined scan requirement, but scan execution has
not been tested. Once import is implemented, use one controlled import to verify
server/local folder mapping, service permissions, metadata/tag retention, nested
track paths, scan completion, and idempotent recovery. Enable live audiobook
acquisition only after the end-to-end workflow passes.
