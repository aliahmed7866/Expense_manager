import csv
import io

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
