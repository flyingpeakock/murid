# murid

**Definition (Webster's Dictionary)**  
*Murid* (noun): of or relating to a family (Muridae) comprising the typical mice and rats and often those rodents classified as cricetids

---

Murid automatically syncs your reading list from Hardcover with your Calibre library and fetches missing ebooks using MyAnonamouse.

It is designed to automate the full pipeline from “want to read” → “available in Calibre”.

## Overview

Murid periodically:

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

## Requirments

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

```
{
  inputs.murid.url = "github:flyingpeakock/murid";
}
```

Module options are defined in [nixosModule.nix](nixosModule.nix)

## Usage

1. Mark books as "Want to Read" on hardcover.
2. Run this script.
3. Start reading

```
Usage: murid [-h] [--version] [--log-level {DEBUG,INFO,WARNING,ERROR,CRITICAL}] [--dry-run] [--schedule] [--test-notification] [--config CONFIG_FILE]

Murid automatically keeps your Calibre library in sync with your reading list on Hardcover, with help from myAnonamouse.

Options:
  -h, --help            show this help message and exit
  --version, -v         show program's version number and exit
  --log-level, -l {DEBUG,INFO,WARNING,ERROR,CRITICAL}
                        logging level (default: INFO)
  --dry-run, -d         see what will be downloaded without actually downloading (default: False)
  --schedule, -s        run murid on a schedule (default: False)
  --test-notification   send a test notification and then exit (default: False)
  --config, -c CONFIG_FILE
                        path to config file (default: $XDG_CONFIG_HOME/murid/config.yaml)

```

## Configuration

Create a yaml configuration file:

```yaml
hardcover_api_keys:
  - Bearer your-hardcover-api-key

calibre_db_path: "/path/to/Calibre Library/metadata.db"

mam_id: your-mam-session-cookie

matcher_threshold: 0.85

lang_codes:
  - ENG

schedule: "0 * * * *"

qbittorrent:
  host: "http://localhost"
  port: 8080
  username: "admin"
  password: "password"
  verify_cert: true
  category: murid
  mapping:
    qbit_path: /downloads/completed
    murid_path: /data/downloads/completed

filetypes:
  - epub
  - mobi
  - azw3
```

### Environment Variables

Sensitive information can be injected via environment variables:

```yaml
hardcover_api_keys:
  - !ENV HARDCOVER_API_KEY1
  - !ENV HARDCOVER_API_KEY2

mam_id: !ENV MAM_ID
```

```bash
export HARDCOVER_API_KEY1="..."
export HARDCOVER_API_KEY2="..."
export MAM_ID="..."
```

## Configuration Reference

| Option                    | Description                           | Default     |
| ------------------------- | ------------------------------------- | ----------- |
| `hardcover_api_keys`      | List of hardcover api keys            | required    |
| `qbittorrent`             | qBittorrent connection                | required    |
| `calibre_db_path`         | Path to Calibre metadata.db           | required    |
| `calibredb_executable`    | Path to calibredb                     | `calibredb` |
| `mam_id`                  | MyAnonamouse session cookie           | required    |
| `matcher_threshold`       | Fuzzy match sensitivity               | `0.7`       |
| `lang_codes`              | Allowed languages                     | `["ENG"]`   |
| `schedule`                | Cron expression                       | `0 * * * *` |
| `redact_sensitive_data`   | Hide secrets in logs                  | `true`      |
| `apprise`                 | Notifications via [Apprise](https://appriseit.com/getting-started/configuration/)   | `None`      |
| `filetypes`               | List of filetypes to support          | `["epub", "mobi", "azw3", "azw"]` |
| `blacklisted_torrent_ids` | List of MaM torrent id's to blacklist | `[]` |
| `torrent_timeout_seconds` | Seconds before a torrent is considered to have timed out | `1800` |

### qBittorrent

| Option        | Description                  | Default  |
| ------------- | ---------------------------- | -------- |
| `host`        | Web UI host                  | required |
| `port`        | Web UI port                  | required |
| `username`    | Login username               | required |
| `password`    | Login password               | required |
| `verify_cert` | SSL verification             | `True`   |
| `category`    | Torrent category             | `murid`  |
| `mapping`     | Path mapping between systems | `None`   |

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
