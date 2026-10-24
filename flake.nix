{
  description = ''
    Murid automatically keeps your Calibre library in sync with your
    reading list on Hardcover, with help from myAnonamouse.
  '';

  inputs = {
    nixpkgs.url = "https://channels.nixos.org/nixos-unstable/nixexprs.tar.zst";

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
          version = "0.8.0";

          nativeCheckInputs = [
            pkgs.python3Packages.pytestCheckHook
          ];

          nativeBuildInputs = [
            pkgs.installShellFiles
            pkgs.python3Packages.argcomplete
          ];

          postInstall = ''
            register-python-argcomplete --shell bash murid > murid.bash
            register-python-argcomplete --shell zsh murid > _murid
            register-python-argcomplete --shell fish murid > murid.fish
            installShellCompletion murid.bash _murid murid.fish
          '';

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
        system,
        ...
      }: let
        python = pkgs.python3;
        pythonPackages = project.renderers.withPackages {inherit python;};
        pythonEnv = python.withPackages pythonPackages;
        pylintEnv = python.withPackages (
          packages:
            pythonPackages packages
            ++ [packages.pylint]
        );
      in {
        packages.default = mkPackage pkgs;

        checks =
          if pkgs.stdenv.hostPlatform.isLinux
          then {
            nixos-module = import ./tests/nixos-module.nix {
              inherit pkgs system;
              module = inputs.self.nixosModules.default;
              inherit (inputs) nixpkgs;
            };
          }
          else {};

        pre-commit.settings.hooks = {
          alejandra.enable = true;
          deadnix.enable = true;
          flake-checker.enable = true;
          pylint = {
            enable = true;
            package = pylintEnv;
            pass_filenames = false;
          };
          statix.enable = true;
          ruff.enable = true;
        };

        devShells.default = pkgs.mkShell {
          shellHook = ''
            export FPATH="${mkPackage pkgs}/share/zsh/site-functions''${FPATH:+:$FPATH}"
            ${config.pre-commit.installationScript}
            echo 1>&2 "Welcome to the development shell for murid!"
          '';
          packages = [
            (mkPackage pkgs)
            pkgs.calibre
            pkgs.alejandra
            pkgs.hatch
            pkgs.pyenv
            pkgs.ruff
            pylintEnv
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
