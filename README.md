# murid

Sync Hardcover reading lists with **Calibre** for ebooks and **Audiobookshelf** for
audiobooks. Murid finds missing books on MyAnonamouse, downloads them through
qBittorrent, and imports them while keeping sources available for seeding.

```text
Hardcover lists → Check libraries → Search MyAnonamouse → qBittorrent → Import & verify
```

## Quick start

You need Python 3.12+, a Hardcover API key, a MyAnonamouse account, and qBittorrent
with its Web UI enabled. For ebooks, install Calibre (`calibredb`). For audiobooks,
you need an Audiobookshelf admin/root API key and a shared writable library.

### 1. Install

```bash
git clone https://github.com/flyingpeakock/murid.git
cd murid
python -m venv .venv
source .venv/bin/activate
pip install .
cp config.example.yaml config.yaml
```

[Windows, NixOS, and development setup →](docs/installation.md)

### 2. Configure

Edit `config.yaml`: set your Hardcover lists, library, and qBittorrent connection.
The example starts with Want to Read ebooks and an authenticated Calibre server;
`calibre.library` also accepts a local library path.

Set the secrets used by the example in the shell or service that runs Murid:

```bash
export HARDCOVER_API_KEY="Bearer ..."
export MAM_ID="..."
export CALIBRE_PASSWORD="..."
export QBITTORRENT_PASSWORD="..."
```

Get the [Hardcover token](https://hardcover.app/account/api) (keep the `Bearer `
prefix) and [MyAnonamouse `mam_id` cookie](https://www.myanonamouse.net/preferences/index.php?view=security).
In PowerShell, use `$env:NAME = "..."`.

[Lists, audiobooks, secrets, and container paths →](docs/configuration.md)

### 3. Preview, then sync

```bash
murid validate-config --config ./config.yaml
murid test-connection --config ./config.yaml
murid run --config ./config.yaml --dry-run
murid run --config ./config.yaml
```

A dry run searches and fetches selected `.torrent` files, but does not add
torrents, import books, request scans, or change import tags.

## Everyday commands

Options go **after** the command. Set `MURID_CONFIG_FILE` to avoid repeating `--config`:

```bash
export MURID_CONFIG_FILE="$PWD/config.yaml"
murid schedule                         # Keep running; sync hourly by default
murid list-missing                     # See what your libraries lack
murid search-book "Dune"               # Preview torrent choices and rejection reasons
murid status                           # Check downloads and imports
murid retry-import                     # Retry without adding torrents
```

Use `--ebooks` or `--audiobooks` to select one medium. Manual search and import
default to ebooks. Murid supports multiple Hardcover accounts and lists,
notifications, and recovery after interrupted imports.

## Guides

- [Usage](docs/usage.md) — commands, local imports, scheduling, troubleshooting, JSON
- [Configuration](docs/configuration.md) — lists, libraries, secrets, download preferences
- [Installation](docs/installation.md) — Windows, NixOS, completion, development
- [Matching](docs/matching.md) — scores and safeguards; inspect with `murid review-matches`
- [Example configuration](config.example.yaml) — editable settings and defaults

## License and responsibility

[MIT](LICENSE). Use Murid in accordance with applicable laws and your services'
terms of service.
