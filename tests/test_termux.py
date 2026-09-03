import json
import os
import subprocess
import sys
from pathlib import Path


def test_admin_registration_includes_service_setup_command(tmp_path):
    registry = tmp_path / "apps.json"
    registry.write_text('{"apps": []}\n', encoding="utf-8")
    env = {
        **os.environ,
        "AYCF_APP_DIR": str(tmp_path / "aycf"),
        "EXPENSE_APP_DIR": str(tmp_path / "pocketwise"),
    }
    subprocess.run(
        [sys.executable, str(Path(__file__).parents[1] / "termux" / "register-admin.py"), str(registry), "8082"],
        check=True,
        env=env,
    )
    app = json.loads(registry.read_text(encoding="utf-8"))["apps"][0]
    assert app["name"] == "Pocketwise"
    assert app["description"] == "Expenses, income, budgets and debt payoff"
    assert app["working_dir"] == str(tmp_path / "pocketwise")
    assert app["service"] == "expense-manager"
    assert app["process_match"] == f"{tmp_path}/pocketwise/.venv/bin/python termux/run-web.py"
    assert app["install_command"] == [
        "bash", str(tmp_path / "aycf" / "termux" / "install-expense-manager.sh")
    ]
