from types import SimpleNamespace

from murid.services.status_service import print_status


def test_status_reports_issues_first_and_progress(capsys):
    torrents = [
        SimpleNamespace(name="Ready", progress=1.0, state="uploading", tags=""),
        SimpleNamespace(
            name="Dune", progress=0.5, state="downloading", tags="other, murid_timeout"
        ),
        SimpleNamespace(
            name="Foundation", progress=1.0, state="stalledUP", tags="murid_import_failed"
        ),
    ]
    client = SimpleNamespace(category="murid", get_torrents=lambda: torrents)

    print_status(client)

    lines = capsys.readouterr().out.splitlines()
    assert lines == [
        "Murid torrents: 3 (category 'murid')",
        "- Dune |  50% | downloading | timed out",
        "- Foundation | 100% | seeding (idle) | import failed",
        "- Ready | 100% | seeding",
        "Needs attention: 2. Inspect qBittorrent, then run murid retry-import.",
    ]


def test_status_empty_category(capsys):
    client = SimpleNamespace(category="murid", get_torrents=lambda: [])

    print_status(client)

    assert capsys.readouterr().out == "Murid torrents: 0 (category 'murid')\n"
