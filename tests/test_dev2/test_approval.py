from fastapi.testclient import TestClient
from dev2_delivery.main import app
from shared.schema import CompanyResearch

client = TestClient(app)

def get_example():
    return CompanyResearch.model_config["json_schema_extra"]["example"]


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_generate_creates_job_and_redirects():
    r = client.post("/generate", json=get_example(), follow_redirects=False)
    assert r.status_code == 303
    assert "/review/" in r.headers["location"]


def test_review_page_loads():
    # Generate first to create a job
    r = client.post("/generate", json=get_example(), follow_redirects=True)
    assert r.status_code == 200
    assert "Acme Corp" in r.text


def test_history_page_loads():
    r = client.get("/history")
    assert r.status_code == 200


def test_review_404_for_unknown_job():
    r = client.get("/review/nonexistentjobid")
    assert r.status_code == 404