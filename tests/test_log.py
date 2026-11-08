from DinoWrite.core import log


def test_logger_has_single_handler_after_reload():
    logger = log.getLogger()
    log.getLogger()
    # pytest adds its own LogCaptureHandler, count only ours
    ours = [h for h in logger.handlers if isinstance(h, log._HoudiniConsoleHandler)]
    assert len(ours) == 1
    assert logger.name == "DinoWrite"
