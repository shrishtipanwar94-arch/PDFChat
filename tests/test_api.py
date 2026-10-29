"""End-to-end API tests against the real database, with the LLM stubbed out.

Skipped when DATABASE_URL is unset or the database is unreachable.
"""

import uuid

import pymupdf
import psycopg
import pytest

from app.config import settings

try:
    psycopg.connect(settings.database_url, connect_timeout=3).close()
    DB_OK = bool(settings.database_url)
except Exception:
    DB_OK = False

pytestmark = pytest.mark.skipif(not DB_OK, reason="database not available")


def make_pdf() -> bytes:
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), "The office cat is named Biscuit.")
    doc.new_page().insert_text((72, 72), "Refunds are allowed within 30 days of purchase.")
    data = doc.tobytes()
    doc.close()
    return data


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        yield c


@pytest.fixture
def stub_llm(monkeypatch):
    from app import llm, main

    provider = llm.Provider("stub", "http://stub", "stub-model")

    async def complete(messages, providers=None, timeout=None):
        return "Refunds within 30 days (p. 2).", provider

    async def stream(messages, providers=None, timeout=None):
        yield {"type": "provider", "provider": "stub", "model": "stub-model"}
        for t in ["Refunds ", "within 30 days."]:
            yield {"type": "token", "text": t}
        yield {"type": "done", "provider": "stub"}

    monkeypatch.setattr(main.llm, "complete", complete)
    monkeypatch.setattr(main.llm, "stream", stream)


def h(session):
    return {"X-Chat-Session-Id": str(session)}


def upload(client, session, data=None, name="t.pdf"):
    return client.post("/api/documents", headers=h(session), files={"file": (name, data or make_pdf(), "application/pdf")})


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200 and r.json()["database"] == "ok"


def test_missing_or_bad_session_header(client):
    assert client.get("/api/documents").status_code == 400
    assert client.get("/api/documents", headers={"X-Chat-Session-Id": "nope"}).status_code == 400


def test_rejects_non_pdf(client):
    r = upload(client, uuid.uuid4(), data=b"just text, renamed to .pdf")
    assert r.status_code == 415


def test_scanned_pdf_is_marked_failed(client):
    doc = pymupdf.open()
    doc.new_page()
    blank = doc.tobytes()
    r = upload(client, uuid.uuid4(), data=blank)
    assert r.status_code == 201
    assert r.json()["status"] == "failed" and "OCR" in r.json()["error"]


def test_upload_chat_and_isolation(client, stub_llm):
    me, other = uuid.uuid4(), uuid.uuid4()
    r = upload(client, me)
    assert r.status_code == 201, r.text
    doc = r.json()
    assert doc["status"] == "ready" and doc["pages"] == 2

    docs = client.get("/api/documents", headers=h(me)).json()["documents"]
    assert [d["id"] for d in docs] == [doc["id"]] and docs[0]["chunks"] >= 2
    assert client.get("/api/documents", headers=h(other)).json()["documents"] == []

    body = {"documentId": doc["id"], "question": "What is the refund policy?"}
    r = client.post("/api/chat", headers=h(me), json=body)
    assert r.status_code == 200
    res = r.json()
    assert res["provider"] == "stub"
    assert res["sources"][0]["page"] == 2  # retrieval puts the refund page first

    # Another session cannot query, or delete, this document.
    assert client.post("/api/chat", headers=h(other), json=body).status_code == 404
    assert client.delete(f"/api/documents/{doc['id']}", headers=h(other)).status_code == 404

    with client.stream("POST", "/api/chat/stream", headers=h(me), json=body) as s:
        text = "".join(s.iter_text())
    assert text.startswith("event: sources")
    assert "event: token" in text and "event: done" in text

    assert client.delete(f"/api/documents/{doc['id']}", headers=h(me)).status_code == 204
    assert client.get("/api/documents", headers=h(me)).json()["documents"] == []
