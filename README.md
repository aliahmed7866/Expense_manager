# Pocketwise Expense Manager

A private, mobile-first expense manager for the local Termux app suite. It tracks expenses and income, monthly category budgets, spending trends and CSV exports. Data stays in a local SQLite database and the web service binds to `127.0.0.1` by default.

## Features

- Expense and income transaction tracking
- Monthly totals, balance and daily spending chart
- Category breakdown and monthly category budgets
- Search and filtering
- CSV export
- CSRF-protected forms and safe integer money storage
- Health endpoint and runit/Termux service scripts
- Automatic registration in the AYCF admin hub

## Run locally

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt pytest
python app.py
```

Open <http://127.0.0.1:8082>. Override `EXPENSE_PORT`, `EXPENSE_BIND_HOST`, `EXPENSE_DB_PATH`, or `EXPENSE_SECRET_KEY` as needed.

## Install on Termux

```bash
cd ~
git clone https://github.com/aliahmed7866/Expense_manager.git
cd Expense_manager
bash termux/install-service.sh
bash termux/install-auto-deploy.sh
```

The installer creates the `expense-manager` runit service, registers it in `~/.config/aycf/apps.json`, and restarts the admin hub when available. The default database is `~/.local/share/expense-manager/expenses.sqlite3`.

## Tests

```bash
pip install pytest
pytest -q
```
