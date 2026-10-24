from types import SimpleNamespace

from murid.services.status_service import print_status


def test_status_reports_issues_first_and_progress(capsys):
    torrents = [
        SimpleNamespace(name="Ready", progress=1.0, state="uploading", tags=""),
        SimpleNamespace(
            name="Dune", progress=0.5, state="downloading", tags="other, murid-timeout"
        ),
        SimpleNamespace(
            name="Foundation", progress=1.0, state="stalledUP", tags="murid-import-failed"
        ),
    ]
    client = SimpleNamespace(category="murid", get_torrents=lambda: torrents)

    print_status(client)

    lines = capsys.readouterr().out.splitlines()
    assert lines == [
        "Murid torrents: 3 (category 'murid')",
        "- Dune [ebook → Calibre] |  50% | downloading | timed out",
        "- Foundation [ebook → Calibre] | 100% | seeding (idle) | import failed",
        "- Ready [ebook → Calibre] | 100% | seeding",
        "Needs attention: 2. Inspect qBittorrent, then run murid retry-import.",
    ]


def test_status_empty_category(capsys):
    client = SimpleNamespace(category="murid", get_torrents=lambda: [])

    print_status(client)

    assert capsys.readouterr().out == "Murid torrents: 0 (category 'murid')\n"


def test_filtered_status_counts_selected_media_and_keeps_unknown_identities_visible(capsys):
    torrents = [
        SimpleNamespace(name="Legacy", progress=1, state="uploading", tags=""),
        SimpleNamespace(
            name="Audio",
            progress=1,
            state="uploading",
            tags="murid_media_audiobook,murid_hardcover_42",
        ),
        SimpleNamespace(
            name="Invalid",
            progress=1,
            state="uploading",
            tags="murid_media_audiobook,murid_media_ebook",
        ),
    ]
    client = SimpleNamespace(category="murid", get_torrents=lambda: torrents)
    print_status(client, media_type="audiobook")
    output = capsys.readouterr().out
    assert "Murid torrents: 2" in output
    assert "- Legacy" not in output
    assert "- Audio" in output
    assert "- Invalid" in output and "invalid request identity" in output
