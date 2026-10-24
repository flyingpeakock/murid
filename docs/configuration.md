# Configuration

[Back to README](../README.md)

Use [config.example.yaml](../config.example.yaml) as the complete configuration reference. Set `calibre.library` to either a local Calibre library path or a Calibre content server URL.
If upgrading an existing config, rename `calibre.library_path` or `calibre.server_url` to `calibre.library`.

## Configuration reference

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
`[ebook, audiobook]`. Use singular `audiobook`, not `audiobooks`. Empty mappings,
empty type lists, and
unknown media types are rejected. Overlapping users and lists represent one
request per Hardcover book ID and media type; requesting both means acquiring
both independently.

`run`, `schedule`, and `retry-import` now route ebook and audiobook requests to
Calibre and Audiobookshelf independently. Inspection output includes media and
destination. Ebook-only Audiobookshelf items do not satisfy audio requests, and
library lookup failures abort the cycle. Manual `search-book` and `add-book` accept
`--media-type audiobook`; omitting it retains ebook behavior. `test-connection`
checks configured/required libraries and the API, shared-path, and staging access
needed for imports without copying or scanning. Before scheduling, verify access
as the actual service user; see [the integration notes](audiobookshelf-integration.md).

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
| `filetypes` | Accepted audiobook formats in preference order; only `m4b` and `mp3` supported initially | `[m4b, mp3]` |

Set `AUDIOBOOKSHELF_API_KEY` in Murid's environment and reference it with `!ENV`.
Supply the key itself; Murid will supply the Authorization Bearer prefix.
The Audiobookshelf key is always redacted by `print-config`, including JSON output,
even when `redact_sensitive_data` is false. Other secrets follow that flag.

Configuration validation does not contact the server or require the shared mount
to exist yet. At runtime, the folder must be writable by Murid and readable by
Audiobookshelf; mount paths can differ. The current contract targets v2.37.1;
see [integration verification and pending live checks](audiobookshelf-integration.md).
The top-level `filetypes` continues to control ebook preferences only. Discovery
uses separate audiobook preferences from `audiobookshelf.filetypes`. Main title,
alternate title, and author fallback searches are scoped to MaM main category 14
for ebooks or 13 for audiobooks. Automatic import and restart recovery are connected;
manual commands select the medium with `--media-type ebook|audiobook`.

Library inspection uses paginated item listing and fetches expanded details for
audio candidates to preserve author names and verify playable tracks. It sends
read-only API requests and neither copies files nor requests scans. Work tags
(`murid:hardcover:<id>`) and title/author metadata support matching; audiobook
edition ISBNs and ASINs are excluded from matching against Hardcover ebook metadata.

The import backend accepts one M4B file, or a title-matched folder of numbered or
book-named M4B/MP3 tracks. One level of disc folders named `CD1`, `Disc 2`, or
`Disk 003` (one to three digits, case insensitive) is supported; filenames and
repeated track basenames across discs are preserved. Underscores, hyphens, and
nested disc folders must be reorganized before import because the target server
does not group them into one book. Mixed encodings and ambiguous multi-book packs
require selecting one complete book/encoding first. Sources remain intact for
seeding; Murid copies supported sidecars and merges its identity tag into the
copied `metadata.json` without adding ebook ISBNs.

Copies are staged privately, then published atomically into
`<library_path>/<author>/<title> [hardcover-<id>]/`. Existing unrelated destinations
are never overwritten. The staging directory must be writable by Murid and on
the same filesystem as the library; ensure it is physically outside **all**
Audiobookshelf scanned roots, including bind-mount aliases. Murid checks local
filesystem placement and visible server root paths, but cannot prove that two
mount aliases expose the same directory. If `library_path` itself is a mount
point, its default sibling may be on a different filesystem; set `staging_path`
explicitly on the shared volume. Audiobookshelf needs read/traverse permissions
on the destination and its parent directories. Keep the staging directory private
to Murid: its journals contain source paths and book metadata.

A scan acknowledgement does not confirm ingestion. Murid verifies the selected
folder ID, destination path, every track's relative path/size and playable duration,
and the Hardcover identity tag. Timeout or scan failure leaves the completed copy
and durable journal available for retry. Keep staging journals, partial folders,
and destination `.murid-import.json` markers; retries use them to resume safely.
A delayed scan does not require another copy. See the
[integration verification record](audiobookshelf-integration.md) for live ingestion
results and remaining service-user/deployment checks.

Murid adds `murid_media_ebook` or `murid_media_audiobook` and
`murid_hardcover_<id>` with the initial torrent add, alongside `murid_pending`.
These identity tags remain after success. Restarts fetch tagged works directly
from Hardcover by ID, so recovery does not require continued reading-list membership
or a MaM comment. Keep a valid Hardcover API key configured. Untagged legacy torrents
remain ebooks and use their MaM comment plus a unique current Hardcover-list match.
Missing or conflicting request identity blocks new discovery until resolved, rather
than risking a duplicate download or an import into the wrong library.

A delayed audiobook scan remains pending for the next run; an import failure keeps
its lifecycle tags and suppresses another download of that work and medium while
recovery is unresolved. `retry-import` retries once and never adds torrents. It
clears pending/timeout/failure tags only after success in the correct library.
For audio this includes verification of the persisted destination and tracks;
a general title match cannot clear a copied-but-unverified import. Dry runs retain
all tags and perform no imports or scans.

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

## Environment variables

The example config reads secrets from environment variables. The Hardcover token must include the `Bearer ` prefix.

```bash
export HARDCOVER_API_KEY="Bearer ..."
export MAM_ID="..."
export CALIBRE_PASSWORD="..."
export QBITTORRENT_PASSWORD="..."
```

In PowerShell, set them with `$env:HARDCOVER_API_KEY = "Bearer ..."` and the equivalent `$env:NAME = "..."` for the others.

Set these variables in the environment that runs Murid. The default config location depends on your operating system. To use a config file elsewhere without passing `--config` on every command, set `MURID_CONFIG_FILE`:

```bash
export MURID_CONFIG_FILE=/path/to/config.yaml
```

`--config` can point to a config file anywhere and takes precedence over `MURID_CONFIG_FILE`.

## Credentials

### Hardcover API Key

Generate one in your account settings:  
<https://hardcover.app/account/api>

### MyAnonamouse Cookie (mam_id)

Found in your MyAnonamouse security settings:  
<https://www.myanonamouse.net/preferences/index.php?view=security>

## Path mapping

If qBittorrent and Murid see the download directory under different paths (for example,
when one or both are running in containers with different volume mounts), configure a path mapping.

Set:

- `qbittorrent.mapping.qbit_path` to the download path as seen by qBittorrent
- `qbittorrent.mapping.murid_path` to the corresponding path as seen by Murid

For example, qBittorrent may save files to `/downloads` inside a container,
while Murid accesses the same files at `/mnt/media/downloads` on the host. In that case:

```yaml
qbittorrent:
  mapping:
    qbit_path: /downloads
    murid_path: /mnt/media/downloads
```

This allows Murid to correctly locate files reported by qBittorrent.

## Torrent preferences and imported metadata

The order of `filetypes` controls format preference for both torrent selection
and ebook selection within a download. Torrents must first pass the configured
filters and [book matching rules](matching.md). Murid then prefers torrents with
seeders, higher match scores, earlier formats in `filetypes`, freeleech, and more seeders, in that
order. Ties use the torrent ID for reproducible selection. Unseeded torrents remain
eligible when no seeded match is available.

New downloads and `search-book --add` use the requested Hardcover book's metadata
when importing into Calibre. Imports preserve title, authors, series (including
position zero), the first valid ISBN, the Hardcover book ID, and the first nonempty
identifier per catalog type. Calibre supports one value per identifier type;
identifier values retain their original case. Existing library records are not
updated during import. Retries of earlier downloads still recover metadata from
MyAnonamouse.

Calibre commands that exceed `calibre.command_timeout_seconds` stop with an error.
An import timeout leaves the download tagged for investigation and `retry-import`.
Check the library before retrying: Calibre may have written the book before the
command timed out. Increase the timeout for large files or slow content servers.

For optional notifications, configure destination URLs using [Apprise](https://appriseit.com/getting-started/configuration/).
