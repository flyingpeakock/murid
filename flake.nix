{
  description = "Search for books from Hardcover on MaM and add them to calibre";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

    pyproject-nix.url = "github:pyproject-nix/pyproject.nix";
    pyproject-nix.inputs.nixpkgs.follows = "nixpkgs";

    git-hooks-nix.url = "github:cachix/git-hooks.nix";
    git-hooks-nix.inputs.nixpkgs.follows = "nixpkgs";

    flake-parts.url = "github:hercules-ci/flake-parts";
  };

  outputs = {
    pyproject-nix,
    flake-parts,
    ...
  } @ inputs:
    flake-parts.lib.mkFlake {inherit inputs;} {
      imports = [inputs.git-hooks-nix.flakeModule];

      systems = [
        "x86_64-linux"
        "aarch64-linux"
        "x86_64-darwin"
        "aarch64-darwin"
      ];

      perSystem = {
        pkgs,
        config,
        ...
      }: let
        project = pyproject-nix.lib.project.loadPyproject {
          projectRoot = ./.;
        };
      in {
        packages.default = pkgs.python3Packages.buildPythonApplication (
          project.renderers.buildPythonPackage {
            python = pkgs.python3;
          }
          // {
            pname = "HardcoverHarvester";
            version = "0.0.0";

            nativeCheckInputs = [
              pkgs.python3Packages.pytestCheckHook
            ];

            meta.mainProgram = "HardcoverHarvester";
          }
        );

        pre-commit.settings.hooks = {
          alejandra.enable = true;
          deadnix.enable = true;
          flake-checker.enable = true;
          statix.enable = true;
          ruff.enable = true;
        };

        devShells.default = pkgs.mkShell {
          shellHook = ''
            ${config.pre-commit.installationScript}
            echo 1>&2 "Welcome to the development shell for HardcoverHarvester!"
          '';
          packages = let
            python = pkgs.python3;
            arg = project.renderers.withPackages {inherit python;};
            pythonEnv = python.withPackages arg;
          in [
            pkgs.calibre
            pkgs.alejandra
            pkgs.hatch
            pkgs.pyenv
            pkgs.ruff
            pkgs.python3Packages.pytest
            pythonEnv
          ];
        };
      };
    };
}
