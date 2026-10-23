# Usage

[Back to README](../README.md)

Murid uses a command followed by its options. Run `murid --help` to list commands,
or `murid <command> --help` for command-specific options. Put `--config` after the
command, as in the examples below.

| Command | Purpose |
| --- | --- |
| `run` | Sync once and exit |
| `schedule` | Sync repeatedly using the configured cron schedule |
| `list-missing` | List Hardcover requests missing from their respective libraries, with media type and destination |
| `review-matches` | Inspect library matches and scores for each medium; use `--matched` or `--unmatched` to filter |
| `search-book NAME` | Preview torrent candidates for a Hardcover book; use `--add` to download and import the selected torrent |
| `add-book NAME PATH` | Import an ebook file with metadata from Hardcover |
| `status` | Show Murid torrents and their download and import status |
| `retry-import` | Retry imports for tagged downloads |
| `test-connection` | Check access to each configured service |
| `test-notification` | Send a test notification through Apprise |
| `validate-config` | Validate a configuration file |
| `print-config` | Print the parsed configuration, with secrets redacted by default |

## Output formats

Every command accepts `--no-color`, `--log-level`, and `--format auto|plain|json`.
`auto` uses terminal layouts when connected to a terminal and unwrapped text when
redirected. `plain` always emits unwrapped text without terminal styling. `json`
emits JSON Lines: one object per result or summary on stdout, with diagnostics on
stderr (also JSON Lines). Each object has a `type` and readable `message`; result
objects also carry fields such as book metadata, scores, progress, and outcome
counts. Consumers should select records by `type` and ignore unfamiliar fields.
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

Murid replaces punctuation and search operators in generated queries with spaces,
preserving Unicode letters, numbers, and combining marks. Queries without
searchable words are skipped. Rejected title queries are reported
as warnings; alternate titles and other books can still be processed. Books whose
title queries all fail are counted as search failures, rather than empty results.
Authentication and connection failures still stop the sync.

## Review matches and validate configuration

For example, inspect book matches or validate a configuration before syncing:

```bash
murid review-matches --unmatched --config ./config.yaml
murid validate-config --config ./config.yaml
```

`list-missing` and `review-matches` compare ebook requests with Calibre and
audiobook requests with Audiobookshelf. A book requested in both formats is
checked independently in each library. Inspection is read-only, and a library
lookup error stops the command rather than reporting that library as empty.
Audiobook discovery and imports remain unavailable during the current
implementation phase; audiobook configurations can be inspected but cannot yet
run acquisition or retries.

## Import a local ebook

To import a file that Murid could not select automatically, give the book name from your
Hardcover Want to Read list and the path to the ebook file:

```bash
murid add-book "Children of Dune" /path/to/children-of-dune.epub --config ./config.yaml
```

Murid matches the name against your Hardcover books, including close spellings and alternate
titles, then uses the matched title, authors, and series when adding the file to Calibre.
It stops if the name is ambiguous or the book already exists in Calibre.
The explicit file overrides automatic `filetypes` preferences; Calibre determines
whether it supports the selected format. Automatic torrent imports still apply
the configured format filter.

## Inspect downloads and retry imports

To inspect downloads in Murid's configured qBittorrent category, including torrents
tagged for a timeout or failed Calibre import, run:

```bash
murid status --config ./config.yaml
```

To retry importing completed Murid downloads tagged as pending, timed out, or failed,
without searching for or adding new torrents, run:

```bash
murid retry-import --config ./config.yaml
```

It checks tagged torrents once, reports downloads still in progress, and leaves failed
imports tagged for further investigation. It exits with a nonzero status if any
tagged torrent still needs attention.

## Check connections

To check access to Hardcover, Calibre, MyAnonamouse, and qBittorrent, run:

```bash
murid test-connection --config ./config.yaml
```

Each service is checked independently. The command exits with a nonzero status if
any check fails.

## Preview and download a book

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

## Scheduling

Start a persistent process to sync on the cron schedule in your configuration:

```bash
murid schedule --config ./config.yaml
```

The default is every hour. For a single sync, use `murid run`; add `--dry-run` to
preview matches and fetch selected `.torrent` files without adding torrents or
downloading ebooks. See the [quick start](../README.md#quick-start) for initial setup.

Downloads receive a persistent `murid_pending` tag when added to qBittorrent.
Each scheduled run checks pending and timed-out torrents again, including downloads
left behind by an interrupted run. Once the book is confirmed in Calibre, Murid
clears the pending and timeout tags. If a completed download fails to import, Murid
marks it `murid_import_failed`; use `retry-import` after investigating the failure.
Recovery uses the MyAnonamouse ID in the torrent comment to identify the download,
then matches its title, authors, and identifiers against the configured Hardcover
Want to Read lists. A unique match supplies the Hardcover ID and book metadata
used for file selection and import. Books missing from those lists or matching
multiple Hardcover works are reported as skipped and remain tagged for attention;
check the reading lists or import an individual ebook with `add-book`.

If two requested books resolve to the same torrent hash in a batch, Murid imports
the first book and reports the second as a failure instead of replacing the first.
Use `add-book` to import another book from the completed download.

| Expression    | Meaning        |
| ------------- | -------------- |
| `0 * * * *`   | Every hour     |
| `0 */6 * * *` | Every 6 hours  |
| `0 3 * * *`   | Daily at 03:00 |
| `0 0 * * 0`   | Weekly         |
