{
  pkgs,
  system,
  module,
  nixpkgs,
}: let
  inherit (nixpkgs) lib;
  package = pkgs.writeShellScriptBin "murid" "exit 0";
  inlineConfig = {
    hardcover_api_keys = ["!ENV HARDCOVER_API_KEY"];
    mam_id = "!ENV MAM_ID";
    calibre.library = "http://localhost:8080/#books";
    qbittorrent = {
      username = "admin";
      password = "!ENV QBITTORRENT_PASSWORD";
    };
  };
  evaluate = settings:
    (lib.nixosSystem {
      inherit system;
      modules = [
        module
        {
          services.murid =
            {
              enable = true;
              inherit package;
              environmentFile = "/etc/murid.env";
            }
            // settings;
        }
      ];
    }).config;
  fromFile = evaluate {configFile = "/etc/murid.yaml";};
  fromInline = evaluate {config = inlineConfig;};
  fromUserLists = evaluate {
    config =
      inlineConfig
      // {
        hardcover_api_keys = [
          "!ENV HARDCOVER_API_KEY"
          {
            api_key = "!ENV SECOND_HARDCOVER_API_KEY";
            list = "download-queue";
          }
          {api_key = "!ENV THIRD_HARDCOVER_API_KEY";}
        ];
      };
  };
  userLists = fromUserLists.services.murid.config.hardcover_api_keys;
  fileCommand = fromFile.systemd.services.murid.serviceConfig.ExecStart;
  inlineCommand = fromInline.systemd.services.murid.serviceConfig.ExecStart;
  expectedFileCommand = "${lib.getExe package} ${lib.escapeShellArgs ["schedule" "--config" "/etc/murid.yaml"]}";
  valid =
    builtins.elemAt userLists 0
    == "!ENV HARDCOVER_API_KEY"
    && (builtins.elemAt userLists 1).list == "download-queue"
    && (builtins.elemAt userLists 2).list == "want-to-read"
    && fileCommand == expectedFileCommand
    && lib.hasPrefix "${lib.getExe package} ${lib.escapeShellArgs ["schedule" "--config"]} " inlineCommand;
in
  if valid
  then pkgs.runCommand "murid-nixos-module-test" {} "touch $out"
  else
    throw (builtins.toJSON {
      inherit fileCommand inlineCommand expectedFileCommand;
    })
