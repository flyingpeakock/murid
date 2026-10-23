# Audiobook support plan

This is a living document. Agents implementing this plan should amend it as they
work to reflect verified findings, decisions, scope changes, completed work, and
remaining tasks. Keep it aligned with the implementation and record the reasoning
behind meaningful deviations.

## Goal

Allow each configured Hardcover list to request ebooks, audiobooks, or both.
Default to ebooks and preserve existing configuration behavior. Calibre remains
the ebook library; Audiobookshelf becomes the audiobook library.

Murid will copy completed audiobooks into a shared library folder, request an
Audiobookshelf scan, and verify ingestion. Downloads remain intact for seeding.

## Configuration design

Group reading lists under each API key (revised at the user's request):

```yaml
hardcover_api_keys:
  - api_key: !ENV HARDCOVER_API_KEY
    reading_list:
      want-to-read: {} # type defaults to ebook
      audiobooks:
        type: audiobook

calibre:
  # Existing ebook configuration

audiobookshelf:
  url: https://audiobooks.example.com
  api_key: !ENV AUDIOBOOKSHELF_API_KEY
  library_id: your-library-id
  library_path: /mnt/audiobooks # Writable path as seen by Murid
  filetypes: [m4b, mp3]
```

- Use `type: [ebook, audiobook]` to request both from one list.
- Token-only entries continue to request Want to Read ebooks.
- Omitted `reading_list` continues to mean Want to Read ebooks; omitted `type`
  defaults to ebook. An explicit list entry with no options uses `{}`.
- Legacy `list` and `media_types` entries remain supported. Do not combine them
  with `reading_list` in the same entry. Use URL slugs and singular `audiobook`.
- Reject empty media type lists and unknown values.
- Require Calibre configuration only when ebooks are requested, and
  Audiobookshelf configuration only when audiobooks are requested.
- Keep the existing top-level `filetypes` setting for ebook preferences.
- Redact the Audiobookshelf API key from logs and configuration output.
- The shared library folder must be writable by Murid and readable by
  Audiobookshelf; their mount paths may differ.

## Behavioral rules

- Identify a wanted request by `(Hardcover book ID, media type)`.
- Combine overlapping lists and users without duplicating requests.
- Requesting both means acquiring both independently. An ebook in Calibre does
  not satisfy an audiobook request.
- Only Audiobookshelf items with usable audio tracks satisfy audiobook requests;
  ebook-only items do not.
- Library lookup failures must not be interpreted as an empty library.
- Removing a book from a Hardcover list does not delete library content.
- An incomplete audiobook download must not suppress discovery of its ebook.

## Implementation sequence

### 1. Verify the Audiobookshelf integration contract

Before committing to client behavior, check the installed Audiobookshelf version
and verify authentication, library item pagination, audio track detection, scan
permissions, scan completion behavior, and metadata handling. The published API
reference says it is outdated, so confirm these against the deployed version or
matching server source.

Reference: https://api.audiobookshelf.org/

**Progress (2026-10-23):** Source contract review completed against v2.37.1
(`3563d49424d50170324de9236a24c591b6d965e9`), the version in the local nixpkgs
checkout. Findings and implementation decisions are recorded in
[docs/audiobookshelf-integration.md](docs/audiobookshelf-integration.md).
The user identified nixpkgs as the deployed version source and deferred live
access until configuration parsing accepts the URL and API key. Proceed with
step 2 using this source-verified contract; deployed-version confirmation and
live permission/ingestion checks remain pending before rollout.

Key decisions: bearer API key with an admin/root user, paginated item listing,
excluded-track-aware presence checks, and destination/track polling after scans
(HTTP 200 does not establish completion). Use `metadata.json` with a namespaced
Hardcover tag and a separate Murid import manifest; do not reuse ebook ISBNs.
Use author/title folders with a Hardcover ID suffix. Multiple Audiobookshelf
library roots require explicit folder mapping before import; this may add an
optional folder setting in a later phase once live deployment needs are known.

Decide the supported metadata representation and destination folder layout here.
Preserve Hardcover work identity where supported, and do not blindly apply
ebook-edition ISBNs as audiobook-edition identifiers.

### 2. Add configuration and media-aware requests together

**Completed (2026-10-23):** Added `BookRequest` with identity based on Hardcover
book ID and media type. `ServiceFactory.wanted_requests()` normalizes legacy
tokens and omitted options to ebook requests and combines overlapping lists.
At the user's request, the preferred configuration now groups lists in a
`reading_list` mapping under each API key. Each list's `type` defaults to ebook;
omitting `reading_list` retains Want to Read ebooks. Legacy flat entries remain
supported. Both request collection and the current ebook sync expand all grouped
lists. Documentation and NixOS serialization reflect the grouped form.
The existing ebook orchestration remains in place until step 3; audiobook
workflows fail explicitly before discovery/import instead of using Calibre or
dropping requests. Audio-only configuration validates without Calibre.

Added validated Audiobookshelf settings, format defaults, conditional backend
requirements, and API key redaction even when general redaction is disabled.
Updated the example, configuration reference, and NixOS options/assertions.
Connection diagnostics skip Calibre for audio-only lists and explicitly report
that Audiobookshelf checks are not implemented. Also corrected token extraction
for mapping entries in existing Hardcover connection checks.

Verification after grouped-list changes: the full Python suite passed (675 tests).
Ruff and Pylint passed, and the NixOS module check passed. Live
`config.yaml` was not changed. Credentials and live integration checks remain
pending. Shared-folder accessibility is intentionally deferred to runtime so
configuration can be prepared before the mount is available.

Make configuration changes at the beginning of implementation, after the
integration check establishes the required Audiobookshelf settings:

- Add a small request object holding a `Book` and its media type. Keep `Book`
  focused on metadata.
- Normalize legacy configuration into ebook requests.
- Add `media_types` validation and Audiobookshelf settings in `src/murid/config.py`.
- Update service construction and conditional backend requirements.
- Update `config.example.yaml`, `docs/configuration.md`, and `nixosModule.nix`
  in the same phase, including configuration tests and NixOS option coverage.
- Until later phases are connected, report an explicit unsupported-operation
  error for audiobook execution; never silently route it to Calibre or ignore it.

Do not change the live `config.yaml` during this phase. Enable audiobook lists in
the live configuration only after the complete workflow passes verification.

### 3. Separate library operations from orchestration

- Introduce a small common interface for listing books, checking presence, and
  importing, with Calibre and Audiobookshelf implementations.
- Keep media-specific file selection within the import implementations.
- Route each request to its library throughout sync and missing-book detection.
- Reuse existing matching logic where appropriate and avoid a general plugin
  framework.

### 4. Make MaM discovery media-aware

- Scope title searches, alternate-title searches, and author fallbacks to the
  requested media category. Verify audiobook category values before using them.
- Apply separate ebook and audiobook format preferences.
- Carry request identity through selection, downloads, and suppression of
  incomplete or failed work.

### 5. Import complete audiobooks into the shared folder

- Initially support a single M4B or a clearly identified single-book folder of
  M4B/MP3 tracks. Do not reuse the ebook selector to choose one audio track.
- Preserve filenames, track structure, and relevant sidecars.
- Reject ambiguous multi-book packs with an actionable diagnostic.
- Use a deterministic destination and check for collisions without overwriting
  unrelated library content.
- Copy to staging outside the scanned library, on the destination filesystem,
  then atomically rename the completed folder into the library.
- Recover incomplete staging work and make repeated imports idempotent.
- Leave source downloads intact for seeding.
- Request a scan and verify the destination item and expected audio tracks in
  Audiobookshelf. A completed copy is not yet a verified import.
- Bound scan verification separately from the torrent download timeout. A delayed
  scan must remain recoverable without another copy or torrent download.

### 6. Preserve routing and identity across restarts

- Persist media type and Hardcover identity when adding a torrent, alongside
  existing pending tags, so interrupted runs can recover the original request.
- Retain recovery behavior for legacy ebook torrents.
- Recover imports even if the book has subsequently left its Hardcover list.
- Clear pending or failure state only after the correct library confirms success.
- Keep failed imports actionable and avoid duplicate downloads during recovery.

### 7. Update commands and operational support

- Include media type and destination in missing-book results, match reviews,
  status, summaries, notifications, and JSON output.
- Add `--media-type ebook|audiobook` to manual search and import commands, defaulting
  to ebook. Accept a folder for manual audiobook imports.
- Check only configured/required libraries in connection diagnostics, including
  shared-folder accessibility and the Audiobookshelf integration permissions.
- Preserve dry-run behavior without copying files, scanning, or changing libraries.
- Document deployment mounts and service permissions; finish NixOS service changes.

## Verification and acceptance criteria

- Existing ebook configuration and workflows continue to pass.
- A book requested in both formats with its ebook already in Calibre downloads
  only the audiobook, imports all tracks, appears in Audiobookshelf, and causes
  no further work on the next run.
- Overlapping lists produce one request per book and media type.
- Audio-only configuration works without Calibre installed or configured.
- An ebook-only Audiobookshelf item does not satisfy an audiobook request.
- MaM title and author searches use the correct media categories.
- Interrupted copies, delayed scans, import failures, and restart recovery do not
  create duplicate folders or downloads.
- Ambiguous packs and destination collisions leave actionable errors and preserve
  existing content.
- Configuration validation, secret redaction, CLI output, and NixOS options cover
  the new settings.
- Run an end-to-end smoke check against the supported Audiobookshelf version
  before enabling audiobook lists in the live configuration.

## Deferred scope

Narrator preferences, abridged/unabridged selection, transcoding, archive
extraction, multi-book packs, and API file uploads are deferred. Initial matching
is at the book/work level rather than selecting a particular audiobook edition.

## Rollout

After verification, add Audiobookshelf credentials and shared-folder settings to
the live configuration, add an audiobook list, run configuration validation and
connection checks, inspect a dry run, and perform one controlled import before
enabling scheduled audiobook acquisition.
