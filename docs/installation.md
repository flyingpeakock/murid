# Installation

[Back to README](../README.md)

## Linux / macOS

```bash
git clone https://github.com/flyingpeakock/murid.git
cd murid

python -m venv .venv
source .venv/bin/activate

pip install .
```

## Windows

```powershell
git clone https://github.com/flyingpeakock/murid.git
cd murid

python -m venv .venv
.\.venv\Scripts\Activate.ps1

pip install .
```

## Development

### With Python

```bash
git clone https://github.com/flyingpeakock/murid.git
cd murid

python -m venv .venv
source .venv/bin/activate

pip install -e ".[dev]"
```

### With Nix

With Nix flakes enabled, enter the development shell from your checkout:

```bash
git clone https://github.com/flyingpeakock/murid.git
cd murid
nix develop
```

The shell provides Python and Murid's dependencies, Calibre, pytest, Ruff, and
Pylint, and installs the configured pre-commit hooks. No virtual environment is
needed. To run the source in your checkout and check your changes:

```bash
PYTHONPATH=src python -m murid.main --help
pytest
ruff check .
```

The `murid` command in the shell runs the Nix-built package. Use the Python command
above to run local edits, or `nix build` to rebuild the package. Run
`nix flake check` for the flake checks, including the NixOS module test on Linux.

### Continuous integration

The [CI workflow](../.github/workflows/ci.yml) runs on pull requests, pushes to
`main`, and manual dispatch. It checks Ruff and Pylint, runs tests with
coverage on Linux with Python 3.12, 3.13, and 3.14, and on Windows and macOS with
Python 3.14. The full test suite, including offline integration tests, runs on
each platform. Linux jobs also build a source distribution and wheel, smoke-test
the installed wheel, run the Nix flake checks, and build the Nix package.

To run the Python checks locally after installing the development dependencies:

```bash
ruff check src tests
pylint src --ignore=_version.py
python -m pytest --cov=murid --cov-report=term-missing
```

The default test run includes offline integration tests in `tests/integration`.
They exercise the CLI with real configuration, clients, matching, and services,
using fake HTTP responses, a stateful qBittorrent API stand-in, and a `calibredb`
stand-in launched through Python in a real subprocess. They require no shell,
credentials, or running external services.
Run only these tests with `python -m pytest -m integration`,
or exclude them with `python -m pytest -m 'not integration'`.

Every CLI command has integration coverage, including search previews and imports,
match review filters, status and retry handling, configuration validation and
redaction, connection checks, and Apprise notification delivery. Scheduler tests
use a controlled clock to verify configuration reloads and recovery after a failed
cycle without waiting for cron intervals.

GitHub Actions are pinned to commits; Dependabot checks for updates weekly.

## NixOS Flake

Add Murid as a flake input, then include its module in your NixOS module list. For example:

```nix
inputs.murid.url = "github:flyingpeakock/murid";

# In nixosSystem.modules:
[
  murid.nixosModules.default
  ({ ... }: {
    services.murid = {
      enable = true;
      environmentFile = "/etc/murid.env";
      config = {
        hardcover_api_keys = [{
          api_key = "!ENV HARDCOVER_API_KEY";
          reading_list.want-to-read = {};
        }];
        mam_id = "!ENV MAM_ID";
        calibre.library = "http://localhost:8080/#books";
        qbittorrent = {
          username = "admin";
          password = "!ENV QBITTORRENT_PASSWORD";
        };
      };
    };
  })
]
```

Put `HARDCOVER_API_KEY` (including the `Bearer ` prefix), `MAM_ID`, and `QBITTORRENT_PASSWORD` in `/etc/murid.env`. See [nixosModule.nix](../nixosModule.nix) for all module options.
The module starts `murid schedule` and accepts either an inline `services.murid.config`
or a path in `services.murid.configFile`. Set `environmentFile` when the selected
configuration uses `!ENV` secrets.

## Shared audiobook libraries on NixOS

Murid needs read access to completed downloads and read/write/traverse access to
both the shared library and staging directories (including the existing parent
when staging has not been created). Audiobookshelf needs read/traverse access to
the published library and its ancestors. The two processes may use different mount
paths, but they must expose the same library root. Staging must be on that same
filesystem and physically outside all scanned roots, including bind-mount aliases.
See [Audiobookshelf configuration](configuration.md#audiobookshelf).

The NixOS module accepts extra service groups and mount dependencies:

```nix
services.murid = {
  enable = true;
  configFile = "/etc/murid.yaml";
  environmentFile = "/etc/murid.env";
  supplementaryGroups = [ "media" "qbittorrent" ];
  requiresMountsFor = [ "/shared/audiobooks" "/shared/staging" "/downloads" ];
};
```

Use existing groups appropriate to your deployment and grant directory access
explicitly. The module does not chown or chmod your existing media directories.
For inline `config`, it automatically adds mount dependencies for
`audiobookshelf.library_path` and the explicit/default staging path. With
`configFile`, specify these paths through `requiresMountsFor`; also include the
completed-download mount when needed. Mount dependencies order startup but do not
create directories or grant access.

Run connection diagnostics with the actual service user and service environment
before enabling the schedule. An interactive user's successful import does not
establish that the service user can read the same downloads or write the mount.
The module does not change Audiobookshelf's mount configuration or API permissions.

### NixOS containers

Apply the service configuration inside `containers.<name>.config`, and use paths
as seen inside that container. The host must bind-mount a common parent containing
both the library and its private staging directory, and expose the completed
downloads as well. Mounting only the scanned library root cannot supply an
outside staging directory on the same filesystem.

For a container exposing the host's media volume as `/data`, an illustrative setup is:

```nix
containers.server = {
  bindMounts."/data" = {
    hostPath = "/opt/container/data";
    isReadOnly = false;
  };
  config = { ... }: {
    services.murid = {
      enable = true;
      user = "calibre";
      group = "multimedia";
      configFile = "/etc/murid.yaml";
      environmentFile = "/secrets/murid";
      requiresMountsFor = [ "/data" ];
    };
    systemd.tmpfiles.rules = [
      "d /data/.murid-staging-audiobooks 0700 calibre multimedia -"
    ];
  };
};
```

In that container's YAML, use `library_path: /data/media/audiobooks` and
`staging_path: /data/.murid-staging-audiobooks`; adapt paths and accounts to the
actual deployment. Keep `qbittorrent.mapping` consistent with the container's
view of completed downloads. A host-side localhost API check does not test access
from a container with private networking.

Keep staging owned by the account that runs imports. Journals are private files
and contain absolute source/library paths. A journal created by a host user is
not portable to a different container path or service account; use a separate
service-owned staging directory or explicitly migrate verified state during a
planned deployment. Completed library items remain discoverable by their work tags.

## Shell completion

To enable shell completion after a Python installation, add the line for your shell to its startup file:

```sh
# bash
eval "$(register-python-argcomplete murid)"

# zsh
eval "$(register-python-argcomplete --shell zsh murid)"

# fish
register-python-argcomplete --shell fish murid | source
```

The Nix package installs completion files for bash, zsh, and fish automatically.
The development shell also includes `murid`. Run `nix develop -c zsh` and complete `murid` by name.
For a direct path such as `./result/bin/murid`, register that path in your current zsh session:

```zsh
source ./result/share/zsh/site-functions/_murid
compdef -p _python_argcomplete '*/murid'
```
