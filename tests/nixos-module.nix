{
  pkgs,
  system,
  module,
  nixpkgs,
}: let
  inherit (nixpkgs) lib;
  package = pkgs.writeShellScriptBin "murid" "exit 0";
  inlineConfig = {
    hardcover_accounts = [
      {
        api_key = "!ENV HARDCOVER_API_KEY";
        reading_list.want-to-read = {};
      }
    ];
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
  fromLegacy = evaluate {
    config =
      (builtins.removeAttrs inlineConfig ["hardcover_accounts"])
      // {
        hardcover_api_keys = inlineConfig.hardcover_accounts;
      };
  };
  sharedService = evaluate {
    configFile = "/etc/murid.yaml";
    supplementaryGroups = ["media" "qbittorrent"];
    requiresMountsFor = ["/shared/audiobooks" "/shared/staging" "/downloads"];
  };
  fromUserLists = evaluate {
    config =
      inlineConfig
      // {
        hardcover_accounts = [
          {
            api_key = "!ENV HARDCOVER_API_KEY";
            reading_list.want-to-read = {};
          }
          {
            api_key = "!ENV SECOND_HARDCOVER_API_KEY";
            reading_list.download-queue = {};
          }
          {
            api_key = "!ENV THIRD_HARDCOVER_API_KEY";
            reading_list.want-to-read = {};
          }
        ];
      };
  };
  userLists = fromUserLists.services.murid.config.hardcover_accounts;
  audioConfig =
    inlineConfig
    // {
      calibre = null;
      hardcover_accounts = [
        {
          api_key = "!ENV HARDCOVER_API_KEY";
          reading_list.want-to-read.type = "audiobook";
        }
      ];
      audiobookshelf = {
        url = "https://audio.example.com";
        api_key = "!ENV AUDIOBOOKSHELF_API_KEY";
        library_id = "library-id";
        library_path = "/mnt/audiobooks";
      };
    };
  fromAudio = evaluate {config = audioConfig;};
  importSettings =
    (evaluate {
      config =
        audioConfig
        // {
          audiobookshelf =
            audioConfig.audiobookshelf
            // {
              staging_path = "/mnt/.staging";
              folder_id = "folder-id";
              scan_timeout_seconds = 17;
            };
        };
    }).services.murid.config.audiobookshelf;
  fromGrouped = evaluate {
    config =
      audioConfig
      // {
        inherit (inlineConfig) calibre;
        hardcover_accounts = [
          {
            api_key = "!ENV HARDCOVER_API_KEY";
            reading_list = {
              want-to-read = {};
              audio.type = "audiobook";
              both.type = ["ebook" "audiobook"];
            };
          }
        ];
      };
  };
  grouped = builtins.head fromGrouped.services.murid.config.hardcover_accounts;
  groupedAudio = evaluate {
    config =
      audioConfig
      // {
        hardcover_accounts = [
          {
            api_key = "!ENV HARDCOVER_API_KEY";
            reading_list.audio.type = "audiobook";
          }
        ];
      };
  };
  fromBoth = evaluate {
    config =
      audioConfig
      // {
        inherit (inlineConfig) calibre;
        hardcover_accounts = [
          {
            api_key = "!ENV HARDCOVER_API_KEY";
            reading_list.want-to-read.type = ["ebook" "audiobook"];
          }
        ];
      };
  };
  backendAssertions = evaluated:
    lib.filter (item:
      !item.assertion
      && builtins.elem item.message [
        "Ebook requests require services.murid.config.calibre"
        "Audiobook requests require services.murid.config.audiobookshelf"
      ])
    evaluated.assertions;
  backendsValid = evaluated: backendAssertions evaluated == [];
  invalidMedia = values:
    builtins.tryEval (builtins.deepSeq
      (evaluate {
        config =
          audioConfig
          // {
            hardcover_accounts = [
              {
                api_key = "!ENV KEY";
                reading_list.want-to-read.type = values;
              }
            ];
          };
      }).services.murid.config.hardcover_accounts
      true);
  invalidHardcover = entries:
    builtins.tryEval (builtins.deepSeq
      (evaluate {
        config = inlineConfig // {hardcover_accounts = entries;};
      }).services.murid.config.hardcover_accounts
      true);
  conflictingAccounts = builtins.tryEval (builtins.deepSeq
    (evaluate {
      config = inlineConfig // {hardcover_api_keys = inlineConfig.hardcover_accounts;};
    }).services.murid.config
    true);
  fileCommand = fromFile.systemd.services.murid.serviceConfig.ExecStart;
  inlineCommand = fromInline.systemd.services.murid.serviceConfig.ExecStart;
  expectedFileCommand = "${lib.getExe package} ${lib.escapeShellArgs ["schedule" "--config" "/etc/murid.yaml"]}";
  valid =
    fromLegacy.services.murid.config.hardcover_accounts
    == fromInline.services.murid.config.hardcover_accounts
    && !(fromLegacy.services.murid.config ? hardcover_api_keys)
    && !conflictingAccounts.success
    && (builtins.elemAt userLists 0).api_key
    == "!ENV HARDCOVER_API_KEY"
    && (builtins.elemAt userLists 1).reading_list.download-queue.type == "ebook"
    && (builtins.elemAt userLists 2).reading_list.want-to-read.type == "ebook"
    && fromAudio.services.murid.config.calibre == null
    && fromAudio.services.murid.config.audiobookshelf.filetypes == ["m4b" "mp3"]
    && fromAudio.services.murid.config.audiobookshelf.staging_path == null
    && fromAudio.services.murid.config.audiobookshelf.folder_id == null
    && fromAudio.services.murid.config.audiobookshelf.scan_timeout_seconds == 120
    && importSettings.staging_path == "/mnt/.staging"
    && importSettings.folder_id == "folder-id"
    && importSettings.scan_timeout_seconds == 17
    && fromInline.systemd.services.murid.serviceConfig.SupplementaryGroups == []
    && fromInline.systemd.services.murid.unitConfig.RequiresMountsFor == []
    && fromAudio.systemd.services.murid.unitConfig.RequiresMountsFor == ["/mnt/audiobooks" "/mnt/.murid-staging-audiobooks"]
    && sharedService.systemd.services.murid.serviceConfig.SupplementaryGroups == ["media" "qbittorrent"]
    && sharedService.systemd.services.murid.unitConfig.RequiresMountsFor == ["/shared/audiobooks" "/shared/staging" "/downloads"]
    && backendsValid fromAudio
    && backendsValid fromBoth
    && backendsValid fromGrouped
    && backendsValid groupedAudio
    && grouped.reading_list.want-to-read.type == "ebook"
    && grouped.reading_list.audio.type == "audiobook"
    && grouped.reading_list.both.type == ["ebook" "audiobook"]
    && !(grouped ? list)
    && !(grouped ? media_types)
    && !(backendsValid (evaluate {
      config =
        audioConfig
        // {
          audiobookshelf = null;
          hardcover_accounts = [
            {
              api_key = "!ENV HARDCOVER_API_KEY";
              reading_list.audio.type = "audiobook";
            }
          ];
        };
    }))
    && !(backendsValid (evaluate {config = audioConfig // {audiobookshelf = null;};}))
    && !(backendsValid (evaluate {config = inlineConfig // {calibre = null;};}))
    && !(invalidHardcover ["!ENV HARDCOVER_API_KEY"]).success
    && !(invalidHardcover [{api_key = "!ENV KEY";}]).success
    && !(invalidHardcover [
      {
        api_key = "!ENV KEY";
        reading_list = {};
      }
    ]).success
    && !(invalidHardcover [
      {
        api_key = "!ENV KEY";
        list = "want-to-read";
      }
    ]).success
    && !(invalidHardcover [
      {
        api_key = "!ENV KEY";
        media_types = ["ebook"];
      }
    ]).success
    && !(invalidMedia []).success
    && !(invalidMedia ["video"]).success
    && fileCommand == expectedFileCommand
    && lib.hasPrefix "${lib.getExe package} ${lib.escapeShellArgs ["schedule" "--config"]} " inlineCommand;
in
  if valid
  then pkgs.runCommand "murid-nixos-module-test" {} "touch $out"
  else
    throw (builtins.toJSON {
      inherit fileCommand inlineCommand expectedFileCommand;
    })
