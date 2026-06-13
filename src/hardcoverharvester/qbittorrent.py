import logging

import qbittorrentapi
from rich.pretty import pretty_repr

logger = logging.getLogger("HardcoverHarvester")


class QbittorrentError(Exception):
    pass


class Qbittorrent:
    def __init__(self, conn_info):
        self.conn_info = conn_info
        self.conn_info["VERIFY_WEBUI_CERTIFICATE"] = False
        self.client = qbittorrentapi.Client(**conn_info)

        try:
            self.client.auth_log_in()
        except qbittorrentapi.LoginFailed as e:
            logging.error(f"Failed to log in to qBittorrent: {e}")
            raise QbittorrentError(f"Failed to log in to qBittorrent: {e}") from e
        self.client.auth_log_out()
        logger.info(f"Connected to qBittorrent version: {self.client.app.version}")
        logger.debug(f"qBittorrent Web API version: {self.client.app.web_api_version}")
        logger.debug(
            "qBittorrent build info:%s",
            pretty_repr([{k: v} for k, v in self.client.app.build_info.items()]),
        )
