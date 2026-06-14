{config, ...}: let
  overlay = config.flake.overlays.default;
in {
  flake.nixosModules.default = {
    config,
    lib,
    pkgs,
    ...
  }: let
    cfg = config.services.hardcoverharvester;

    yaml = pkgs.formats.yaml {};
    createYAMLConfig = config: yaml.generate "hardcoverharvester.yaml" config;

    configEnvType = lib.types.addCheck lib.types.str (val: lib.strings.hasPrefix "!ENV " val);

    configUserType = lib.types.listOf (lib.types.submodule {
      options = {
        id = lib.mkOption {
          description = "User ID for hardcover";
          type = lib.types.int;
        };
        api_key = lib.mkOption {
          description = "API key for hardcover";
          type = configEnvType;
        };
      };
    });

    configQbittorrentType = lib.types.submodule {
      options = {
        host = lib.mkOption {
          description = "Host for qBittorrent Web API";
          type = lib.types.str;
          default = "http://localhost";
        };
        username = lib.mkOption {
          description = "Username for qBittorrent Web API";
          type = lib.types.str;
        };
        password = lib.mkOption {
          description = "Password for qBittorrent Web API";
          type = configEnvType;
        };
        verify_cert = lib.mkOption {
          description = "Whether to verify SSL certificates when connecting to qBittorrent Web API";
          type = lib.types.bool;
          default = true;
        };
        category = lib.mkOption {
          description = "Category to use when adding torrents to qBittorrent";
          type = lib.types.str;
          default = "hardcoverharvester";
        };
        port = lib.mkOption {
          description = "Port that qBittorrent Web API is running on";
          type = lib.types.port;
          default = config.services.qbittorrent.webuiPort;
        };
      };
    };
  in {
    options.services.hardcoverharvester = {
      enable = lib.mkEnableOption "HardcoverHarvester";
      package = lib.mkPackageOption pkgs "hardcoverharvester" {};

      user = lib.mkOption {
        description = "User to run the HardcoverHarvester service as";
        type = lib.types.str;
        default = "hardcoverharvester";
      };
      group = lib.mkOption {
        description = "Group to run the HardcoverHarvester service as";
        type = lib.types.str;
        default = "hardcoverharvester";
      };

      configFile = lib.mkOption {
        description = ''
          Path to the HardcoverHarvester configuration file.
          Ignored if `config` option is used.
        '';
        type = lib.types.str;
      };

      environmentFile = lib.mkOption {
        description = ''
          Path to an environment file containing environment variables for the HardcoverHarvester service.
        '';
        type = lib.types.nullOr lib.types.str;
      };

      extraArgs = lib.mkOption {
        description = "Extra command line arguments to pass to the HardcoverHarvester executable";
        type = lib.types.listOf lib.types.str;
        default = [];
      };

      config = lib.mkOption {
        description = "Configuration for HardcoverHarvester";
        default = {};
        type = lib.types.submodule {
          options = {
            users = lib.mkOption {
              description = "Hardcover user ids and their corresponding API keys";
              type = configUserType;
            };

            redact_sensitive_data = lib.mkOption {
              description = "Whether to redact sensitive data (e.g. API keys) from logs";
              type = lib.types.bool;
              default = true;
            };

            calibre_db_path = lib.mkOption {
              description = "Path to the calibre database file";
              type = lib.types.str;
            };

            calibredb_executable = lib.mkOption {
              description = "Path to the calibredb executable";
              type = lib.types.str;
              default = "${pkgs.calibre}/bin/calibredb";
            };

            matcher_threshold = lib.mkOption {
              description = "Threshold for the matcher to consider a match valid (between 0 and 1)";
              type = lib.types.float;
              default = 0.85;
            };

            mam_id = lib.mkOption {
              description = "MaM ID from myanonamouse";
              type = configEnvType;
            };

            lang_codes = lib.mkOption {
              description = "List of language codes to prefer when matching books (e.g. ['ENG', 'SWE'])";
              type = lib.types.listOf lib.types.str;
              default = ["ENG"];
            };

            qbittorrent = lib.mkOption {
              description = "QBittorrent configuration";
              type = configQbittorrentType;
            };

            schedule = lib.mkOption {
              description = "Cron schedule for running the harvester";
              type = lib.types.str;
              default = "0 * * * *"; # every hour
            };
          };
        };
      };
    };

    config = lib.mkIf cfg.enable {
      nixpkgs.overlays = [overlay];

      users = {
        users = lib.mkIf (cfg.user == "hardcoverharvester") {
          hardcoverharvester = {
            inherit (cfg) group;
            isSystemUser = true;
          };
        };
        groups = lib.mkIf (cfg.group == "hardcoverharvester") {
          hardcoverharvester = {};
        };
      };

      systemd.services.hardcoverharvester = {
        description = "Fetch books from MaM and add them to calibre";
        enable = true;
        after = ["network.target"];
        wantedBy = ["multi-user.target"];
        serviceConfig = {
          Type = "simple";
          User = cfg.user;
          Group = cfg.group;
          EnvironmentFile = lib.optionalString (cfg.environmentFile != null) cfg.environmentFile;
          ExecStart = let
            configFile =
              if cfg.config != {}
              then createYAMLConfig cfg.config
              else cfg.configFile;
            args =
              [
                "--config ${configFile}"
              ]
              ++ cfg.extraArgs;
          in "${lib.getExe cfg.package} ${lib.concatStringsSep " " args}";
        };
      };
    };
  };
}
