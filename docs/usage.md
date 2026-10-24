# Usage

[Back to README](../README.md)

Set your config once, then run commands with options after the command name:

```bash
export MURID_CONFIG_FILE=/path/to/config.yaml
murid run --dry-run
murid run
murid schedule
```

`--config /path/to/config.yaml` overrides the environment variable.
Use `murid <command> --help` for all options.

## Find, download, or import a book

```bash
murid list-missing
murid review-matches --unmatched
murid search-book "Children of Dune"         # Preview scores and rejection reasons
murid search-book "Children of Dune" --add   # Download, wait, and import
murid add-book "Children of Dune" /downloads/children-of-dune.epub
```

Manual commands resolve the title against your configured Hardcover lists,
including alternate titles and close spellings. They stop on ambiguous names or
an existing library match. Search previews do not fetch `.torrent` files;
`--add --dry-run` can fetch them without adding downloads.

To choose a candidate from the preview, use its MyAnonamouse ID:

```bash
murid search-book "Children of Dune" --torrent-id 123456
murid search-book "Children of Dune" --torrent-id 123456 --add
```

`--torrent-id` works for ebooks and audiobooks, including with `--dry-run`.
Candidates must still pass matching and configured filters. An absent or rejected
ID returns an error; without `--add`, the command only previews the selection.

An explicit ebook file overrides `filetypes` preferences; Calibre decides whether
it supports the format. Automatic imports still apply the format filter.

Inspection is read-only. Each requested medium is checked against its own library;
a library lookup error stops the command rather than treating the library as empty.

Inspection is read-only. Each requested medium is checked against its own library;
a library lookup error stops the command rather than treating the library as empty.

Inspection is read-only. Each requested medium is checked against its own library;
a library lookup error stops the command rather than treating the library as empty.

## Choose ebooks or audiobooks

Use `--ebooks` or `--audiobooks` to restrict `list-missing`, `review-matches`,
`run`, `schedule`, `retry-import`, `status`, or `test-connection` to one medium.
Without either flag, these commands operate across configured media. The flags are mutually exclusive.

```bash
murid list-missing --audiobooks
murid review-matches --ebooks --unmatched
murid run --audiobooks --dry-run
```

Media filters also apply to retries. Connection checks still include shared
services such as Hardcover and qBittorrent.

`search-book` and `add-book` also accept these flags and default to ebooks when
neither is given. `--media-type ebook|audiobook` remains supported on these two
commands as an alternative to the flags.

## Audiobook commands

Manual commands look up titles across your configured Hardcover lists. The media
flag chooses the destination and torrent preferences, independently of the list's
automatic media setting. The corresponding library must be configured.

```bash
murid search-book "Book title" --audiobooks --config ./config.yaml
murid search-book "Book title" --audiobooks --add --dry-run --config ./config.yaml
murid add-book "Book title" "/downloads/Book title" --audiobooks --dry-run --config ./config.yaml
murid add-book "Book title" "/downloads/Book title" --audiobooks --config ./config.yaml
```

Use one M4B file or a complete single-book MP3/M4B folder. A complete audiobook
stored as one MP3 must be placed in its own title-matched folder. Track/disc
structure is retained; supported disc folders are described in the
[configuration reference](configuration.md). Sources stay available for seeding.
If an import remains pending, repeat `add-book` to check it again without another
copy. The title must still be on a configured Hardcover list.

Run `test-connection` as the service user before scheduling imports, then test a
real import to confirm Audiobookshelf can read the shared files.

## Preview changes

`run`, `schedule`, `search-book`, `add-book`, and `retry-import` accept `--dry-run`.
Previews may fetch `.torrent` files, but do not add downloads, import books, scan
libraries, or change import tags.

## Inspect downloads and retry imports

```bash
murid status
murid retry-import
murid test-connection
murid test-notification
murid run --log-level debug
```

`retry-import` checks pending, timed-out, and failed downloads once, imports those
that are complete, and leaves unresolved downloads tagged. It never adds torrents.
`test-connection` checks each configured service independently and fails if any
check fails. `test-notification` sends through Apprise and fails if no destinations
are configured or delivery fails. Debug logging includes tracebacks.

## Scheduling

Start a persistent process to sync on the cron schedule in your configuration:

```bash
murid schedule --config ./config.yaml
```

The default is every hour. Configuration is reloaded before each scheduled run. Configuration is reloaded before each scheduled run. Configuration is reloaded before each scheduled run.
Set `schedule` in your YAML to change the interval:

Scheduled runs revisit unfinished downloads and imports, including those left by
an interrupted run. Use `status` to inspect them and `retry-import` after fixing
an import failure. See [recovery](configuration.md#torrent-metadata-and-recovery)
for tags and troubleshooting.

If several requested books share one torrent, use `add-book` to import additional
books from the completed download.

| Expression    | Meaning        |
| ------------- | -------------- |
| `0 * * * *`   | Every hour     |
| `0 */6 * * *` | Every 6 hours  |
| `0 3 * * *`   | Daily at 03:00 |
| `0 0 * * 0`   | Weekly         |

## Output formats

Every command accepts `--no-color`, `--log-level`, and `--format auto|plain|json`.
`auto` uses terminal layouts when connected to a terminal and unwrapped text when
redirected. `plain` always emits unwrapped text without terminal styling. `json`
emits JSON Lines: one object per result or summary on stdout, with diagnostics on
stderr (also JSON Lines). Each object has a `type` and readable `message`; result
objects also carry fields such as book metadata, scores, progress, and outcome
counts. Consumers should select records by `type` and ignore unfamiliar fields.
Search, import, and status records include `media_type` and `destination`; sync
and retry summaries include counts under `by_media`.
`print-config --format json` emits a `config` record containing the parsed,
redacted configuration. `NO_COLOR` and `--no-color` also apply to terminal help.

```bash
murid status --format json
murid list-missing --format plain > missing-books.txt
murid search-book "Dune" --no-color
```

## Exit codes and search failures

`run` reports a final sync summary and returns a nonzero exit code if imports
failed, downloads remain pending, a required lookup was skipped, or no acceptable
torrent was available for a missing book. Dry runs report planned imports and do
not count a pending download as a failure. `retry-import` also returns nonzero for
pending, failed, or skipped imports. Scheduled runs report unresolved outcomes and
continue to the next scheduled cycle. `test-notification` reports delivery success
or failure; no configured Apprise destinations is a failure. Detailed tracebacks
are available with `--log-level debug`.

A rejected search query produces a warning; Murid can still try alternate titles
and other books. Authentication and connection failures stop the sync.

## Command reference

| Command | Purpose |
| --- | --- |
| `run` | Sync once and exit |
| `schedule` | Sync repeatedly using the configured cron schedule |
| `list-missing` | List Hardcover requests missing from their respective libraries, with media type and destination |
| `review-matches` | Inspect library matches and scores for each medium; use `--matched` or `--unmatched` to filter |
| `search-book NAME` | Preview torrent candidates for a Hardcover book; use `--add` to download and import the selected torrent |
| `add-book NAME PATH` | Import a local ebook, or an audiobook with `--audiobooks` |
| `status` | Show Murid torrents and their download and import status |
| `retry-import` | Retry imports for tagged downloads |
| `test-connection` | Check access to each configured service |
| `test-notification` | Send a test notification through Apprise |
| `validate-config` | Validate a configuration file |
| `print-config` | Print the parsed configuration, with secrets redacted by default |
