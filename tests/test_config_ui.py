"""Run real JS modules with Node's built-in VM and controlled DOM/fetch."""

from pathlib import Path
import subprocess


def test_redacted_configuration_ui():
    result = subprocess.run(["node", "--test", str(Path(__file__).with_name("config_ui.cjs"))],
                            capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr
