"""Module for integrating Apprise notifications into the Murid application."""

import logging
from typing import Callable

import apprise
import yaml


class AppriseHandler(logging.Handler):
    """Custom logging handler that sends error-level logs to Apprise notifications."""

    def __init__(self, apprise_obj: apprise.Apprise = None):
        super().__init__()
        self.apprise = apprise_obj or apprise.Apprise()

    def emit(self, record: logging.LogRecord) -> None:
        if record.levelno >= logging.ERROR:
            self.apprise.notify(
                body=record.getMessage(),
                title=f"murid - {record.levelname}",
                notify_type=apprise.NotifyType.FAILURE,
            )


def init_apprise(
    logger: logging.Logger, config: dict
) -> Callable[[str, str, apprise.NotifyType], None]:
    """Initialize Apprise with the provided configuration and return a notify function."""
    logger.debug("Initializing Apprise with config: %s", config)
    asset = apprise.AppriseAsset(
        app_id="murid",
        app_desc=(
            "Murid automatically keeps your "
            "Calibre library in sync with your reading "
            "list on Hardcover, with help from myAnonamouse."
        ),
    )

    apprise_conf = apprise.AppriseConfig()
    apprise_conf.add_config(yaml.dump(config), format="yaml")

    apprise_obj = apprise.Apprise(asset=asset)
    apprise_obj.add(apprise_conf)
    logger.addHandler(AppriseHandler(apprise_obj))
    return apprise_obj.notify


def send_test_notification(notify: Callable[[str, str, apprise.NotifyType], None]) -> None:
    """Send a test notification to verify that Apprise is working correctly."""
    notify(
        title="Murid - Test Notification",
        body="Hello from Murid!",
        notify_type=apprise.NotifyType.INFO,
    )
