"""The release's regression tool works without the removed expectations file."""

import subprocess
import sys
from pathlib import Path


def test_regression_check_flags_changes_without_expectations(tmp_path):
    before, after = tmp_path / "before", tmp_path / "after"
    before.mkdir()
    after.mkdir()
    for folder in (before, after):
        (folder / "R1.json").write_text('{"journal_number": "R1", "value": 1}')
    script = Path(__file__).resolve().parents[1] / "tools" / "regression_check.py"
    command = [sys.executable, str(script), str(before), str(after)]

    identical = subprocess.run(command, capture_output=True, text=True)
    assert identical.returncode == 0, identical.stdout + identical.stderr

    (after / "R1.json").write_text('{"journal_number": "R1", "value": 2}')
    changed = subprocess.run(command, capture_output=True, text=True)
    assert changed.returncode == 1, changed.stdout + changed.stderr
    assert "unexpected change" in changed.stdout
