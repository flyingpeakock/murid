# murid

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

## Configuration

Create a yaml configuration file:

```yaml
users:
  - id: 12345
    api_key: your-hardcover-api-key

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
```

### Environment Variables

Sensitive information can be injected via environment variables:

```yaml
users:
  - id: 12345
    api_key: !ENV HARDCOVER_API_KEY

mam_id: !ENV MAM_ID
```

```bash
export HARDCOVER_API_KEY="..."
export MAM_ID="..."
```

## Configuration Reference

| Option                  | Description                 | Default     |
| ----------------------- | --------------------------- | ----------- |
| `users`                 | Hardcover accounts          | required    |
| `qbittorrent`           | qBittorrent connection      | required    |
| `calibre_db_path`       | Path to Calibre metadata.db | required    |
| `calibredb_executable`  | Path to calibredb           | `calibredb` |
| `mam_id`                | MyAnonamouse session cookie | required    |
| `matcher_threshold`     | Fuzzy match sensitivity     | `0.7`       |
| `lang_codes`            | Allowed languages           | `["ENG"]`   |
| `schedule`              | Cron expression             | `0 * * * *` |
| `redact_sensitive_data` | Hide secrets in logs        | `true`      |
| `apprise`               | Notifications via [Apprise](https://appriseit.com/getting-started/configuration/)   | `None`      |

### Users

| Option    | Description       | Default  |
| --------- | ----------------- | -------- |
| `id`      | Hardcover user ID | required |
| `api_key` | Hardcover API key | required |


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

## Credentials

### Hardcover User ID

Available via your Hardcover account or API response

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
