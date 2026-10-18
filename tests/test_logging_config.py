"""El log de la app no lleva contenido del canal."""

from __future__ import annotations

import logging

from logging_config import QUIET_LOGGERS, setup_logging


def test_asyncssh_stays_in_warning_even_with_info_root():
    setup_logging(logging.INFO, to_file=False, force=True)
    assert "asyncssh" in QUIET_LOGGERS
    assert not logging.getLogger("asyncssh").isEnabledFor(logging.INFO)
    assert logging.getLogger("asyncssh").isEnabledFor(logging.WARNING)
    assert logging.getLogger("services").isEnabledFor(logging.INFO)
