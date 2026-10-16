# Configuration

[Back to README](../README.md)

Use [config.example.yaml](../config.example.yaml) as the complete configuration reference. Set `calibre.library` to either a local Calibre library path or a Calibre content server URL.
If upgrading an existing config, rename `calibre.library_path` or `calibre.server_url` to `calibre.library`.

## Configuration reference

Defaults below apply to the YAML configuration. Required values must be supplied.

| Option | Description | Default |
| --- | --- | --- |
| `hardcover_api_keys` | List of Hardcover API tokens, each starting with `Bearer ` | required |
| `qbittorrent` | qBittorrent connection settings (see below) | required connection values |
| `calibre` | Calibre settings (see below) | library required |
| `mam_id` | MyAnonamouse session cookie | required |
| `matcher_threshold` | Match confidence threshold from `0.0` to `1.0`; see [matching logic](matching.md) | `0.92` |
| `lang_codes` | Torrent languages and language-tagged Hardcover titles used for search | `["ENG"]` |
| `schedule` | Cron expression for scheduled syncs | `0 * * * *` |
| `redact_sensitive_data` | Hide secrets in logs and config dumps | `true` |
| `apprise` | List of Apprise notification URLs | `null` (disabled) |
| `filetypes` | Accepted ebook formats, most preferred first | `["epub", "mobi", "azw3", "azw"]` |
| `blacklisted_torrent_ids` | MyAnonamouse torrent IDs to exclude | `[]` |
| `torrent_timeout_seconds` | Seconds to wait for a torrent to complete | `1800` |

### Calibre

These options belong under `calibre`.

| Option | Description | Default |
| --- | --- | --- |
| `calibredb_executable` | Path to the `calibredb` executable | `calibredb` |
| `library` | Local library path or Calibre content server URL | required |
| `server_username` | Calibre content server username | `null` |
| `server_password` | Calibre content server password | `null` |

### qBittorrent

These options belong under `qbittorrent`.

| Option | Description | Default |
| --- | --- | --- |
| `host` | Web UI host | required |
| `port` | Web UI port | required |
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

For optional notifications, configure destination URLs using [Apprise](https://appriseit.com/getting-started/configuration/).
