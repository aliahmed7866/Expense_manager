from __future__ import annotations

import csv
import io
import os
import re
import secrets
import sqlite3
from calendar import monthrange
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path

from flask import Flask, Response, abort, flash, redirect, render_template, request, session, url_for


CATEGORY_COLOURS = {
    "Housing": "#8b5cf6",
    "Bills": "#06b6d4",
    "Food": "#f59e0b",
    "Transport": "#3b82f6",
    "Shopping": "#ec4899",
    "Entertainment": "#f97316",
    "Health": "#10b981",
    "Travel": "#6366f1",
    "Debt payment": "#ef476f",
    "Other": "#64748b",
    "Salary": "#22c55e",
}
MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def money_to_pence(value: str) -> int:
    try:
        amount = Decimal(value.strip()).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, AttributeError):
        raise ValueError("Enter a valid amount.") from None
    if amount <= 0 or amount > Decimal("99999999.99"):
        raise ValueError("Amount must be greater than zero.")
    return int(amount * 100)


def optional_money_to_pence(value: str | None) -> int:
    if not value or not value.strip():
        return 0
    try:
        amount = Decimal(value.strip()).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except InvalidOperation:
        raise ValueError("Enter a valid minimum payment.") from None
    if amount < 0 or amount > Decimal("99999999.99"):
        raise ValueError("Minimum payment cannot be negative.")
    return int(amount * 100)


def apr_to_basis_points(value: str | None) -> int:
    if not value or not value.strip():
        return 0
    try:
        apr = Decimal(value.strip()).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except InvalidOperation:
        raise ValueError("Enter a valid APR.") from None
    if apr < 0 or apr > 999:
        raise ValueError("APR must be between 0% and 999%.")
    return int(apr * 100)


def debt_form_values(form) -> dict:
    lender = form.get("lender", "").strip()
    if not lender or len(lender) > 100:
        raise ValueError("Add a lender name (maximum 100 characters).")
    debt_type = form.get("debt_type", "other")
    if debt_type not in {"credit_card", "loan", "overdraft", "bnpl", "priority", "personal", "other"}:
        raise ValueError("Choose a valid debt type.")
    due_raw = form.get("due_day", "").strip()
    due_day = int(due_raw) if due_raw else None
    if due_day is not None and not 1 <= due_day <= 31:
        raise ValueError("Due day must be from 1 to 31.")
    return {
        "lender": lender,
        "debt_type": debt_type,
        "apr_basis_points": apr_to_basis_points(form.get("apr")),
        "minimum_payment_pence": optional_money_to_pence(form.get("minimum_payment")),
        "due_day": due_day,
        "priority": 1 if form.get("priority") == "1" or debt_type == "priority" else 0,
        "notes": form.get("notes", "").strip()[:500],
    }


def valid_month(value: str | None) -> str:
    return value if value and MONTH_RE.fullmatch(value) else date.today().strftime("%Y-%m")


def create_app(test_config: dict | None = None) -> Flask:
    app = Flask(__name__)
    app.config.from_mapping(
        SECRET_KEY=os.environ.get("EXPENSE_SECRET_KEY") or secrets.token_urlsafe(32),
        DATABASE=os.environ.get(
            "EXPENSE_DB_PATH",
            str(Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "expense-manager" / "expenses.sqlite3"),
        ),
    )
    if test_config:
        app.config.update(test_config)

    def db() -> sqlite3.Connection:
        connection = sqlite3.connect(app.config["DATABASE"])
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    def init_db() -> None:
        path = Path(app.config["DATABASE"])
        path.parent.mkdir(parents=True, exist_ok=True)
        with db() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS categories (
                    id INTEGER PRIMARY KEY,
                    name TEXT NOT NULL COLLATE NOCASE UNIQUE,
                    kind TEXT NOT NULL CHECK (kind IN ('expense', 'income')),
                    colour TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS transactions (
                    id INTEGER PRIMARY KEY,
                    occurred_on TEXT NOT NULL,
                    kind TEXT NOT NULL CHECK (kind IN ('expense', 'income')),
                    amount_pence INTEGER NOT NULL CHECK (amount_pence > 0),
                    merchant TEXT NOT NULL,
                    category_id INTEGER NOT NULL REFERENCES categories(id),
                    payment_method TEXT NOT NULL DEFAULT '',
                    notes TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_transactions_date ON transactions(occurred_on DESC);
                CREATE INDEX IF NOT EXISTS idx_transactions_category ON transactions(category_id);
                CREATE TABLE IF NOT EXISTS budgets (
                    month TEXT NOT NULL,
                    category_id INTEGER NOT NULL REFERENCES categories(id) ON DELETE CASCADE,
                    amount_pence INTEGER NOT NULL CHECK (amount_pence > 0),
                    PRIMARY KEY (month, category_id)
                );
                CREATE TABLE IF NOT EXISTS debts (
                    id INTEGER PRIMARY KEY,
                    lender TEXT NOT NULL,
                    starting_balance_pence INTEGER NOT NULL CHECK (starting_balance_pence > 0),
                    notes TEXT NOT NULL DEFAULT '',
                    created_on TEXT NOT NULL,
                    archived INTEGER NOT NULL DEFAULT 0 CHECK (archived IN (0, 1))
                );
                CREATE TABLE IF NOT EXISTS debt_payments (
                    id INTEGER PRIMARY KEY,
                    debt_id INTEGER NOT NULL REFERENCES debts(id) ON DELETE CASCADE,
                    transaction_id INTEGER NOT NULL UNIQUE REFERENCES transactions(id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_debt_payments_debt ON debt_payments(debt_id);
                CREATE TABLE IF NOT EXISTS app_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                """
            )
            debt_columns = {row["name"] for row in connection.execute("PRAGMA table_info(debts)")}
            migrations = {
                "debt_type": "TEXT NOT NULL DEFAULT 'other'",
                "apr_basis_points": "INTEGER NOT NULL DEFAULT 0",
                "minimum_payment_pence": "INTEGER NOT NULL DEFAULT 0",
                "due_day": "INTEGER",
                "priority": "INTEGER NOT NULL DEFAULT 0",
            }
            for column, definition in migrations.items():
                if column not in debt_columns:
                    connection.execute(f"ALTER TABLE debts ADD COLUMN {column} {definition}")
            connection.execute(
                "INSERT OR IGNORE INTO app_settings(key, value) VALUES ('debt_strategy', 'avalanche')"
            )
            for name, colour in CATEGORY_COLOURS.items():
                kind = "income" if name == "Salary" else "expense"
                connection.execute(
                    "INSERT OR IGNORE INTO categories(name, kind, colour) VALUES (?, ?, ?)",
                    (name, kind, colour),
                )

    def csrf_token() -> str:
        session.setdefault("csrf_token", secrets.token_urlsafe(24))
        return session["csrf_token"]

    @app.before_request
    def protect_forms():
        if request.method == "POST":
            supplied = request.form.get("csrf_token", "")
            expected = session.get("csrf_token", "")
            if not supplied or not expected or not secrets.compare_digest(supplied, expected):
                abort(400, "Invalid or expired form token. Refresh and try again.")

    @app.context_processor
    def template_helpers():
        return {"csrf_token": csrf_token, "today": date.today().isoformat()}

    @app.template_filter("money")
    def money(value: int | None) -> str:
        return f"£{(value or 0) / 100:,.2f}"

    @app.get("/")
    def dashboard():
        month = valid_month(request.args.get("month"))
        with db() as connection:
            totals = connection.execute(
                """SELECT
                    COALESCE(SUM(CASE WHEN kind='income' THEN amount_pence END), 0) income,
                    COALESCE(SUM(CASE WHEN kind='expense' THEN amount_pence END), 0) expense
                   FROM transactions WHERE substr(occurred_on, 1, 7)=?""",
                (month,),
            ).fetchone()
            categories = connection.execute(
                """SELECT c.name, c.colour, SUM(t.amount_pence) amount_pence
                   FROM transactions t JOIN categories c ON c.id=t.category_id
                   WHERE t.kind='expense' AND substr(t.occurred_on, 1, 7)=?
                   GROUP BY c.id ORDER BY amount_pence DESC""",
                (month,),
            ).fetchall()
            budget = connection.execute(
                "SELECT COALESCE(SUM(amount_pence), 0) total FROM budgets WHERE month=?", (month,)
            ).fetchone()["total"]
            recent = connection.execute(
                """SELECT t.*, c.name category, c.colour FROM transactions t
                   JOIN categories c ON c.id=t.category_id
                   ORDER BY occurred_on DESC, t.id DESC LIMIT 8"""
            ).fetchall()
            days = connection.execute(
                """SELECT occurred_on day, SUM(amount_pence) amount_pence FROM transactions
                   WHERE kind='expense' AND substr(occurred_on, 1, 7)=?
                   GROUP BY occurred_on ORDER BY occurred_on""",
                (month,),
            ).fetchall()
            debt_summary = connection.execute(
                """SELECT COALESCE(SUM(d.starting_balance_pence), 0) starting,
                    COALESCE(SUM((SELECT COALESCE(SUM(t.amount_pence), 0)
                        FROM debt_payments dp JOIN transactions t ON t.id=dp.transaction_id
                        WHERE dp.debt_id=d.id)), 0) paid
                   FROM debts d WHERE d.archived=0"""
            ).fetchone()
            transaction_count = connection.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
        highest = max((row["amount_pence"] for row in days), default=1)
        category_total = sum(row["amount_pence"] for row in categories) or 1
        return render_template(
            "dashboard.html", month=month, totals=totals, budget=budget, recent=recent,
            categories=categories, category_total=category_total, days=days, highest=highest,
            debt_summary=debt_summary,
            first_run=transaction_count == 0 and debt_summary["starting"] == 0,
        )

    @app.route("/transactions", methods=["GET", "POST"])
    def transactions():
        if request.method == "POST":
            try:
                kind = request.form.get("kind", "expense")
                if kind not in {"expense", "income"}:
                    raise ValueError("Choose a valid transaction type.")
                amount = money_to_pence(request.form.get("amount", ""))
                occurred_on = date.fromisoformat(request.form.get("occurred_on", ""))
                merchant = request.form.get("merchant", "").strip()
                category_id = int(request.form.get("category_id", ""))
                if not merchant or len(merchant) > 100:
                    raise ValueError("Add a merchant or description (maximum 100 characters).")
                with db() as connection:
                    category = connection.execute(
                        "SELECT id FROM categories WHERE id=? AND kind=?", (category_id, kind)
                    ).fetchone()
                    if not category:
                        raise ValueError("Choose a category matching the transaction type.")
                    connection.execute(
                        """INSERT INTO transactions
                           (occurred_on, kind, amount_pence, merchant, category_id, payment_method, notes)
                           VALUES (?, ?, ?, ?, ?, ?, ?)""",
                        (occurred_on.isoformat(), kind, amount, merchant, category_id,
                         request.form.get("payment_method", "").strip()[:40],
                         request.form.get("notes", "").strip()[:500]),
                    )
                flash("Transaction saved.", "success")
                return redirect(url_for("transactions", month=occurred_on.strftime("%Y-%m")))
            except (ValueError, TypeError) as exc:
                flash(str(exc), "error")

        month = valid_month(request.args.get("month"))
        query = request.args.get("q", "").strip()[:100]
        kind_filter = request.args.get("kind", "")
        add_kind = request.args.get("add_kind", "expense")
        if add_kind not in {"expense", "income"}:
            add_kind = "expense"
        clauses = ["substr(t.occurred_on, 1, 7)=?"]
        params: list[object] = [month]
        if kind_filter in {"expense", "income"}:
            clauses.append("t.kind=?")
            params.append(kind_filter)
        if query:
            clauses.append("(t.merchant LIKE ? OR t.notes LIKE ? OR c.name LIKE ?)")
            params.extend([f"%{query}%"] * 3)
        with db() as connection:
            rows = connection.execute(
                f"""SELECT t.*, c.name category, c.colour FROM transactions t
                    JOIN categories c ON c.id=t.category_id
                    WHERE {' AND '.join(clauses)} ORDER BY t.occurred_on DESC, t.id DESC""",
                params,
            ).fetchall()
            categories = connection.execute("SELECT * FROM categories ORDER BY kind, name").fetchall()
        return render_template(
            "transactions.html", rows=rows, categories=categories, month=month,
            query=query, kind_filter=kind_filter, add_kind=add_kind,
        )

    @app.post("/transactions/<int:transaction_id>/delete")
    def delete_transaction(transaction_id: int):
        with db() as connection:
            connection.execute("DELETE FROM transactions WHERE id=?", (transaction_id,))
        flash("Transaction deleted.", "success")
        return redirect(request.form.get("next") or url_for("transactions"))

    @app.route("/budgets", methods=["GET", "POST"])
    def budgets():
        month = valid_month(request.values.get("month"))
        if request.method == "POST":
            try:
                category_id = int(request.form.get("category_id", ""))
                amount = money_to_pence(request.form.get("amount", ""))
                with db() as connection:
                    exists = connection.execute(
                        "SELECT id FROM categories WHERE id=? AND kind='expense'", (category_id,)
                    ).fetchone()
                    if not exists:
                        raise ValueError("Choose a valid expense category.")
                    connection.execute(
                        """INSERT INTO budgets(month, category_id, amount_pence) VALUES (?, ?, ?)
                           ON CONFLICT(month, category_id) DO UPDATE SET amount_pence=excluded.amount_pence""",
                        (month, category_id, amount),
                    )
                flash("Budget updated.", "success")
                return redirect(url_for("budgets", month=month))
            except (ValueError, TypeError) as exc:
                flash(str(exc), "error")
        with db() as connection:
            rows = connection.execute(
                """SELECT c.id, c.name, c.colour, COALESCE(b.amount_pence, 0) budget,
                    COALESCE(SUM(t.amount_pence), 0) spent
                   FROM categories c
                   LEFT JOIN budgets b ON b.category_id=c.id AND b.month=?
                   LEFT JOIN transactions t ON t.category_id=c.id AND t.kind='expense'
                       AND substr(t.occurred_on, 1, 7)=?
                   WHERE c.kind='expense' GROUP BY c.id ORDER BY c.name""",
                (month, month),
            ).fetchall()
        return render_template("budgets.html", rows=rows, month=month)

    @app.post("/budgets/<int:category_id>/delete")
    def delete_budget(category_id: int):
        month = valid_month(request.form.get("month"))
        with db() as connection:
            connection.execute("DELETE FROM budgets WHERE month=? AND category_id=?", (month, category_id))
        flash("Budget removed.", "success")
        return redirect(url_for("budgets", month=month))

    @app.route("/debts", methods=["GET", "POST"])
    def debts():
        if request.method == "POST":
            try:
                values = debt_form_values(request.form)
                balance = money_to_pence(request.form.get("balance", ""))
                with db() as connection:
                    connection.execute(
                        """INSERT INTO debts
                           (lender, starting_balance_pence, notes, created_on, debt_type,
                            apr_basis_points, minimum_payment_pence, due_day, priority)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (values["lender"], balance, values["notes"], date.today().isoformat(),
                         values["debt_type"], values["apr_basis_points"], values["minimum_payment_pence"],
                         values["due_day"], values["priority"]),
                    )
                flash("Debt added.", "success")
                return redirect(url_for("debts"))
            except ValueError as exc:
                flash(str(exc), "error")

        current_month = date.today().strftime("%Y-%m")
        with db() as connection:
            raw_rows = connection.execute(
                """SELECT d.*, COALESCE(SUM(t.amount_pence), 0) paid_pence,
                    d.starting_balance_pence - COALESCE(SUM(t.amount_pence), 0) outstanding_pence,
                    COALESCE(SUM(CASE WHEN substr(t.occurred_on, 1, 7)=? THEN t.amount_pence ELSE 0 END), 0) monthly_paid_pence,
                    COUNT(dp.id) payment_count
                   FROM debts d
                   LEFT JOIN debt_payments dp ON dp.debt_id=d.id
                   LEFT JOIN transactions t ON t.id=dp.transaction_id
                   WHERE d.archived=0 GROUP BY d.id""",
                (current_month,),
            ).fetchall()
            cash = connection.execute(
                """SELECT COALESCE(SUM(CASE WHEN kind='income' THEN amount_pence ELSE -amount_pence END), 0)
                   available FROM transactions"""
            ).fetchone()["available"]
            history = connection.execute(
                """SELECT dp.id, d.lender, t.occurred_on, t.amount_pence
                   FROM debt_payments dp JOIN debts d ON d.id=dp.debt_id
                   JOIN transactions t ON t.id=dp.transaction_id
                   ORDER BY t.occurred_on DESC, dp.id DESC LIMIT 12"""
            ).fetchall()
            strategy = connection.execute(
                "SELECT value FROM app_settings WHERE key='debt_strategy'"
            ).fetchone()["value"]
        rows = [dict(row) for row in raw_rows]
        if strategy not in {"avalanche", "snowball"}:
            strategy = "avalanche"
        def strategy_key(row):
            strategy_value = -row["apr_basis_points"] if strategy == "avalanche" else row["outstanding_pence"]
            return (0 if row["priority"] else 1, strategy_value, row["outstanding_pence"], row["id"])
        rows.sort(key=strategy_key)
        today_date = date.today()
        minimum_required = 0
        for row in rows:
            row["minimum_remaining_pence"] = max(
                min(row["minimum_payment_pence"], row["outstanding_pence"]) - row["monthly_paid_pence"], 0
            )
            minimum_required += row["minimum_remaining_pence"]
            row["due_status"] = ""
            row["due_tone"] = ""
            if row["due_day"] and row["minimum_remaining_pence"]:
                last_day = monthrange(today_date.year, today_date.month)[1]
                due_date = date(today_date.year, today_date.month, min(row["due_day"], last_day))
                days_until = (due_date - today_date).days
                if days_until < 0:
                    row["due_status"], row["due_tone"] = "Minimum overdue", "danger"
                elif days_until == 0:
                    row["due_status"], row["due_tone"] = "Minimum due today", "warning"
                elif days_until <= 7:
                    row["due_status"], row["due_tone"] = f"Minimum due in {days_until} days", "warning"
            elif row["minimum_payment_pence"] and not row["minimum_remaining_pence"]:
                row["due_status"], row["due_tone"] = "This month’s minimum covered", "success"
        total_starting = sum(row["starting_balance_pence"] for row in rows)
        total_paid = sum(row["paid_pence"] for row in rows)
        available_income = max(cash, 0)
        target = next((row for row in rows if row["outstanding_pence"] > 0), None)
        return render_template(
            "debts.html", rows=rows, history=history, available_income=available_income,
            total_starting=total_starting, total_paid=total_paid,
            total_outstanding=max(total_starting - total_paid, 0),
            minimum_required=minimum_required, minimum_shortfall=max(minimum_required - available_income, 0),
            strategy=strategy, target=target,
        )

    @app.post("/debts/strategy")
    def set_debt_strategy():
        strategy = request.form.get("strategy", "")
        if strategy not in {"avalanche", "snowball"}:
            abort(400, "Unsupported debt strategy.")
        with db() as connection:
            connection.execute(
                """INSERT INTO app_settings(key, value) VALUES ('debt_strategy', ?)
                   ON CONFLICT(key) DO UPDATE SET value=excluded.value""",
                (strategy,),
            )
        flash("Payoff strategy updated.", "success")
        return redirect(url_for("debts"))

    @app.post("/debts/<int:debt_id>/edit")
    def edit_debt(debt_id: int):
        try:
            values = debt_form_values(request.form)
            current_balance = money_to_pence(request.form.get("balance", ""))
            with db() as connection:
                paid = connection.execute(
                    """SELECT COALESCE(SUM(t.amount_pence), 0) paid FROM debt_payments dp
                       JOIN transactions t ON t.id=dp.transaction_id WHERE dp.debt_id=?""",
                    (debt_id,),
                ).fetchone()["paid"]
                updated = connection.execute(
                    """UPDATE debts SET lender=?, starting_balance_pence=?, notes=?, debt_type=?,
                       apr_basis_points=?, minimum_payment_pence=?, due_day=?, priority=?
                       WHERE id=? AND archived=0""",
                    (values["lender"], current_balance + paid, values["notes"], values["debt_type"],
                     values["apr_basis_points"], values["minimum_payment_pence"], values["due_day"],
                     values["priority"], debt_id),
                )
                if not updated.rowcount:
                    raise ValueError("Debt not found.")
            flash("Debt details updated.", "success")
        except (ValueError, TypeError) as exc:
            flash(str(exc), "error")
        return redirect(url_for("debts"))

    @app.post("/debts/<int:debt_id>/pay")
    def pay_debt(debt_id: int):
        try:
            amount = money_to_pence(request.form.get("amount", ""))
            paid_on = date.fromisoformat(request.form.get("paid_on", ""))
            if paid_on > date.today():
                raise ValueError("Debt payments cannot be dated in the future.")
            with db() as connection:
                connection.execute("BEGIN IMMEDIATE")
                debt = connection.execute(
                    """SELECT d.*, d.starting_balance_pence - COALESCE(SUM(t.amount_pence), 0) outstanding
                       FROM debts d LEFT JOIN debt_payments dp ON dp.debt_id=d.id
                       LEFT JOIN transactions t ON t.id=dp.transaction_id
                       WHERE d.id=? AND d.archived=0 GROUP BY d.id""",
                    (debt_id,),
                ).fetchone()
                if not debt:
                    raise ValueError("Debt not found.")
                available = connection.execute(
                    """SELECT COALESCE(SUM(CASE WHEN kind='income' THEN amount_pence ELSE -amount_pence END), 0)
                       FROM transactions"""
                ).fetchone()[0]
                if amount > debt["outstanding"]:
                    raise ValueError("Payment cannot be more than the outstanding balance.")
                if amount > max(available, 0):
                    raise ValueError("Not enough available income. Add income or reduce the payment.")
                category_id = connection.execute(
                    "SELECT id FROM categories WHERE name='Debt payment' AND kind='expense'"
                ).fetchone()["id"]
                cursor = connection.execute(
                    """INSERT INTO transactions
                       (occurred_on, kind, amount_pence, merchant, category_id, payment_method, notes)
                       VALUES (?, 'expense', ?, ?, ?, ?, ?)""",
                    (paid_on.isoformat(), amount, f'Debt payment · {debt["lender"]}', category_id,
                     request.form.get("payment_method", "").strip()[:40], "Linked debt repayment"),
                )
                connection.execute(
                    "INSERT INTO debt_payments(debt_id, transaction_id) VALUES (?, ?)",
                    (debt_id, cursor.lastrowid),
                )
            flash(f'Payment to {debt["lender"]} recorded.', "success")
        except (ValueError, TypeError) as exc:
            flash(str(exc), "error")
        return redirect(url_for("debts"))

    @app.post("/debt-payments/<int:payment_id>/delete")
    def delete_debt_payment(payment_id: int):
        with db() as connection:
            payment = connection.execute(
                "SELECT transaction_id FROM debt_payments WHERE id=?", (payment_id,)
            ).fetchone()
            if payment:
                connection.execute("DELETE FROM transactions WHERE id=?", (payment["transaction_id"],))
                flash("Debt payment undone and income returned to the available pool.", "success")
        return redirect(url_for("debts"))

    @app.post("/debts/<int:debt_id>/archive")
    def archive_debt(debt_id: int):
        with db() as connection:
            connection.execute("UPDATE debts SET archived=1 WHERE id=?", (debt_id,))
        flash("Debt archived.", "success")
        return redirect(url_for("debts"))

    @app.get("/export.csv")
    def export_csv():
        with db() as connection:
            rows = connection.execute(
                """SELECT t.occurred_on, t.kind, t.amount_pence, t.merchant, c.name category,
                    t.payment_method, t.notes FROM transactions t
                   JOIN categories c ON c.id=t.category_id ORDER BY t.occurred_on DESC, t.id DESC"""
            ).fetchall()
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["date", "type", "amount_gbp", "merchant", "category", "payment_method", "notes"])
        for row in rows:
            writer.writerow([row["occurred_on"], row["kind"], f'{row["amount_pence"] / 100:.2f}',
                             row["merchant"], row["category"], row["payment_method"], row["notes"]])
        return Response(
            output.getvalue(), mimetype="text/csv",
            headers={"Content-Disposition": f"attachment; filename=expenses-{date.today().isoformat()}.csv"},
        )

    @app.get("/health")
    def health():
        try:
            with db() as connection:
                connection.execute("SELECT 1").fetchone()
            return {"ok": True, "service": "expense-manager", "database": "ready"}
        except sqlite3.Error:
            return {"ok": False, "service": "expense-manager", "database": "unavailable"}, 503

    init_db()
    return app


app = create_app()

if __name__ == "__main__":
    app.run(
        host=os.environ.get("EXPENSE_BIND_HOST", "127.0.0.1"),
        port=int(os.environ.get("EXPENSE_PORT", "8082")),
        debug=False,
    )
