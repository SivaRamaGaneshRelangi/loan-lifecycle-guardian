import os
import pathlib
import shutil
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
os.environ["DATABASE_URL"] = "sqlite:///./test_guardian.db"
os.environ["GEMINI_API_KEY"] = ""
os.environ["GOOGLE_API_KEY"] = ""
os.environ["SEED_DEMO"] = "1"
os.environ["UPLOAD_DIR"] = "./test_uploads"

import pytest  # noqa: E402

DB = pathlib.Path("test_guardian.db")


@pytest.fixture(scope="session")
def client():
    if DB.exists():
        DB.unlink()
    shutil.rmtree("test_uploads", ignore_errors=True)
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app) as c:
        yield c


def login(client, u, p):
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}
