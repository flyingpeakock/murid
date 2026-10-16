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
        hardcover_api_keys = [ "!ENV HARDCOVER_API_KEY" ];
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
