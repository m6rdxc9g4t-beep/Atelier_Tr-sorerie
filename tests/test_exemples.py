"""Exemples de la suite : chaque histoire se charge (compte, opérations, budgets) et se retire sans reste."""

from pathlib import Path

EXEMPLES = Path(__file__).resolve().parents[1] / "exemples-suite"


def _count(api, url):
    return len(api.get(url).get_json()["items"])


def test_every_story_loads_with_one_budget_exceeded(api):
    histoires = api.get("/api/exemples-suite").get_json()["items"]
    assert len(histoires) >= 9
    for h in histoires:
        assert h["charge"] is False
        r = api.post(f"/api/exemples-suite/{h['id']}")
        assert r.status_code == 201, r.get_json()
        account_id = r.get_json()["account_id"]
        acc = api.get(f"/api/accounts/{account_id}").get_json()
        assert acc["transaction_count"] == h["operations"]
    month = histoires[0]["budgets_mois"]
    items = api.get(f"/api/budgets?month={month}").get_json()["items"]
    assert any(b["status"] == "depasse" for b in items)


def test_load_is_idempotent_and_remove_leaves_nothing(api):
    before = {"accounts": _count(api, "/api/accounts"), "categories": _count(api, "/api/categories"),
              "budgets": _count(api, "/api/budgets?month=2026-10")}
    first = api.post("/api/exemples-suite/studio-garance").get_json()
    again = api.post("/api/exemples-suite/studio-garance").get_json()
    assert again["deja_charge"] is True and again["account_id"] == first["account_id"]
    assert _count(api, "/api/accounts") == before["accounts"] + 1
    histoire = next(h for h in api.get("/api/exemples-suite").get_json()["items"] if h["id"] == "studio-garance")
    assert histoire["charge"] is True and histoire["account_id"] == first["account_id"]

    r = api.delete("/api/exemples-suite/studio-garance")
    assert r.status_code == 200, r.get_json()
    after = {"accounts": _count(api, "/api/accounts"), "categories": _count(api, "/api/categories"),
             "budgets": _count(api, "/api/budgets?month=2026-10")}
    assert after == before
    assert api.delete("/api/exemples-suite/studio-garance").status_code == 404


def test_existing_category_and_budget_are_kept(api):
    """Une catégorie du même nom est réutilisée ; un budget déjà posé n'est ni modifié ni supprimé."""
    cat = api.post("/api/categories", json={"name": "Matériel", "kind": "depense"}).get_json()
    api.post("/api/budgets", json={"category_id": cat["id"], "month": "2026-10", "amount_limit": "999"})
    res = api.post("/api/exemples-suite/studio-garance").get_json()
    assert "Matériel" in res["budgets_gardes"]
    assert cat["id"] not in res["categories_creees"]
    api.delete("/api/exemples-suite/studio-garance")
    budgets = api.get("/api/budgets?month=2026-10").get_json()["items"]
    assert [(b["category_name"], b["amount_limit_cents"]) for b in budgets] == [("Matériel", 99900)]


def test_unknown_story(api):
    assert api.post("/api/exemples-suite/inconnue").status_code == 404
    assert api.post("/api/exemples-suite/..%2Fx").status_code == 404


def test_missing_directory(app, api, tmp_path):
    app.config["EXEMPLES_DIR"] = tmp_path / "absent"
    assert api.get("/api/exemples-suite").get_json()["items"] == []


def test_examples_are_shipped():
    assert (EXEMPLES / "index.json").is_file()
