import logging

from murid import AppriseHandler, init_apprise, send_test_notification


def test_emit_sends_error_notification():
    class DummyApprise:
        def __init__(self):
            self.calls = []

        def notify(self, **kwargs):
            self.calls.append(kwargs)

    apprise_obj = DummyApprise()
    handler = AppriseHandler(apprise_obj)

    record = logging.LogRecord(
        name="test",
        level=logging.ERROR,
        pathname="",
        lineno=1,
        msg="something broke",
        args=(),
        exc_info=None,
    )

    handler.emit(record)

    assert len(apprise_obj.calls) == 1
    assert apprise_obj.calls[0]["body"] == "something broke"
    assert apprise_obj.calls[0]["title"] == "murid - ERROR"

def test_emit_ignores_non_error_messages():
    class DummyApprise:
        def __init__(self):
            self.calls = []

        def notify(self, **kwargs):
            self.calls.append(kwargs)

    apprise_obj = DummyApprise()
    handler = AppriseHandler(apprise_obj)

    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname="",
        lineno=1,
        msg="hello",
        args=(),
        exc_info=None,
    )

    handler.emit(record)

    assert apprise_obj.calls == []

def test_send_test_notification():
    calls = []

    def notify(**kwargs):
        calls.append(kwargs)

    send_test_notification(notify)

    assert len(calls) == 1

    call = calls[0]
    assert call["title"] == "Murid - Test Notification"
    assert call["body"] == "Hello from Murid!"

def test_init_apprise_adds_handler():
    logger = logging.getLogger("test_apprise")
    logger.handlers.clear()

    notify = init_apprise(
        logger,
        {"urls": ["mailto://test@example.com"]},
    )

    assert callable(notify)
    assert any(
        isinstance(h, AppriseHandler)
        for h in logger.handlers
    )
