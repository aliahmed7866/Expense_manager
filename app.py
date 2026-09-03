from __future__ import annotations

import csv
import io
import os
import re
import secrets
import sqlite3
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
                """
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
        highest = max((row["amount_pence"] for row in days), default=1)
        category_total = sum(row["amount_pence"] for row in categories) or 1
        return render_template(
            "dashboard.html", month=month, totals=totals, budget=budget, recent=recent,
            categories=categories, category_total=category_total, days=days, highest=highest,
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
            query=query, kind_filter=kind_filter,
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
