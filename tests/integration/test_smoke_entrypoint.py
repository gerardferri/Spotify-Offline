from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys


def test_smoke_entrypoint_exits_without_touching_user_data(tmp_path: Path):
    project_root = Path(__file__).resolve().parents[2]
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(project_root / "src")
    environment["QT_QPA_PLATFORM"] = "offscreen"
    local_data = tmp_path / "local-app-data"
    environment["LOCALAPPDATA"] = str(local_data)

    completed = subprocess.run(
        [sys.executable, "-m", "ytmp3studio", "--smoke-test"],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert not local_data.exists()
