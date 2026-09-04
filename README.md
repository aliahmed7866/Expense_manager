# Pocketwise Expense Manager

A private, mobile-first expense manager for the local Termux app suite. It tracks expenses and income, monthly category budgets, spending trends and CSV exports. Data stays in a local SQLite database and the web service binds to `127.0.0.1` by default.

## Features

- Expense and income transaction tracking
- Weekly and monthly recurring bills and income
- Upcoming 30-day cash-flow forecast with projected available balance
- One-tap record, skip-once and remove controls for scheduled entries
- Separate lender debt cards with live outstanding balances
- Income-funded debt repayments with payment history and undo support
- Priority-debt safeguards, monthly minimums and due-date status
- Highest-APR and smallest-balance payoff strategies
- Editable APR, debt type, lender and repayment details
- Monthly totals, balance and daily spending chart
- Category breakdown and monthly category budgets
- Search and filtering
- CSV export
- CSRF-protected forms and safe integer money storage
- Health endpoint and runit/Termux service scripts
- Automatic registration in the AYCF admin hub
- One-tap expense, income and debt actions with a guided first-run state

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

The installer creates the `expense-manager` runit service and registers it in `~/.config/aycf/apps.json`. The admin hub reads that registry dynamically, so it does not need to be restarted. The default database is `~/.local/share/expense-manager/expenses.sqlite3`.

If the service is not installed yet, the admin hub can run its configured setup command from the Pocketwise **Start** button. After setup, Start, Stop and Restart use the `expense-manager` runit service directly.

## Tests

```bash
pip install pytest
pytest -q
```

## Install as a phone app

Keep Pocketwise running in Termux, open its local URL in Chrome, then use the in-app **Install app** button (or Chrome's **Install app / Add to Home screen** menu). The installed icon opens Pocketwise in its own app window and provides shortcuts for income, expenses and debts where supported.

The Termux service, SQLite data and auto-deploy process are unchanged. If the service is stopped, the installed app shows a short offline message directing you to start Pocketwise from the Admin Hub; financial pages and API responses are never stored as stale offline data.
