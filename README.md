# HardcoverHarvester

HardcoverHarvester automatically keeps your Calibre library in sync with your reading list on Hardcover.

It periodically:

1. Fetches books from one or more Hardcover accounts.
2. Compares them against your existing Calibre library.
3. Searches MyAnonamouse (MaM) for missing ebooks.
4. Downloads matching torrents through qBittorrent.
5. Imports completed downloads into Calibre.

The goal is to provide a mostly hands-off workflow for acquiring books you've added to your Hardcover "Want to Read" list.

---

## Features

- Multiple Hardcover user support
- Automatic matching against existing Calibre books
- ISBN and title/author matching
- Configurable fuzzy matching threshold
- Scheduled harvesting using cron expressions
- MyAnonamouse integration
- qBittorrent integration
- Automatic Calibre imports
- Dry-run mode for testing
- Environment variable support for secrets

---

## How It Works

```text
Hardcover
    ↓
Fetch reading list
    ↓
Compare against Calibre library
    ↓
Search MyAnonamouse
    ↓
Download missing books
    ↓
qBittorrent
    ↓
Import completed downloads
    ↓
Calibre
```

---

## Requirements

- Python 3.12+
- Calibre
- qBittorrent
- A Hardcover API key
- A MyAnonamouse account

---

## Installation

### Using pip

```bash
pip install .
```

### Development Installation

```bash
git clone <repository-url>
cd HardcoverHarvester

pip install -e ".[dev]"
```

---

## Configuration

Create a configuration file:

```yaml
users:
  - id: 12345
    api_key: "your-hardcover-api-key"

calibre_db_path: "/path/to/Calibre Library/metadata.db"

mam_id: "your-mam-session-cookie"

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
  category: "hardcoverharvester"
```

### Environment Variables

Sensitive values can be loaded from environment variables:

```yaml
users:
  - id: 12345
    api_key: !ENV HARDCOVER_API_KEY

mam_id: !ENV MAM_ID
```

Example:

```bash
export HARDCOVER_API_KEY="..."
export MAM_ID="..."
```

---

## Configuration Options

| Option | Description | Default |
|----------|-------------|----------|
| `users` | Hardcover users to monitor | Required |
| `calibre_db_path` | Path to Calibre `metadata.db` | Required |
| `mam_id` | MyAnonamouse session cookie | Required |
| `matcher_threshold` | Fuzzy match threshold | `0.85` |
| `lang_codes` | Allowed language codes | `["ENG"]` |
| `schedule` | Cron schedule | `0 * * * *` |
| `redact_sensitive_data` | Hide secrets in logs | `true` |

### qBittorrent

| Option | Description |
|----------|-------------|
| `host` | qBittorrent URL |
| `port` | qBittorrent WebUI port |
| `username` | Username |
| `password` | Password |
| `verify_cert` | Verify SSL certificates |
| `category` | Category assigned to downloads |

---

## Finding Your Credentials

### Hardcover User ID

Your Hardcover user ID can be obtained from the Hardcover API or account information.

### Hardcover API Key

Generate an API key from your Hardcover account settings.

### MyAnonamouse `mam_id`

Log into MyAnonamouse and copy the `mam_id` cookie value from your browser.

---

## Usage

### Run Normally

```bash
HardcoverHarvester --config config.yaml
```

### Dry Run

See what would be downloaded without actually downloading anything:

```bash
HardcoverHarvester --config config.yaml --dry-run
```

### Debug Logging

```bash
HardcoverHarvester \
  --config config.yaml \
  --log-level DEBUG
```

---

## Scheduling

Scheduling is controlled by a cron expression.

Examples:

| Schedule | Description |
|-----------|-------------|
| `0 * * * *` | Every hour |
| `0 */6 * * *` | Every 6 hours |
| `0 3 * * *` | Daily at 03:00 |
| `0 0 * * 0` | Weekly |

---

## Matching Logic

Books are considered already owned when:

- ISBNs match, or
- Title/author similarity exceeds the configured threshold.

Books not found in Calibre are searched on MyAnonamouse.

---

## Logging

Supported log levels:

- `DEBUG`
- `INFO`
- `WARNING`
- `ERROR`
- `CRITICAL`

Example:

```bash
HardcoverHarvester \
  --config config.yaml \
  --log-level DEBUG
```

---

## Development

Run tests:

```bash
pytest
```

Run coverage:

```bash
pytest --cov
```

Lint:

```bash
ruff check .
```

---

## Disclaimer

This project is intended for personal library management and automation.

Users are responsible for ensuring their usage complies with the terms of service of Hardcover, MyAnonamouse, qBittorrent, and any applicable laws.

---

## License

MIT License
