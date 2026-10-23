from __future__ import annotations

import os
import sys

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def pytest_configure(config):
    config.addinivalue_line("markers", "linux_only: usa sh, permisos POSIX, XDG o senales de Linux")


def pytest_collection_modifyitems(config, items):
    if sys.platform != "win32":
        return
    skip = pytest.mark.skip(reason="solo Linux")
    for item in items:
        if "linux_only" in item.keywords:
            item.add_marker(skip)


@pytest.fixture(scope="session")
def qt_application():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])
