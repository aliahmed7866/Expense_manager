import csv
import io
import re
import sqlite3
from datetime import date

import pytest

from app import (
    FINANCIAL_PLAN_DEFAULTS,
    build_financial_projection,
    create_app,
    money_to_pence,
    next_recurring_date,
)


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


def test_quick_actions_prefill_the_right_transaction_type(client):
    dashboard = client.get("/").get_data(as_text=True)
    assert "Add first income" in dashboard
    assert "Add expense" in dashboard
    assert "Home plan" in dashboard
    income_page = client.get("/transactions?add_kind=income#add").get_data(as_text=True)
    assert 'name="kind" value="income" checked' in income_page


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


def test_home_plan_baseline_matches_financial_plan(client):
    page = client.get("/plan")
    assert page.status_code == 200
    html = page.get_data(as_text=True)
    assert "Your route to the deposit" in html
    assert "£29,500.00" in html
    assert "£500.00" in html
    assert "2027-02" in html
    assert "Uses the £10k baseline" in html


def test_home_plan_projection_captures_expense_reduction_and_reserve():
    projection = build_financial_projection(dict(FINANCIAL_PLAN_DEFAULTS))
    assert projection["monthly_surplus_before"] == 200_000
    assert projection["monthly_surplus_after"] == 250_000
    assert projection["debt_free_month"] == "2027-02"
    assert projection["lisa"] == 2_500_000
    assert projection["deposit_pot"] == 3_050_000
    assert projection["safe_deposit"] == 2_950_000
    assert projection["gap"] == 50_000


def test_tracked_debt_replaces_plan_debt_baseline(client):
    client.get("/debts")
    add_debt(client, "Actual card", "8000", "24.9", "100")
    page = client.get("/plan").get_data(as_text=True)
    assert "Uses your tracked debts" in page
    assert "Uses the £10k baseline" not in page


def test_home_plan_settings_can_be_updated(client):
    client.get("/plan")
    data = {"csrf_token": token(client)}
    money_fields = [
        "gross_salary", "take_home", "normal_expenses", "travel_fund",
        "expense_reduction", "current_lisa", "cash_outside_lisa", "card_debt",
        "deposit_goal", "bonus_net", "buying_costs", "emergency_buffer",
        "lisa_one", "lisa_two", "lisa_contributed_current_year", "property_price", "pension_student",
    ]
    for field in money_fields:
        data[field] = "0"
    data.update({
        "take_home": "4100", "normal_expenses": "1650", "travel_fund": "300",
        "current_lisa": "15000", "card_debt": "10000", "deposit_goal": "30000",
        "start_month": "2026-10", "reduction_month": "2026-11",
        "bonus_month": "2027-03", "lisa_one_month": "2027-03",
        "lisa_two_month": "2027-04", "target_month": "2027-05",
        "travel_in_expenses": "no", "uk_nation": "England",
    })
    response = client.post("/plan", data=data, follow_redirects=True)
    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "Home plan updated with your latest figures" in html
    assert 'name="take_home" inputmode="decimal" value="4100.00"' in html
    assert 'name="uk_nation" maxlength="40" value="England"' in html

def test_monthly_recurrence_handles_end_of_month():
    assert next_recurring_date(date(2026, 1, 31), "monthly") == date(2026, 2, 28)
    assert next_recurring_date(date(2028, 1, 31), "monthly") == date(2028, 2, 29)

def test_recurring_bill_can_be_recorded_and_advanced(client):
    html = client.get("/recurring").get_data(as_text=True)
    bills_id = find_category_id(html, "Bills")
    response = client.post(
        "/recurring",
        data={
            "csrf_token": token(client),
            "kind": "expense",
            "amount": "49.99",
            "merchant": "Phone plan",
            "category_id": bills_id,
            "cadence": "monthly",
            "next_due": date.today().isoformat(),
        },
        follow_redirects=True,
    )
    page = response.get_data(as_text=True)
    assert "Phone plan" in page
    assert "£49.99" in page

    recorded = client.post(
        "/recurring/1/post",
        data={"csrf_token": token(client)},
        follow_redirects=True,
    ).get_data(as_text=True)
    assert "Entry recorded and next date scheduled." in recorded
    transactions = client.get(
        f"/transactions?month={date.today().strftime('%Y-%m')}"
    ).get_data(as_text=True)
    assert "Phone plan" in transactions
    assert "£49.99" in transactions

def test_recurring_entry_can_be_skipped_without_transaction(client):
    html = client.get("/recurring").get_data(as_text=True)
    salary_id = find_category_id(html, "Salary")
    client.post(
        "/recurring",
        data={
            "csrf_token": token(client),
            "kind": "income",
            "amount": "500.00",
            "merchant": "Side income",
            "category_id": salary_id,
            "cadence": "weekly",
            "next_due": date.today().isoformat(),
        },
    )
    page = client.post(
        "/recurring/1/skip",
        data={"csrf_token": token(client)},
        follow_redirects=True,
    ).get_data(as_text=True)
    assert "Occurrence skipped." in page
    assert (date.today() + date.resolution * 7).isoformat() in page
    assert "Side income" not in client.get(
        f"/transactions?month={date.today().strftime('%Y-%m')}"
    ).get_data(as_text=True)
