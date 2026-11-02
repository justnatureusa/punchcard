import pytest
from fastapi.testclient import TestClient

import db
import main

ADMIN = {"X-Admin-Password": "secret"}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "DATABASE", tmp_path / "test.db")
    monkeypatch.setattr(main, "ADMIN_PASSWORD", "secret")
    with TestClient(main.app) as client:
        yield client


def card_token(eid):
    conn = db.connect(main.DATABASE)
    token = db.get_employee(conn, eid)["card_token"]
    conn.close()
    return token


def test_page_loads(client):
    assert "Punchcard" in client.get("/").text


def test_admin_endpoints_need_the_password(client):
    assert client.get("/api/employees").status_code == 401
    assert client.get("/api/employees", headers={"X-Admin-Password": "wrong"}).status_code == 401
    assert client.get("/api/employees", headers=ADMIN).status_code == 200


def test_add_employee_scan_and_report(client):
    response = client.post("/api/employees", json={"eid": "E1", "name": "Mia"}, headers=ADMIN)
    assert response.status_code == 201
    assert client.get("/api/employees", headers=ADMIN).json() == [
        {"eid": "E1", "name": "Mia", "email": None}
    ]

    image = client.get("/api/employees/E1/card.png", headers=ADMIN)
    assert image.headers["content-type"] == "image/png"

    token = card_token("E1")
    clock_in = client.post("/api/punch", json={"token": token, "direction": "in"})
    assert clock_in.json() == {"name": "Mia", "direction": "in"}

    again = client.post("/api/punch", json={"token": token, "direction": "in"})
    assert again.status_code == 400
    assert again.json()["detail"] == "Mia is already clocked in"

    client.post("/api/punch", json={"token": token, "direction": "out"})
    [shift] = client.get("/api/report", headers=ADMIN).json()
    assert shift["name"] == "Mia"
    assert shift["clock_out"] != ""

    csv = client.get("/api/report.csv", headers=ADMIN).text
    assert csv.splitlines()[1].startswith("E1,Mia,")


def test_duplicate_employee_id_is_rejected(client):
    client.post("/api/employees", json={"eid": "E1", "name": "Mia"}, headers=ADMIN)
    response = client.post("/api/employees", json={"eid": "E1", "name": "Sam"}, headers=ADMIN)
    assert response.status_code == 409
    assert response.json()["detail"] == "Employee ID E1 already exists"


def test_blank_name_is_rejected(client):
    response = client.post("/api/employees", json={"eid": "E1", "name": "  "}, headers=ADMIN)
    assert response.status_code == 400


def test_edit_shift_uses_local_time(client):
    client.post("/api/employees", json={"eid": "E1", "name": "Mia"}, headers=ADMIN)
    token = card_token("E1")
    client.post("/api/punch", json={"token": token, "direction": "in"})
    client.post("/api/punch", json={"token": token, "direction": "out"})
    [shift] = client.get("/api/report", headers=ADMIN).json()

    response = client.put(
        f"/api/shifts/{shift['id']}",
        json={"clock_in": "2026-10-12T09:00", "clock_out": "2026-10-12T17:30"},
        headers=ADMIN,
    )
    assert response.status_code == 200

    [shift] = client.get("/api/report", headers=ADMIN).json()
    assert shift["clock_in"] == "2026-10-12 09:00 AM"  # Los Angeles time
    assert shift["clock_out_input"] == "2026-10-12T17:30"
    assert shift["hours"] == 8.5
    assert shift["edited"] is True


def test_bad_edit_is_rejected(client):
    client.post("/api/employees", json={"eid": "E1", "name": "Mia"}, headers=ADMIN)
    token = card_token("E1")
    client.post("/api/punch", json={"token": token, "direction": "in"})
    [shift] = client.get("/api/report", headers=ADMIN).json()

    response = client.put(
        f"/api/shifts/{shift['id']}",
        json={"clock_in": "2026-10-12T09:00", "clock_out": "2026-10-12T08:00"},
        headers=ADMIN,
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "Clock-out has to be after clock-in"
