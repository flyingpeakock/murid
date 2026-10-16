# murid

**Definition (Webster's Dictionary)**  
*Murid* (noun): of or relating to a family (Muridae) comprising the typical mice and rats and often those rodents classified as cricetids

---

Murid automatically syncs your reading list from Hardcover with your Calibre library and fetches missing ebooks using MyAnonamouse.

It is designed to automate the full pipeline from “want to read” → “available in Calibre”.

## Overview

On each run, Murid:

1. Fetches books from one or more Hardcover accounts
2. Compares them against your local Calibre library
3. Searches MyAnonamouse for missing books
4. Sends matching torrents to qBittorrent
5. Imports completed downloads into Calibre

The goal is a mostly hands-off workflow for turning your “Want to Read” list into an actual, local library.


## Features

- Multiple Hardcover accounts
- ISBN + title/author matching
- Fuzzy matching with configurable threshold
- Scheduled sync via cron expressions
- MyAnonamouse integration
- qBittorrent integration
- Automatic Calibre imports
- Dry-run mode
- Environment variable secret injection
- Structured logging

## Architecture

Hardcover → Fetch reading lists  
    ↓  
Calibre → Check existing library  
    ↓  
MyAnonamouse → Search missing books  
    ↓  
qBittorrent → Download torrents  
    ↓  
Calibre → Import completed books

## Requirements

- Python 3.12+
- Calibre
- qBittorrent (Web UI enabled)
- Hardcover API key
- MyAnonamouse account

## Installation

### Linux / macOS

```bash
git clone https://github.com/flyingpeakock/murid.git
cd murid

python -m venv .venv
source .venv/bin/activate

pip install .
```

To enable shell completion after a Python installation, add the line for your shell to its startup file:

```sh
# bash
eval "$(register-python-argcomplete murid)"

# zsh
eval "$(register-python-argcomplete --shell zsh murid)"

# fish
register-python-argcomplete --shell fish murid | source
```

The Nix package installs completion files for bash, zsh, and fish automatically.
The development shell also includes `murid`. Run `nix develop -c zsh` and complete `murid` by name.
For a direct path such as `./result/bin/murid`, register that path in your current zsh session:

```zsh
source ./result/share/zsh/site-functions/_murid
compdef -p _python_argcomplete '*/murid'
```

### Windows

```powershell
git clone https://github.com/flyingpeakock/murid.git
cd murid

python -m venv .venv
.\.venv\Scripts\Activate.ps1

pip install .
```

### Development

```bash
git clone https://github.com/flyingpeakock/murid.git
cd murid

python -m venv .venv
source .venv/bin/activate

pip install -e ".[dev]"
```

### NixOS Flake

Add Murid as a flake input, then include its module in your NixOS module list. For example:

```nix
inputs.murid.url = "github:flyingpeakock/murid";

# In nixosSystem.modules:
[
  murid.nixosModules.default
  ({ ... }: {
    services.murid = {
      enable = true;
      environmentFile = "/etc/murid.env";
      config = {
        hardcover_api_keys = [ "!ENV HARDCOVER_API_KEY" ];
        mam_id = "!ENV MAM_ID";
        calibre.library = "http://localhost:8080/#books";
        qbittorrent = {
          username = "admin";
          password = "!ENV QBITTORRENT_PASSWORD";
        };
      };
    };
  })
]
```

Put `HARDCOVER_API_KEY` (including the `Bearer ` prefix), `MAM_ID`, and `QBITTORRENT_PASSWORD` in `/etc/murid.env`. See [nixosModule.nix](nixosModule.nix) for all module options.
The module starts `murid schedule` and accepts either an inline `services.murid.config`
or a path in `services.murid.configFile`. Set `environmentFile` when the selected
configuration uses `!ENV` secrets.

## Usage

Murid uses a command followed by its options. Run `murid --help` to list commands,
or `murid <command> --help` for command-specific options. Put `--config` after the
command, as in the examples below.

| Command | Purpose |
| --- | --- |
| `run` | Sync once and exit |
| `schedule` | Sync repeatedly using the configured cron schedule |
| `list-missing` | List Hardcover books missing from Calibre |
| `review-matches` | Inspect Hardcover to Calibre matches and scores; use `--matched` or `--unmatched` to filter |
| `search-book NAME` | Preview torrent candidates for a Hardcover book; use `--add` to download and import the selected torrent |
| `add-book NAME PATH` | Import an ebook file with metadata from Hardcover |
| `status` | Show Murid torrents and their download and import status |
| `retry-import` | Retry imports for tagged downloads |
| `test-connection` | Check access to each configured service |
| `test-notification` | Send a test notification through Apprise |
| `validate-config` | Validate a configuration file |
| `print-config` | Print the parsed configuration, with secrets redacted by default |

Murid replaces punctuation and search operators in generated queries with spaces,
preserving Unicode letters, numbers, and combining marks. Queries without
searchable words are skipped.

For example, inspect book matches or validate a configuration before syncing:

```bash
murid review-matches --unmatched --config ./config.yaml
murid validate-config --config ./config.yaml
```

To import a file that Murid could not select automatically, give the book name from your
Hardcover Want to Read list and the path to the ebook file:

```bash
murid add-book "Children of Dune" /path/to/children-of-dune.epub --config ./config.yaml
```

Murid matches the name against your Hardcover books, including close spellings and alternate
titles, then uses the matched title, authors, and series when adding the file to Calibre.
It stops if the name is ambiguous or the book already exists in Calibre.

To inspect downloads in Murid's configured qBittorrent category, including torrents
tagged for a timeout or failed Calibre import, run:

```bash
murid status --config ./config.yaml
```

To retry importing completed Murid downloads tagged for a timeout or failed import,
without searching for or adding new torrents, run:

```bash
murid retry-import --config ./config.yaml
```

It checks tagged torrents once, reports downloads still in progress, and leaves failed
imports tagged for further investigation. It exits with a nonzero status if any
tagged torrent still needs attention.

To check access to Hardcover, Calibre, MyAnonamouse, and qBittorrent, run:

```bash
murid test-connection --config ./config.yaml
```

Each service is checked independently. The command exits with a nonzero status if
any check fails.

To preview MyAnonamouse results for a book on your Hardcover reading list and see
which torrent Murid would select, run:

```bash
murid search-book "Children of Dune" --config ./config.yaml
```

This shows candidate scores and rejection reasons without downloading a torrent or
adding anything to qBittorrent or Calibre.

To add the selected torrent to qBittorrent and wait for its completed ebook to be
imported into Calibre, use `--add`:

```bash
murid search-book "Children of Dune" --add --config ./config.yaml
```

Murid refuses to add the book if it is already in Calibre. If the torrent does not
finish within the configured timeout, Murid tags it for a later import attempt.

Copy the example config, fill in your connection details, and provide the secrets described below:

```bash
cp config.example.yaml config.yaml
murid run --config ./config.yaml --dry-run
```

A dry run searches for matches and fetches the selected `.torrent` files, but does not add them to qBittorrent or download the ebooks. Omit `--dry-run` for a one-time sync. To keep Murid running on the cron schedule in your config, use:

```bash
murid schedule --config ./config.yaml
```

## Configuration

Use [config.example.yaml](config.example.yaml) as the complete configuration reference. Set `calibre.library` to either a local Calibre library path or a Calibre content server URL.
If upgrading an existing config, rename `calibre.library_path` or `calibre.server_url` to `calibre.library`.

### Environment Variables

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

## Configuration Reference

| Option                    | Description                           | Default     |
| ------------------------- | ------------------------------------- | ----------- |
| `hardcover_api_keys`      | List of hardcover api keys            | required    |
| `qbittorrent`             | qBittorrent connection                | required    |
| `calibre`                 | Calibre configuration                 | required    |
| `mam_id`                  | MyAnonamouse session cookie           | required    |
| `matcher_threshold`       | Fuzzy match sensitivity               | `0.92`      |
| `lang_codes`              | Torrent languages and tagged Hardcover alternate titles | `["ENG"]`   |
| `schedule`                | Cron expression                       | `0 * * * *` |
| `redact_sensitive_data`   | Hide secrets in logs                  | `true`      |
| `apprise`                 | Notifications via [Apprise](https://appriseit.com/getting-started/configuration/)   | `None`      |
| `filetypes`               | List of filetypes to support          | `["epub", "mobi", "azw3", "azw"]` |
| `blacklisted_torrent_ids` | List of MaM torrent id's to blacklist | `[]` |
| `torrent_timeout_seconds` | Seconds before a torrent is considered to have timed out | `1800` |

### Calibre

| Option                 | Description                     | Default     |
| ---------------------- | ------------------------------- | ----------- |
| `calibredb_executable` | Path to calibredb executable    | `calibredb` |
| `library`              | Local library path or content server URL | required |
| `server_username`      | Calibre content server username | `None`      |
| `server_password`      | Calibre content server password | `None`      |

### qBittorrent

| Option        | Description                  | Default  |
| ------------- | ---------------------------- | -------- |
| `host`        | Web UI host                  | required |
| `port`        | Web UI port                  | required |
| `username`    | Login username               | required |
| `password`    | Login password               | required |
| `verify_cert` | SSL verification             | `True`   |
| `category`    | Torrent category             | `murid`  |
| `mapping`     | Path mapping between systems; both paths are unset by default | both paths unset |

#### Path Mapping

If qBittorrent and murid see the download directory under different paths (for example,
when one or both are running in containers with different volume mounts), configure a path mapping. 

Set: 

- `qbittorrent.mapping.qbit_path` to the download path as seen by qBittorrent
- `qbittorrent.mapping.murid_path` to the corresponding path as seen by murid

For example, qBittorrent may save files to `/downloads` inside a container,
while murid accesses the same files at `/mnt/media/downloads` on the host. In that case:

```yaml
qbittorrent:
  mapping:
    qbit_path: /downloads
    murid_path: /mnt/media/downloads
```

This allows murid to correctly locate files reported by qBittorrent.

## Credentials

### Hardcover API Key

Generate one in your account settings:  
<https://hardcover.app/account/api>

### MyAnonamouse Cookie (mam_id)

Found in your MyAnonamouse security settings:  
<https://www.myanonamouse.net/preferences/index.php?view=security>

## Scheduling

Cron-based scheduling controls how often Murid runs.

Each scheduled run checks timed-out torrents again. It clears the timeout tag once
the book is confirmed in Calibre. If a completed download fails to import, Murid
marks it `murid_import_failed`; use `retry-import` after investigating the failure.

| Expression    | Meaning        |
| ------------- | -------------- |
| `0 * * * *`   | Every hour     |
| `0 */6 * * *` | Every 6 hours  |
| `0 3 * * *`   | Daily at 03:00 |
| `0 0 * * 0`   | Weekly         |

## Matching Logic

A book is considered already present if:

- ISBN matches, or
- Title/author similarity exceeds matcher_threshold

Otherwise, it will be searched and downloaded via MyAnonamouse.

## Disclaimer

This tool is intended for personal library automation and management.

Users are responsible for complying with applicable laws and the terms of service of all services used, including Hardcover, MyAnonamouse, and qBittorrent.

## License

MIT
