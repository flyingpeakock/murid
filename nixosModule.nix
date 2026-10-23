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
    mediaTypes =
      if cfg.config == null
      then []
      else
        lib.concatMap (entry:
          if builtins.isString entry
          then ["ebook"]
          else if entry ? reading_list
          then
            lib.concatMap (options:
              if builtins.isString options.type
              then [options.type]
              else options.type)
            (builtins.attrValues entry.reading_list)
          else entry.media_types)
        cfg.config.hardcover_api_keys;

    yaml = pkgs.formats.yaml {};
    createYAMLConfig = config: yaml.generate "murid.yaml" config;

    configEnvType = lib.types.addCheck lib.types.str (val: lib.strings.hasPrefix "!ENV " val);

    configCalibreType = lib.types.submodule {
      options = {
        command_timeout_seconds = lib.mkOption {
          description = "Maximum runtime in seconds for each calibredb command";
          type = lib.types.ints.positive;
          default = 120;
        };
        calibredb_executable = lib.mkOption {
          description = "Path to the calibredb executable";
          type = lib.types.str;
          default = "${pkgs.calibre}/bin/calibredb";
        };
        library = lib.mkOption {
          description = "Path to the Calibre library or URL to the Calibre content server";
          type = lib.types.str;
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

      supplementaryGroups = lib.mkOption {
        description = "Additional service groups for reading downloads and writing shared libraries";
        type = lib.types.listOf lib.types.str;
        default = [];
      };
      requiresMountsFor = lib.mkOption {
        description = "Additional absolute paths whose mounts must be available before Murid starts; use for configFile deployments and download mounts";
        type = lib.types.listOf (lib.types.addCheck lib.types.str (lib.hasPrefix "/"));
        default = [];
      };

      configFile = lib.mkOption {
        description = ''
          Path to the murid configuration file.
          Set either this option or `config`.
        '';
        type = lib.types.nullOr lib.types.str;
        default = null;
      };

      environmentFile = lib.mkOption {
        description = ''
          Path to an environment file containing environment variables for the murid service.
        '';
        type = lib.types.nullOr lib.types.str;
        default = null;
      };

      extraArgs = lib.mkOption {
        description = "Extra command line arguments to pass to the murid executable";
        type = lib.types.listOf lib.types.str;
        default = [];
      };

      config = lib.mkOption {
        description = "Configuration for murid";
        default = null;
        type = lib.types.nullOr (lib.types.submodule {
          options = {
            hardcover_api_keys = lib.mkOption {
              description = "Hardcover API tokens or per-user API token and grouped reading lists";
              apply = entries:
                map (entry:
                  if builtins.isString entry
                  then entry
                  else if entry.reading_list == null
                  then builtins.removeAttrs entry ["reading_list"]
                  else if entry.list != "want-to-read" || entry.media_types != ["ebook"]
                  then throw "reading_list cannot be combined with custom list or media_types"
                  else builtins.removeAttrs entry ["list" "media_types"])
                entries;
              type = lib.types.listOf (lib.types.either configEnvType (lib.types.submodule {
                options = {
                  api_key = lib.mkOption {
                    description = "Hardcover API token, including the Bearer prefix";
                    type = configEnvType;
                  };
                  list = lib.mkOption {
                    description = "List slug from its URL, or want-to-read for the reading status";
                    type = lib.types.str;
                    default = "want-to-read";
                  };
                  media_types = lib.mkOption {
                    description = "Media requested from this list";
                    type = lib.types.addCheck (lib.types.listOf (lib.types.enum ["ebook" "audiobook"])) (values: values != []);
                    default = ["ebook"];
                  };
                  reading_list = lib.mkOption {
                    description = "List slugs mapped to options; type defaults to ebook";
                    default = null;
                    type = lib.types.nullOr (lib.types.addCheck (lib.types.attrsOf (lib.types.submodule {
                      options.type = lib.mkOption {
                        description = "Requested medium, or a list requesting both media";
                        default = "ebook";
                        type =
                          lib.types.either (lib.types.enum ["ebook" "audiobook"])
                          (lib.types.addCheck (lib.types.listOf (lib.types.enum ["ebook" "audiobook"])) (values: values != []));
                      };
                    })) (values: values != {}));
                  };
                };
              }));
              default = [];
            };

            redact_sensitive_data = lib.mkOption {
              description = "Whether to redact sensitive data (e.g. API keys) from logs";
              type = lib.types.bool;
              default = true;
            };

            matcher_threshold = lib.mkOption {
              description = "Threshold for the matcher to consider a match valid (between 0 and 1)";
              type = lib.types.addCheck lib.types.float (value: value >= 0 && value <= 1);
              default = 0.92;
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
              type = lib.types.nullOr configCalibreType;
              default = null;
            };

            audiobookshelf = lib.mkOption {
              description = "Audiobookshelf configuration; required for audiobook requests";
              default = null;
              type = lib.types.nullOr (lib.types.submodule {
                options = {
                  url = lib.mkOption {
                    description = "Audiobookshelf HTTP(S) base URL";
                    type = lib.types.str;
                  };
                  api_key = lib.mkOption {
                    description = "API key for an active admin/root user with library access";
                    type = configEnvType;
                  };
                  library_id = lib.mkOption {
                    description = "Audiobookshelf book library ID";
                    type = lib.types.str;
                  };
                  library_path = lib.mkOption {
                    description = "Absolute shared library path as seen by Murid";
                    type = lib.types.str;
                  };
                  staging_path = lib.mkOption {
                    description = "Private staging directory outside all scanned roots on the library filesystem; defaults to a sibling of library_path";
                    type = lib.types.nullOr lib.types.str;
                    default = null;
                  };
                  folder_id = lib.mkOption {
                    description = "Audiobookshelf folder ID corresponding to library_path; required for multiple library roots";
                    type = lib.types.nullOr lib.types.str;
                    default = null;
                  };
                  scan_timeout_seconds = lib.mkOption {
                    description = "Separate maximum wait for verified Audiobookshelf ingestion";
                    type = lib.types.ints.positive;
                    default = 120;
                  };
                  filetypes = lib.mkOption {
                    description = "Accepted audiobook formats in preference order";
                    type = lib.types.addCheck (lib.types.listOf (lib.types.enum ["m4b" "mp3"])) (values: values != []);
                    default = ["m4b" "mp3"];
                  };
                };
              });
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
              description = "Accepted ebook formats in preference order";
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
              type = lib.types.ints.positive;
              default = 1800; # 30 minutes
            };
          };
        });
      };
    };

    config = lib.mkIf cfg.enable {
      nixpkgs.overlays = [overlay];

      assertions = [
        {
          assertion = (cfg.config != null) != (cfg.configFile != null);
          message = "Set exactly one of services.murid.config or services.murid.configFile";
        }
        {
          assertion = !(builtins.elem "ebook" mediaTypes) || cfg.config.calibre != null;
          message = "Ebook requests require services.murid.config.calibre";
        }
        {
          assertion = !(builtins.elem "audiobook" mediaTypes) || cfg.config.audiobookshelf != null;
          message = "Audiobook requests require services.murid.config.audiobookshelf";
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
        description = "Murid syncs Hardcover ebook and audiobook requests with their libraries";
        enable = true;
        after = ["network.target"];
        wantedBy = ["multi-user.target"];
        unitConfig.RequiresMountsFor = lib.unique (cfg.requiresMountsFor
          ++ (
            if cfg.config != null && cfg.config.audiobookshelf != null
            then let
              audio = cfg.config.audiobookshelf;
              staging =
                if audio.staging_path != null
                then audio.staging_path
                else "${builtins.dirOf audio.library_path}/.murid-staging-${builtins.baseNameOf audio.library_path}";
            in [audio.library_path staging]
            else []
          ));
        serviceConfig = {
          Type = "simple";
          SupplementaryGroups = cfg.supplementaryGroups;
          User = cfg.user;
          Group = cfg.group;
          EnvironmentFile = lib.optionalString (cfg.environmentFile != null) cfg.environmentFile;
          ExecStart = let
            configFile =
              if cfg.config != null
              then createYAMLConfig cfg.config
              else cfg.configFile;
            args = ["schedule" "--config" (toString configFile)] ++ cfg.extraArgs;
          in "${lib.getExe cfg.package} ${lib.escapeShellArgs args}";
        };
      };
    };
  };
}
