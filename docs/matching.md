# Matching logic

[Back to README](../README.md)

```bash
murid review-matches --unmatched
murid search-book "Book title"
```

Use these to inspect library matches or torrent scores and rejection reasons.
`matcher_threshold` defaults to `0.92`; lowering it does not bypass the safeguards
below.

Murid compares identifiers first, then title, author, and series metadata.
Calibre uses the rules below; Audiobookshelf also uses Hardcover work tags and
excludes audiobook edition ISBNs and ASINs from ebook-metadata comparisons.

## Scoring

- **Identifiers:** A shared valid ISBN or external catalog ID gives a score of
  `1.0`. ISBN checksums are validated, and ISBN-10 values are converted to ISBN-13.
  Catalog names and IDs are normalized so supported URL and raw-ID forms can
  match. A shared identifier is rejected if both books have titles and authors,
  title similarity is below `0.35`, and no authors match.
- **Titles:** Comparisons ignore case, punctuation, extra whitespace, and leading
  English articles (`a`, `an`, `the`), while preserving Unicode letters and
  numbers. Murid compares full titles and alternate titles, plus variants that
  remove recognized subtitles, series prefixes, volume annotations, author
  suffixes, or omnibus labels. Alternate and shortened variants receive lower
  confidence scores.
- **Authors:** Comparisons recognize `Surname, Given` ordering, initials, close
  spellings, and names embedded in a combined author field. Single-word names
  also match whole tokens in combined fields containing at least three words;
  single initials are excluded. Extra contributors
  are tolerated, with a small score reduction.

Without a shared identifier, the overall score is `0.85 × title similarity +
0.15 × author similarity`. If either book has no authors, it is `0.94 × title
similarity` instead. Matching series names and positions add `0.04` when title
similarity is at least `0.85`, up to a maximum score of `1.0`.

Metadata matches must reach `matcher_threshold` (default `0.92`) and a title
similarity of at least `0.85`. They are rejected when both books have authors but
none match, when positions differ within the same series, or when normalized
titles with the same word count differ by exactly one word (unless a main or
alternate title matches exactly). Lowering the threshold does not bypass these safeguards.

Qualifying Hardcover–Calibre pairs are assigned in descending score order, with
each book used at most once. Unmatched Hardcover books are searched on
MyAnonamouse. Torrent candidates use the same matching rules, together with the
configured language, file type, and blacklist filters; see
[torrent preferences](configuration.md#torrent-preferences-and-imported-metadata) for ranking.
