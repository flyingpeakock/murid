# Installation

[Back to README](../README.md)

[Linux / macOS](#linux--macos) · [Windows](#windows) · [NixOS](#nixos-flake) ·
[Shell completion](#shell-completion) · [Development](#development)

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
        hardcover_accounts = [{
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
before enabling the schedule.

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

### Checks and CI

```bash
ruff check src tests
pylint src --ignore=_version.py
python -m pytest --cov=murid --cov-report=term-missing
```

Tests include offline CLI integration tests; no credentials or running services
are needed. Use `python -m pytest -m integration` to run only those tests, or
`python -m pytest -m 'not integration'` to exclude them.

[CI](../.github/workflows/ci.yml) runs lint, the full test suite on Linux
(Python 3.12–3.14), Windows and macOS (3.14), package build/install smoke checks,
and Nix package/module checks.
