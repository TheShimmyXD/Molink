from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="session")
def qt_application():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])
