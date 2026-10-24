# murid

**Definition (Webster's Dictionary)**  
*Murid* (noun): of or relating to a family (Muridae) comprising the typical mice and rats and often those rodents classified as cricetids

---

Murid syncs Hardcover reading lists with Calibre for ebooks and Audiobookshelf for
audiobooks. It searches MyAnonamouse for missing books, downloads them through
qBittorrent, and imports each completed download into its media-specific library.

```text
Hardcover → Reading lists and requested formats
    ↓
Calibre / Audiobookshelf → Check existing books
    ↓
MyAnonamouse → Search the requested format
    ↓
qBittorrent → Download and retain sources for seeding
    ↓
Calibre / Audiobookshelf → Import and verify
```

It supports multiple Hardcover accounts, separate list and format preferences,
scheduled syncs, notifications, dry runs, and recovery after interrupted imports.

## Requirements

- Python 3.12+
- Calibre with `calibredb` for ebooks
- Audiobookshelf with an admin/root API key and a shared writable library for audiobooks
- qBittorrent with its Web UI enabled
- A Hardcover API key
- A MyAnonamouse account

## Quick start

### 1. Install

On Linux or macOS:

```bash
git clone https://github.com/flyingpeakock/murid.git
cd murid
python -m venv .venv
source .venv/bin/activate
pip install .
```

See the [installation guide](docs/installation.md) for Windows, NixOS, shell
completion, and development setup.

### 2. Configure

```bash
cp config.example.yaml config.yaml
```

Edit `config.yaml` with your Calibre library and qBittorrent connection details.
`calibre.library` accepts a local library path or a Calibre content server URL.
The [example configuration](config.example.yaml) lists all settings, including
language, format preferences, and optional notifications.

The example reads secrets from environment variables. Set these in the shell or
service environment that runs Murid:

```bash
export HARDCOVER_API_KEY="Bearer ..."
export MAM_ID="..."
export CALIBRE_PASSWORD="..."
export QBITTORRENT_PASSWORD="..."
```

Get your Hardcover token from [account settings](https://hardcover.app/account/api)
(include the `Bearer ` prefix), and your `mam_id` cookie from
[MyAnonamouse security settings](https://www.myanonamouse.net/preferences/index.php?view=security).
`CALIBRE_PASSWORD` is needed when using the example's authenticated Calibre server
configuration; adjust the Calibre settings for your library.

In PowerShell, use `$env:NAME = "..."` instead of `export NAME="..."`.
See the [configuration guide](docs/configuration.md) for config file selection,
container path mapping, credentials, and import behavior.

### 3. Check and preview

```bash
murid validate-config --config ./config.yaml
murid test-connection --config ./config.yaml
murid run --config ./config.yaml --dry-run
```

A dry run searches for matches and fetches selected `.torrent` files. It does not
add torrents, copy books, request scans, or change import tags. Review the results before running
your first sync.

## Everyday usage

Sync once:

```bash
murid run --config ./config.yaml
```

Or keep Murid running on the configured cron schedule (every hour by default):

```bash
murid schedule --config ./config.yaml
```

Put options after the command. Run `murid --help` or `murid <command> --help` for
available options.

| Command | Purpose |
| --- | --- |
| `run` | Sync once and exit |
| `schedule` | Sync repeatedly using the configured cron schedule |
| `list-missing` | List Hardcover requests missing from their media libraries |
| `review-matches` | Inspect Hardcover library matches and scores |
| `search-book NAME` | Preview torrent candidates; use `--add` to download and import |
| `add-book NAME PATH` | Import a local book; use `--audiobooks` for an M4B or complete audio folder |
| `status` | Show Murid torrents and their download and import status |
| `retry-import` | Retry imports for tagged downloads |
| `test-connection` | Check access to each configured service |
| `test-notification` | Send a test notification through Apprise |
| `validate-config` | Validate a configuration file |
| `print-config` | Print the parsed configuration, with secrets redacted by default |

See the [usage guide](docs/usage.md) for command examples, scheduling and retries,
JSON output, and exit codes.

## How matching works

Murid checks ISBNs and catalog IDs, then compares titles, authors, and series
metadata. Matching tolerates alternate titles and common formatting differences
while rejecting conflicting metadata. Adjust `matcher_threshold` (default `0.92`)
to control sensitivity, and use `murid review-matches` to inspect results.

Use `--ebooks` or `--audiobooks` on listing, search, import, sync, retry, status,
and connection commands to select one medium. Search and manual import default to
ebooks; other commands retain their behavior across configured media.

Unmatched books are searched on MyAnonamouse; downloads must pass the configured
language, file type, and blacklist filters as well as the matching rules. See
[matching logic](docs/matching.md) for scoring and safeguards.

## Documentation

- [Installation](docs/installation.md) — Windows, NixOS, shell completion, development
- [Configuration](docs/configuration.md) — secrets, library paths, torrent preferences, imports
- [Usage](docs/usage.md) — commands, output formats, scheduling, troubleshooting
- [Matching logic](docs/matching.md) — identifiers, scoring, rejection rules
- [Example configuration](config.example.yaml) — all configuration settings

## Disclaimer

This tool is intended for personal library automation and management. Users are
responsible for complying with applicable laws and the terms of service of
Hardcover, MyAnonamouse, qBittorrent, and any other services used.

## License

[MIT](LICENSE)
