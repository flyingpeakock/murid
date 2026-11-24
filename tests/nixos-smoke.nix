{
  name = "murid-confinement";
  node.pkgsReadOnly = false;
  requiredFeatures.kvm = false;

  nodes.machine =
    { config, pkgs, ... }:
    let
      root = "/home/fixture";
      media = "${root}/media";
      downloads = "/srv/downloads";
      calibre = "${root}/Calibre Library";
      certificate = pkgs.runCommand "murid-test-certificate" { nativeBuildInputs = [ pkgs.openssl ]; } ''
        mkdir "$out"
        openssl req -x509 -newkey rsa:2048 -nodes -days 36500 \
          -subj /CN=fixture.test -addext subjectAltName=DNS:fixture.test \
          -keyout "$out/key.pem" -out "$out/cert.pem"
      '';
      probe = pkgs.writeText "murid-confinement-probe.py" ''
        import errno
        import os
        import socket
        import subprocess
        import urllib.request
        from pathlib import Path

        assert os.environ["MAM_ID"] == "fixture-credential"
        assert not Path("/run/murid-test.env").exists()
        assert not Path("${root}/unrelated").exists()
        assert not Path("/srv/unrelated").exists()
        assert not Path("/tmp/host-file").exists()
        assert not Path("/proc/sys").exists()

        downloaded = Path("${downloads}/fixture.txt")
        assert downloaded.read_text().strip() == "Fixture ebook"
        try:
            downloaded.write_text("write should fail")
        except OSError as error:
            assert error.errno == errno.EROFS, error
        else:
            raise AssertionError("download directory is writable")

        command = [os.environ["CALIBREDB"], "--with-library", "${calibre}"]
        subprocess.run(command + ["add", str(downloaded), "--title", "Fixture ebook"], check=True)
        result = subprocess.check_output(command + ["list", "--for-machine"], text=True)
        assert "Fixture ebook" in result, result

        staging = Path("${media}/.murid-staging-audiobooks")
        library = Path("${media}/audiobooks")
        pending = staging / "pending"
        pending.mkdir(parents=True)
        (pending / "fixture.m4b").write_text("fixture audiobook")
        os.link(pending / "fixture.m4b", library / "linked.m4b")
        os.rename(pending, library / "published")
        assert (library / "published/fixture.m4b").samefile(library / "linked.m4b")

        assert socket.gethostbyname("fixture.test") == "127.0.0.1"
        with urllib.request.urlopen("https://fixture.test:8443/", timeout=10) as response:
            assert response.status == 200
      '';
    in
    {
      users.groups.media = { };
      system.stateVersion = "26.11";
      networking.nameservers = [ "127.0.0.1" ];
      services.dnsmasq = {
        enable = true;
        settings = {
          listen-address = "127.0.0.1";
          address = "/fixture.test/127.0.0.1";
          no-resolv = true;
        };
      };
      security.pki.certificateFiles = [ "${certificate}/cert.pem" ];
      systemd.services.fixture-https = {
        wantedBy = [ "multi-user.target" ];
        serviceConfig.ExecStart = ''
          ${pkgs.python3}/bin/python -m http.server 8443 --bind 127.0.0.1 \
            --directory ${pkgs.emptyDirectory} --tls-cert ${certificate}/cert.pem --tls-key ${certificate}/key.pem
        '';
      };
      services.murid = {
        enable = true;
        supplementaryGroups = [ "media" ];
        environmentFile = "/run/murid-test.env";
        config = {
          hardcover_accounts = [
            {
              api_key = "!ENV HARDCOVER_API_KEY";
              reading_list.ebooks.type = "ebook";
              reading_list.audiobooks.type = "audiobook";
            }
          ];
          mam_id = "!ENV MAM_ID";
          schedule = "0 0 1 1 *";
          calibre.library = calibre;
          audiobookshelf = {
            url = "https://fixture.test:8443";
            api_key = "!ENV MAM_ID";
            library_id = "fixture";
            library_path = "${media}/audiobooks";
          };
          qbittorrent = {
            username = "fixture";
            password = "!ENV MAM_ID";
            mapping = {
              qbit_path = "/torrents";
              murid_path = downloads;
            };
          };
        };
      };
      systemd.services.murid = {
        wantedBy = pkgs.lib.mkForce [ ];
        environment = {
          # Keep the probe from adding Calibre to the confinement closure itself.
          CALIBREDB = builtins.unsafeDiscardStringContext config.services.murid.config.calibre.calibredb_executable;
        };
        serviceConfig.ExecStartPost = "${pkgs.python3}/bin/python ${probe}";
      };
    };

  testScript = ''
    machine.wait_for_unit("multi-user.target")
    machine.wait_for_unit("dnsmasq.service")
    machine.wait_for_open_port(8443)
    machine.succeed(
        "install -d -o root -g media -m 2770 '/home/fixture/Calibre Library' /home/fixture/media/audiobooks /srv/downloads",
        "chgrp media /home/fixture/media",
        "chmod 2770 /home/fixture/media",
        "printf 'Fixture ebook\n' > /srv/downloads/fixture.txt",
        "chmod 0666 /srv/downloads/fixture.txt",
        "touch /home/fixture/unrelated /srv/unrelated /tmp/host-file",
        "install -m 0600 /dev/null /run/murid-test.env",
        "printf 'MAM_ID=fixture-credential\nHARDCOVER_API_KEY=\"Bearer fixture-token\"\n' > /run/murid-test.env",
        "systemctl start murid.service || (journalctl -u murid.service --no-pager; false)",
        "test -s '/home/fixture/Calibre Library/metadata.db'",
        "test -f /home/fixture/media/audiobooks/published/fixture.m4b",
    )
    machine.wait_for_unit("murid.service")
    machine.wait_until_succeeds("journalctl -u murid.service -b | grep -F 'Next murid cycle scheduled'")
  '';
}
