{
  description = ''
    Murid automatically keeps your Calibre library in sync with your
    reading list on Hardcover, with help from myAnonamouse.
  '';

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
  } @ inputs: let
    project = pyproject-nix.lib.project.loadPyproject {
      projectRoot = ./.;
    };

    mkPackage = pkgs:
      pkgs.python3Packages.buildPythonApplication (
        project.renderers.buildPythonPackage {
          python = pkgs.python3;
        }
        // {
          pname = "murid";
          version = "0.2.0";

          nativeCheckInputs = [
            pkgs.python3Packages.pytestCheckHook
          ];

          meta.mainProgram = "murid";
        }
      );
  in
    flake-parts.lib.mkFlake {inherit inputs;} {
      imports = [
        inputs.git-hooks-nix.flakeModule
        ./nixosModule.nix
      ];

      systems = [
        "x86_64-linux"
        "aarch64-linux"
        "x86_64-darwin"
        "aarch64-darwin"
      ];

      flake.overlays.default = final: _: {
        murid = mkPackage final;
      };

      perSystem = {
        pkgs,
        config,
        ...
      }: {
        packages.default = mkPackage pkgs;

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
            echo 1>&2 "Welcome to the development shell for murid!"
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
            pkgs.pylint
            pkgs.python3Packages.pytest
            pkgs.python3Packages.pytest-cov
            pkgs.python3Packages.virtualenv
            pkgs.python3Packages.pip
            pythonEnv
          ];
        };
      };
    };
}
