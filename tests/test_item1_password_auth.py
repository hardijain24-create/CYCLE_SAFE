from fastapi.testclient import TestClient


def test_signup_then_login_with_email_password():
    from cyclesafe.api.main import app
    client = TestClient(app)

    payload = {
        "email": "Ada@Example.com",
        "password": "correcthorse",
        "name": "Ada",
        "age": 30,
        "stage": "regular",
        "country": "India",
        "state": "Maharashtra",
        "city": "Mumbai",
    }
    created = client.post("/signup", json=payload)
    assert created.status_code == 200, created.text
    body = created.json()
    assert body["email"] == "ada@example.com"
    assert "token" in body
    assert "password" not in body
    assert "password_hash" not in str(body)

    dup = client.post("/signup", json=payload)
    assert dup.status_code == 409

    bad = client.post("/login", json={"email": "ada@example.com", "password": "wrong-password"})
    assert bad.status_code == 401

    ok = client.post("/login", json={"email": "Ada@Example.com", "password": "correcthorse"})
    assert ok.status_code == 200, ok.text
    token = ok.json()["token"]
    user_id = ok.json()["user_id"]

    exported = client.get(f"/export?user_id={user_id}", headers={"Authorization": f"Bearer {token}"})
    assert exported.status_code == 200
    assert "password_hash" not in exported.text
    assert "correcthorse" not in exported.text
