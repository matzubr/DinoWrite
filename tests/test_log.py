import importlib

from DinoWrite.core import log


def _ours(logger):
    return [h for h in logger.handlers if getattr(h, "dinowrite", False)]


def test_logger_has_single_handler_after_reload(capsys):
    importlib.reload(log)
    importlib.reload(log)
    logger = log.getLogger()
    assert len(_ours(logger)) == 1
    assert logger.name == "DinoWrite"

    logger.warning("once")
    assert capsys.readouterr().out.count("once") == 1
