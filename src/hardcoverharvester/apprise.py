import logging
from typing import Callable

import apprise
import yaml


class AppriseHandler(logging.Handler):
    def __init__(self, apprise_obj: apprise.Apprise = None):
        super().__init__()
        self.apprise = apprise_obj or apprise.Apprise()

    def emit(self, record: logging.LogRecord) -> None:
        if record.levelno >= logging.ERROR:
            self.apprise.notify(
                body=record.getMessage(),
                title=f"HardcoverHarvester - {record.levelname}",
                notify_type=apprise.NotifyType.FAILURE,
            )


def init_apprise(
    logger: logging.Logger, config: dict
) -> Callable[[str, str, apprise.NotifyType], None]:
    logger.debug("Initializing Apprise with config: %s", config)
    asset = apprise.AppriseAsset(
        app_id="HardcoverHarvester",
        app_desc="Fetch Hardcover books with MaM",
    )

    apprise_conf = apprise.AppriseConfig()
    apprise_conf.add_config(yaml.dump(config), format="yaml")

    apprise_obj = apprise.Apprise(asset=asset)
    apprise_obj.add(apprise_conf)
    logger.addHandler(AppriseHandler(apprise_obj))
    return apprise_obj.notify
