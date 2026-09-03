import csv
import io
import re
import sqlite3
from datetime import date

import pytest

from app import create_app, money_to_pence


@pytest.fixture()
def client(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "test.sqlite3"), "SECRET_KEY": "test"})
    with app.test_client() as client:
        client.get("/")
        yield client


def token(client):
    with client.session_transaction() as session:
        return session["csrf_token"]


def test_money_to_pence_rounds():
    assert money_to_pence("12.345") == 1235
    with pytest.raises(ValueError):
        money_to_pence("0")


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json["ok"] is True


def test_add_transaction_and_dashboard(client):
    page = client.get("/transactions")
    assert page.status_code == 200
    html = page.get_data(as_text=True)
    category_id = html.split('data-kind="expense"')[0].rsplit('value="', 1)[1].split('"', 1)[0]
    response = client.post(
        "/transactions",
        data={"csrf_token": token(client), "kind": "expense", "amount": "12.50",
              "merchant": "Corner Shop", "occurred_on": "2026-09-03", "category_id": category_id},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert "Corner Shop" in response.get_data(as_text=True)
    dashboard = client.get("/?month=2026-09").get_data(as_text=True)
    assert "£12.50" in dashboard


def test_csrf_required(client):
    assert client.post("/transactions", data={}).status_code == 400


def test_csv_export(client):
    response = client.get("/export.csv")
    rows = list(csv.reader(io.StringIO(response.get_data(as_text=True))))
    assert rows[0][:4] == ["date", "type", "amount_gbp", "merchant"]


def find_category_id(html, name):
    match = re.search(rf'<option value="(\d+)" data-kind="[^"]+"[^>]*>{re.escape(name)}</option>', html)
    assert match
    return match.group(1)


def add_income(client, amount="600.00"):
    html = client.get("/transactions").get_data(as_text=True)
    client.post(
        "/transactions",
        data={"csrf_token": token(client), "kind": "income", "amount": amount,
              "merchant": "Monthly income", "occurred_on": "2026-09-03",
              "category_id": find_category_id(html, "Salary")},
    )


def test_debt_payment_uses_available_income_and_can_be_undone(client):
    client.get("/debts")
    client.post(
        "/debts",
        data={"csrf_token": token(client), "lender": "Example Bank", "balance": "1000.00"},
    )
    add_income(client)
    response = client.post(
        "/debts/1/pay",
        data={"csrf_token": token(client), "amount": "250.00", "paid_on": "2026-09-03"},
        follow_redirects=True,
    )
    page = response.get_data(as_text=True)
    assert "Payment to Example Bank recorded." in page
    assert "£750.00" in page
    assert "£350.00" in page
    assert "£750.00" in client.get("/?month=2026-09").get_data(as_text=True)

    undone = client.post(
        "/debt-payments/1/delete", data={"csrf_token": token(client)}, follow_redirects=True
    ).get_data(as_text=True)
    assert "£1,000.00" in undone
    assert "£600.00" in undone


def test_debt_payment_cannot_exceed_available_income(client):
    client.get("/debts")
    client.post(
        "/debts",
        data={"csrf_token": token(client), "lender": "Example Bank", "balance": "100.00"},
    )
    response = client.post(
        "/debts/1/pay",
        data={"csrf_token": token(client), "amount": "10.00", "paid_on": "2026-09-03"},
        follow_redirects=True,
    )
    assert "Not enough available income" in response.get_data(as_text=True)


def add_debt(client, lender, balance, apr, minimum="0", priority=False):
    client.post(
        "/debts",
        data={"csrf_token": token(client), "lender": lender, "balance": balance,
              "debt_type": "credit_card", "apr": apr, "minimum_payment": minimum,
              "due_day": "20", "priority": "1" if priority else "0"},
    )


def test_payoff_strategy_reorders_focus_without_overriding_priority(client):
    client.get("/debts")
    add_debt(client, "High APR Card", "1000", "29.9", "50")
    add_debt(client, "Small Card", "100", "5", "10")
    page = client.get("/debts").get_data(as_text=True)
    assert page.index("High APR Card") < page.index("Small Card")

    page = client.post(
        "/debts/strategy",
        data={"csrf_token": token(client), "strategy": "snowball"},
        follow_redirects=True,
    ).get_data(as_text=True)
    assert page.index("Small Card") < page.index("High APR Card")

    client.post(
        "/debts/1/edit",
        data={"csrf_token": token(client), "lender": "High APR Card", "balance": "1000",
              "debt_type": "credit_card", "apr": "29.9", "minimum_payment": "50",
              "due_day": "20", "priority": "1"},
    )
    page = client.get("/debts").get_data(as_text=True)
    assert page.index("High APR Card") < page.index("Small Card")
    assert "Priority" in page


def test_editing_current_debt_balance_preserves_payment_history(client):
    client.get("/debts")
    add_debt(client, "Flexible Card", "1000", "19.9")
    add_income(client)
    client.post(
        "/debts/1/pay",
        data={"csrf_token": token(client), "amount": "100", "paid_on": date.today().isoformat()},
    )
    page = client.post(
        "/debts/1/edit",
        data={"csrf_token": token(client), "lender": "Flexible Card", "balance": "800",
              "debt_type": "credit_card", "apr": "18.9", "minimum_payment": "40", "due_day": "25"},
        follow_redirects=True,
    ).get_data(as_text=True)
    assert "Debt details updated." in page
    assert "£800.00" in page
    assert "£100.00 paid" in page


def test_existing_debt_database_is_migrated(tmp_path):
    database = tmp_path / "legacy.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.execute(
            """CREATE TABLE debts (id INTEGER PRIMARY KEY, lender TEXT NOT NULL,
               starting_balance_pence INTEGER NOT NULL, notes TEXT NOT NULL DEFAULT '',
               created_on TEXT NOT NULL, archived INTEGER NOT NULL DEFAULT 0)"""
        )
    create_app({"TESTING": True, "DATABASE": str(database), "SECRET_KEY": "test"})
    with sqlite3.connect(database) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(debts)")}
    assert {"debt_type", "apr_basis_points", "minimum_payment_pence", "due_day", "priority"} <= columns
