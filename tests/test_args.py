from pathlib import Path

import pytest

from murid import __version__
from murid.args import MuridArgumentParser


@pytest.fixture(autouse=True)
def clear_config_file_environment(monkeypatch):
    """Keep parser defaults independent of the developer shell environment."""
    monkeypatch.delenv("MURID_CONFIG_FILE", raising=False)


def test_default_config_path_linux(monkeypatch):
    monkeypatch.setattr("platform.system", lambda: "Linux")
    monkeypatch.setenv("XDG_CONFIG_HOME", "/tmp/config")

    assert MuridArgumentParser.default_config_path() == Path("/tmp/config/murid/config.yaml")


def test_config_path_uses_environment_variable(monkeypatch):
    monkeypatch.setenv("MURID_CONFIG_FILE", "/tmp/murid.yaml")
    monkeypatch.setattr("platform.system", lambda: "Plan9")

    assert MuridArgumentParser.default_config_path() == Path("/tmp/murid.yaml")


def test_cli_config_path_takes_precedence_over_environment(monkeypatch):
    monkeypatch.setenv("MURID_CONFIG_FILE", "/tmp/from-environment.yaml")

    args = MuridArgumentParser("test").parse_args(["run", "--config", "/tmp/from-cli.yaml"])

    assert args.config_file == "/tmp/from-cli.yaml"


def test_default_config_path_linux_fallback(monkeypatch):
    monkeypatch.setattr("platform.system", lambda: "Linux")
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setattr(Path, "home", lambda: Path("/home/test"))

    assert MuridArgumentParser.default_config_path() == Path("/home/test/.config/murid/config.yaml")


def test_default_config_path_macos(monkeypatch):
    monkeypatch.setattr("platform.system", lambda: "Darwin")
    monkeypatch.setattr(Path, "home", lambda: Path("/Users/test"))

    assert MuridArgumentParser.default_config_path() == Path(
        "/Users/test/Library/Application Support/murid/config.yaml"
    )


def test_default_config_path_windows(monkeypatch):
    monkeypatch.setattr("platform.system", lambda: "Windows")
    monkeypatch.setenv("APPDATA", r"C:\Users\Test\AppData\Roaming")

    path = MuridArgumentParser.default_config_path()

    assert path == Path(r"C:\Users\Test\AppData\Roaming") / "murid" / "config.yaml"


def test_default_config_path_unsupported(monkeypatch):
    monkeypatch.setattr("platform.system", lambda: "Plan9")

    with pytest.raises(RuntimeError):
        MuridArgumentParser.default_config_path()


def test_arg_parser_defaults():
    parser = MuridArgumentParser("test")

    args = parser.parse_args(["run"])

    assert args.log_level == "INFO"
    assert args.dry_run is False
    assert args.command == "run"


@pytest.mark.parametrize("flag", ["--version", "-v"])
def test_version_exits_before_command_is_required(flag, capsys):
    parser = MuridArgumentParser("test")

    with pytest.raises(SystemExit) as exit_info:
        parser.parse_args([flag])

    assert exit_info.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_arg_parser_flags():
    parser = MuridArgumentParser("test")

    args = parser.parse_args(
        [
            "run",
            "--log-level",
            "debug",
            "--dry-run",
            "--config",
            "/tmp/config.yaml",
        ]
    )

    assert args.log_level == "DEBUG"
    assert args.dry_run is True
    assert args.config_file == "/tmp/config.yaml"


@pytest.mark.parametrize("command", ["run", "status", "validate-config"])
def test_commands_accept_no_color(command):
    args = MuridArgumentParser("test").parse_args([command, "--no-color"])

    assert args.no_color is True


def test_add_book_arguments():
    args = MuridArgumentParser("test").parse_args(
        ["add-book", "Dune", "/tmp/dune.epub", "--config", "/tmp/config.yaml"]
    )

    assert args.command == "add-book"
    assert args.name == "Dune"
    assert args.path == "/tmp/dune.epub"
    assert args.config_file == "/tmp/config.yaml"


def test_status_arguments():
    args = MuridArgumentParser("test").parse_args(["status", "--config", "/tmp/config.yaml"])

    assert args.command == "status"
    assert args.config_file == "/tmp/config.yaml"


def test_search_book_arguments():
    args = MuridArgumentParser("test").parse_args(
        ["search-book", "Dune", "--config", "/tmp/config.yaml"]
    )

    assert args.command == "search-book"
    assert args.name == "Dune"
    assert args.add is False
    assert args.log_level == "INFO"
    assert args.config_file == "/tmp/config.yaml"


def test_search_book_add_flag():
    args = MuridArgumentParser("test").parse_args(
        ["search-book", "Dune", "--add", "--log-level", "debug"]
    )

    assert args.add is True
    assert args.log_level == "DEBUG"


def test_retry_import_arguments():
    args = MuridArgumentParser("test").parse_args(
        ["retry-import", "--config", "/tmp/config.yaml", "--log-level", "debug"]
    )

    assert args.command == "retry-import"
    assert args.config_file == "/tmp/config.yaml"
    assert args.log_level == "DEBUG"


def test_connection_arguments():
    args = MuridArgumentParser("test").parse_args(
        ["test-connection", "--config", "/tmp/config.yaml"]
    )

    assert args.command == "test-connection"
    assert args.config_file == "/tmp/config.yaml"
    assert args.log_level == "INFO"


@pytest.mark.parametrize(
    "command",
    [
        "run",
        "schedule",
        "test-notification",
        "test-connection",
        "list-missing",
        "status",
        "retry-import",
        "review-matches",
        "validate-config",
        "print-config",
    ],
)
def test_commands_accept_config_after_command(command):
    args = MuridArgumentParser("test").parse_args([command, "--config", "/tmp/murid.yaml"])

    assert args.command == command
    assert args.config_file == "/tmp/murid.yaml"


def test_schedule_accepts_dry_run_and_log_level():
    args = MuridArgumentParser("test").parse_args(
        ["schedule", "--dry-run", "--log-level", "warning"]
    )

    assert args.dry_run is True
    assert args.log_level == "WARNING"


def test_review_matches_filter_is_mutually_exclusive():
    parser = MuridArgumentParser("test")

    assert parser.parse_args(["review-matches", "--unmatched"]).matched is False
    assert parser.parse_args(["review-matches", "--matched"]).matched is True
    with pytest.raises(SystemExit):
        parser.parse_args(["review-matches", "--matched", "--unmatched"])


@pytest.mark.parametrize("command", ["search-book", "add-book"])
def test_manual_media_type_defaults_and_audiobook_choice(command):
    arguments = [command, "Dune"] + (["/tmp/audio"] if command == "add-book" else [])
    parser = MuridArgumentParser()
    assert parser.parse_args(arguments).media_type == "ebook"
    args = parser.parse_args(arguments + ["--media-type", "audiobook", "--dry-run"])
    assert args.media_type == "audiobook" and args.dry_run
    with pytest.raises(SystemExit):
        parser.parse_args(arguments + ["--media-type", "video"])
