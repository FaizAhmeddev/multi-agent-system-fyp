"""Files attached in the chat: upload, use in a request, download; other users cannot read them."""
from __future__ import annotations

from bhelpers import auth_header, login

PW = "Plenty-Long-Passw0rd"


def test_attach_summarize_and_export(client, make_user, tmp_path, monkeypatch):
    monkeypatch.setenv("WORKSPACE_DATA_DIR", str(tmp_path))
    u = make_user("sana@company.pk", ["employee"])
    h = auth_header(login(client, email=u["email"], password=PW).json()["access_token"])
    r = client.post("/api/assistant/attachments", headers=h,
                    files={"file": ("expenses.csv", b"item,amount\nRent,250000\nSalaries,900000\nInternet,15000\n",
                                    "text/csv")})
    assert r.status_code == 201, r.text
    a = r.json()
    assert a["name"] == "expenses.csv" and a["chars"] > 20
    out = client.post("/api/assistant/messages", headers=h,
                      json={"text": "Analyze these expenses and export it as PDF", "attachments": [a["id"]]}).json()
    card = out["cards"][0]
    assert card["agent"] == "documents" and "expenses.csv" in card["title"]
    pdf = next(x for x in card["links"] if x["label"].startswith("Download"))
    got = client.get(pdf["url"], headers=h)
    assert got.status_code == 200 and got.content[:4] == b"%PDF"
    assert client.get(f"/api/assistant/attachments/{a['id']}", headers=h).content.startswith(b"item,amount")
    other = make_user("omar@company.pk", ["employee"])
    oh = auth_header(login(client, email=other["email"], password=PW).json()["access_token"])
    assert client.get(f"/api/assistant/attachments/{a['id']}", headers=oh).status_code == 404
    bad = client.post("/api/assistant/attachments", headers=h, files={"file": ("x.exe", b"MZ", "application/x")})
    assert bad.status_code == 422
