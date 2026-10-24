# Configuration

[Back to README](../README.md)

Use [config.example.yaml](../config.example.yaml) as the complete configuration reference. Set `calibre.library` to either a local Calibre library path or a Calibre content server URL.
If upgrading an existing config, rename `calibre.library_path` or `calibre.server_url` to `calibre.library`.

## Environment variables

The example config reads secrets from environment variables. The Hardcover token must include the `Bearer ` prefix.

```bash
export HARDCOVER_API_KEY="Bearer ..."
export MAM_ID="..."
export CALIBRE_PASSWORD="..."
export QBITTORRENT_PASSWORD="..."
```

In PowerShell, set them with `$env:HARDCOVER_API_KEY = "Bearer ..."` and the equivalent `$env:NAME = "..."` for the others.

Set these variables in the environment that runs Murid. Default config locations:

| Platform | Path |
| --- | --- |
| Linux | `$XDG_CONFIG_HOME/murid/config.yaml` (or `~/.config/murid/config.yaml`) |
| macOS | `~/Library/Application Support/murid/config.yaml` |
| Windows | `%APPDATA%\murid\config.yaml` (or `~/AppData/Roaming/murid/config.yaml`) |

To use a config file elsewhere without passing `--config` on every command, set `MURID_CONFIG_FILE`:

```bash
export MURID_CONFIG_FILE=/path/to/config.yaml
```

`--config` can point to a config file anywhere and takes precedence over `MURID_CONFIG_FILE`.

Get your [Hardcover token](https://hardcover.app/account/api) and
[MyAnonamouse cookie](https://www.myanonamouse.net/preferences/index.php?view=security)
from account settings.

## Path mapping

Map the same download directory as seen by each process:

```yaml
qbittorrent:
  mapping:
    qbit_path: /downloads
    murid_path: /mnt/media/downloads
```

## Configuration reference

[Hardcover lists](#hardcover-lists) · [Audiobookshelf](#audiobookshelf) ·
[Calibre](#calibre) · [qBittorrent](#qbittorrent) ·
[Recovery](#torrent-metadata-and-recovery) · [Notifications](#notifications)

Defaults below apply to the YAML configuration. Required values must be supplied.

| Option | Description | Default |
| --- | --- | --- |
| `hardcover_api_keys` | Hardcover accounts with required `api_key` and `reading_list` (see below) | required |
| `qbittorrent` | qBittorrent connection settings (see below) | required connection values |
| `calibre` | Calibre settings (see below) | library required for ebooks |
| `audiobookshelf` | Audiobook library settings (see below) | required for audiobooks |
| `mam_id` | MyAnonamouse session cookie | required |
| `matcher_threshold` | Match confidence threshold from `0.0` to `1.0`; see [matching logic](matching.md) | `0.92` |
| `lang_codes` | Torrent languages and language-tagged Hardcover titles used for search | `["ENG"]` |
| `schedule` | Cron expression for scheduled syncs | `0 * * * *` |
| `redact_sensitive_data` | Hide secrets in logs and config dumps | `true` |
| `apprise` | List of Apprise notification URLs | `null` (disabled) |
| `filetypes` | Accepted ebook formats, most preferred first | `["epub", "mobi", "azw3", "azw"]` |
| `exclude_vip` | Exclude VIP-only torrents from ebook and audiobook selection | `false` |
| `blacklisted_torrent_ids` | MyAnonamouse torrent IDs to exclude | `[]` |
| `torrent_timeout_seconds` | Positive integer seconds to wait for a torrent to complete | `1800` |

### Hardcover lists

Each entry in `hardcover_api_keys` represents one user and requires an `api_key`
and a non-empty `reading_list` mapping. Group lists under one API key:

```yaml
hardcover_api_keys:
  - api_key: !ENV HARDCOVER_API_KEY
    reading_list:
      want-to-read: {} # type defaults to ebook
      books-to-download:
        type: ebook
      audiobooks:
        type: audiobook
  - api_key: !ENV SECOND_HARDCOVER_API_KEY
    reading_list:
      want-to-read: {}
```

Use the last part of your list URL: for
`https://hardcover.app/@yourname/lists/books-to-download`, use `books-to-download`
as the key under `reading_list`. Use the slug `want-to-read`, not `want to read`.
The custom list must belong to the user associated with that entry's token, which
must have permission to read the list. All books in that list are eligible for
sync, regardless of their reading status. The list replaces Want to Read for
that user unless `want-to-read` is also included. Missing or inaccessible lists cause an
error rather than falling back to Want to Read. An empty list selects no books.

Include `want-to-read: {}` to request Want to Read ebooks. Within each list,
omit `type` (use `{}` for an entry with no options) to default to ebook.
Token-only entries and the former `list` and `media_types` options are no longer
accepted; convert them to explicit `reading_list` entries when upgrading.

Set each list's `type` to `ebook` (the default), `audiobook`, or
`[ebook, audiobook]`. Use singular `audiobook`, not `audiobooks`. An empty
`reading_list`, empty type lists, and unknown media types are rejected.
Overlapping users and lists represent one
request per Hardcover book ID and media type; requesting both means acquiring
both independently.

```yaml
hardcover_api_keys:
  - api_key: !ENV HARDCOVER_API_KEY
    reading_list:
      audiobooks:
        type: audiobook
audiobookshelf:
  url: https://audiobooks.example.com
  api_key: !ENV AUDIOBOOKSHELF_API_KEY
  library_id: your-library-id
  library_path: /mnt/audiobooks
  filetypes: [m4b, mp3]
```

### Audiobookshelf

[Shared library permissions on NixOS](installation.md#shared-audiobook-libraries-on-nixos)

These options belong under `audiobookshelf`. Omit this section for ebook-only
configurations; omit Calibre for audio-only configuration validation.

| Option | Description | Default |
| --- | --- | --- |
| `url` | HTTP(S) base URL, optionally including a base path, without credentials, query or fragment | required |
| `api_key` | API key belonging to an active admin/root user with library access | required |
| `library_id` | Audiobookshelf book library ID | required |
| `library_path` | Absolute shared library directory as seen by Murid | required |
| `staging_path` | Absolute private staging/state directory on the library filesystem, outside every scanned root | sibling `.murid-staging-<library directory name>` |
| `folder_id` | Audiobookshelf folder ID corresponding to `library_path`; required for multiple library roots | sole library folder |
| `scan_timeout_seconds` | Positive integer limiting scan verification, separately from download timeout | `120` |
| `filetypes` | Accepted audiobook formats in preference order; `m4b` and `mp3` supported | `[m4b, mp3]` |

Set `AUDIOBOOKSHELF_API_KEY` in Murid's environment and reference it with `!ENV`.
Supply the key itself; Murid will supply the Authorization Bearer prefix.
The Audiobookshelf key is always redacted by `print-config`, including JSON output,
even when `redact_sensitive_data` is false. Other secrets follow that flag.

Configuration validation does not contact the server or require the shared mount
to exist yet. At runtime, the folder must be writable by Murid and readable by
Audiobookshelf; mount paths can differ. The integration has been verified against
Audiobookshelf v2.37.1.
Use `filetypes` for ebook preferences and `audiobookshelf.filetypes` for audiobook
preferences.

#### Accepted files

```text
Dune.m4b                     # One complete M4B
Dune/                        # Or one complete book folder
  CD1/                       # Optional disc level
    01.mp3
    02.mp3
  CD2/
    01.mp3
```

Use one M4B file, or a title-matched folder of numbered or book-named M4B/MP3
tracks. A single MP3 must be inside its own title-matched folder. For folders with
multiple M4Bs, every filename must match the requested book title. One level of disc folders named `CD1`, `Disc 2`, or
`Disk 003` (one to three digits, case insensitive) is supported; filenames and
repeated track basenames across discs are preserved. Underscores, hyphens, and
nested disc folders must be reorganized before import. For mixed encodings or
multi-book packs, select one complete book in one encoding first. Folders containing recognized
unsupported audio formats, including MP4, AIFF, and OGA, are rejected in full.
Sources remain intact for seeding. Supported sidecar files are copied too.

#### Staging and recovery

Books are copied into
`<library_path>/<author>/<title> [hardcover-<id>]/`. Existing unrelated destinations
are never overwritten. The staging directory must be writable by Murid and on
the same filesystem as the library; ensure it is physically outside **all**
Audiobookshelf scanned roots, including bind-mount aliases. If `library_path` itself is a mount
point, its default sibling may be on a different filesystem; set `staging_path`
explicitly on the shared volume. Audiobookshelf needs read/traverse permissions
on the destination and its parent directories. Keep the staging directory private
to Murid.

If a scan times out or fails, retry the import; a delayed scan does not require
another copy. Keep staging journals, partial folders, and destination
`.murid-import.json` markers until the import succeeds.

### Calibre

These options belong under `calibre`.

| Option | Description | Default |
| --- | --- | --- |
| `calibredb_executable` | Path to the `calibredb` executable | `calibredb` |
| `command_timeout_seconds` | Positive integer maximum runtime for each `calibredb` command | `120` |
| `library` | Local library path or Calibre content server URL | required |
| `server_username` | Calibre content server username | `null` |
| `server_password` | Calibre content server password | `null` |

### qBittorrent

These options belong under `qbittorrent`.

| Option | Description | Default |
| --- | --- | --- |
| `host` | Web UI host | required |
| `port` | Web UI port, integer from `1` to `65535` | required |
| `username` | Login username | required |
| `password` | Login password | required |
| `verify_cert` | Verify TLS certificates | `true` |
| `category` | Category assigned to Murid torrents | `murid` |
| `mapping.qbit_path` | Download path as seen by qBittorrent; see [path mapping](#path-mapping) | `null` |
| `mapping.murid_path` | Corresponding download path as seen by Murid | `null` |

### Torrent metadata and recovery

| qBittorrent tag | Meaning |
| --- | --- |
| `murid` | Import pending |
| `murid-timeout` | Download exceeded the wait limit |
| `murid-import-failed` | Import failed |

```bash
murid status
murid retry-import
```

Murid clears these tags after a successful import. Unresolved imports are retried
without downloading the book again. Dry runs leave tags and comments unchanged.

Keep Murid's torrent comments: they identify the book and medium for recovery,
even after a book leaves your reading lists. A valid Hardcover API key is still
required. Missing or conflicting identities block new discovery; inspect the
affected torrents with `status` before retrying.

Older torrents are migrated automatically during sync, retry, or torrent adds.
Migration requires qBittorrent Web API 2.12.1 or newer. Legacy torrents without a
saved Hardcover ID are treated as ebooks and need their original MyAnonamouse
comment plus a unique match in your current Hardcover lists.

## Torrent preferences and imported metadata

The order of `filetypes` controls format preference for both torrent selection
and ebook selection within a download. Torrents must first pass the configured
filters and [book matching rules](matching.md). Murid then prefers torrents with
seeders, higher match scores, earlier formats in `filetypes`, freeleech, and more seeders, in that
order. Ties use the torrent ID for reproducible selection. Unseeded torrents remain
eligible when no seeded match is available.

Calibre imports use Hardcover titles, authors, series, and identifiers. Existing
metadata and format files are preserved; missing formats can be added to matching
records. Records without any formats count as missing.

Calibre commands that exceed `calibre.command_timeout_seconds` stop with an error.
An import timeout leaves the download tagged for investigation and `retry-import`.
Check the library before retrying: Calibre may have written the book before the
command timed out. Increase the timeout for large files or slow content servers.

## Notifications

Configure destination URLs using [Apprise](https://appriseit.com/getting-started/configuration/).

Set `apprise` to a list of destination URLs, as shown in the example configuration,
or an Apprise configuration mapping containing `urls`. Omit `apprise` or set it to
`null` to disable notifications. A nonempty configuration that loads no usable
destinations is rejected during initialization.
