from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QRunnable


class FunctionWorker(QRunnable):
    def __init__(
        self,
        function: Callable[[], Any],
        succeeded: Callable[[Any], None],
        failed: Callable[[BaseException], None],
    ) -> None:
        super().__init__()
        self._function = function
        self._succeeded = succeeded
        self._failed = failed
        self.setAutoDelete(True)

    def run(self) -> None:
        try:
            result = self._function()
        except BaseException as exc:
            self._failed(exc)
        else:
            self._succeeded(result)

