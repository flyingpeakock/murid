{config, ...}: let
  overlay = config.flake.overlays.default;
in {
  flake.nixosModules.default = {
    config,
    lib,
    pkgs,
    ...
  }: let
    cfg = config.services.murid;

    yaml = pkgs.formats.yaml {};
    createYAMLConfig = config: yaml.generate "murid.yaml" config;

    configEnvType = lib.types.addCheck lib.types.str (val: lib.strings.hasPrefix "!ENV " val);

    configCalibreType = lib.types.submodule {
      options = {
        calibredb_executable = lib.mkOption {
          description = "Path to the calibredb executable";
          type = lib.types.str;
          default = "${pkgs.calibre}/bin/calibredb";
        };
        library_path = lib.mkOption {
          description = "Path to the Calibre library";
          type = lib.types.nullOr lib.types.str;
          default = null;
        };
        server_url = lib.mkOption {
          description = "URL to the Calibre server";
          type = lib.types.nullOr lib.types.str;
          default = null;
        };
        server_username = lib.mkOption {
          description = "Username for the Calibre server";
          type = lib.types.nullOr configEnvType;
          default = null;
        };
        server_password = lib.mkOption {
          description = "Password for the Calibre server";
          type = lib.types.nullOr configEnvType;
          default = null;
        };
      };
    };

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
          default = "murid";
        };
        port = lib.mkOption {
          description = "Port that qBittorrent Web API is running on";
          type = lib.types.port;
          default = config.services.qbittorrent.webuiPort;
        };
        mapping = lib.mkOption {
          description = "Mapping of qbittorrent save paths to paths as seen by the murid service";
          type = lib.types.submodule {
            options = {
              qbit_path = lib.mkOption {
                description = "Path as seen by qBittorrent";
                type = lib.types.nullOr lib.types.str;
                default = null;
              };
              murid_path = lib.mkOption {
                description = "Path as seen by the murid service";
                type = lib.types.nullOr lib.types.str;
                default = null;
              };
            };
          };
        };
      };
    };
  in {
    options.services.murid = {
      enable = lib.mkEnableOption "murid";
      package = lib.mkPackageOption pkgs "murid" {};

      user = lib.mkOption {
        description = "User to run the murid service as";
        type = lib.types.str;
        default = "murid";
      };
      group = lib.mkOption {
        description = "Group to run the murid service as";
        type = lib.types.str;
        default = "murid";
      };

      configFile = lib.mkOption {
        description = ''
          Path to the murid configuration file.
          Ignored if `config` option is used.
        '';
        type = lib.types.str;
      };

      environmentFile = lib.mkOption {
        description = ''
          Path to an environment file containing environment variables for the murid service.
        '';
        type = lib.types.nullOr lib.types.str;
      };

      extraArgs = lib.mkOption {
        description = "Extra command line arguments to pass to the murid executable";
        type = lib.types.listOf lib.types.str;
        default = [];
      };

      config = lib.mkOption {
        description = "Configuration for murid";
        default = {};
        type = lib.types.submodule {
          options = {
            hardcover_api_keys = lib.mkOption {
              description = "List of API keys for hardcover";
              type = lib.types.listOf configEnvType;
              default = [];
            };

            redact_sensitive_data = lib.mkOption {
              description = "Whether to redact sensitive data (e.g. API keys) from logs";
              type = lib.types.bool;
              default = true;
            };

            matcher_threshold = lib.mkOption {
              description = "Threshold for the matcher to consider a match valid (between 0 and 1)";
              type = lib.types.float;
              default = 0.7;
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

            calibre = lib.mkOption {
              description = "Calibre configuration";
              type = configCalibreType;
            };

            schedule = lib.mkOption {
              description = "Cron schedule for running the murid";
              type = lib.types.str;
              default = "0 * * * *"; # every hour
            };

            apprise = lib.mkOption {
              description = "Apprise configuration for notifications";
              default = null;
              type = lib.types.nullOr (lib.types.submodule {
                freeformType = yaml.type;
                options.urls = lib.mkOption {
                  description = "List of Apprise URLs to send notifications to";
                  type = lib.types.listOf lib.types.str;
                };
              });
            };

            filetypes = lib.mkOption {
              description = "List of filetypes to consider when matching books";
              type = lib.types.listOf lib.types.str;
              default = [
                "epub"
                "mobi"
                "azw3"
                "azw"
                "kfx"
              ];
            };

            blacklisted_torrent_ids = lib.mkOption {
              description = "List of blacklisted torrent ID's to ignore when fetching data from trackers";
              type = lib.types.listOf lib.types.int;
              default = [];
            };

            torrent_timeout_seconds = lib.mkOption {
              description = "Number of seconds before a torrent download is considered timed out";
              default = 1800; # 30 minutes
            };
          };
        };
      };
    };

    config = lib.mkIf cfg.enable {
      nixpkgs.overlays = [overlay];

      assertions = let
        library_path_not_null = cfg.config.calibre.library_path != null;
        server_url_not_null = cfg.config.calibre.server_url != null;
      in [
        {
          assertion = library_path_not_null != server_url_not_null;
          message = "Only one of calibre.library_path or calibre.server_url can be set in the murid configuration";
        }
      ];

      users = {
        users = lib.mkIf (cfg.user == "murid") {
          murid = {
            inherit (cfg) group;
            isSystemUser = true;
          };
        };
        groups = lib.mkIf (cfg.group == "murid") {
          murid = {};
        };
      };

      systemd.services.murid = {
        description = "Murid automatically keeps your Calibre library in sync";
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
                "--schedule"
              ]
              ++ cfg.extraArgs;
          in "${lib.getExe cfg.package} ${lib.concatStringsSep " " args}";
        };
      };
    };
  };
}
