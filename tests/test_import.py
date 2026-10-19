import io
import json
from datetime import datetime

from openpyxl import Workbook

from services import importer

# Export typique d'une banque française : préambule, « ; », virgule décimale, Débit/Crédit, Windows-1252
BANK_CSV = """Compte courant n° 12345678;;;;
Période du 01/10/2026 au 18/10/2026;;;;
;;;;
Date opération;Date valeur;Libellé;Débit;Crédit
01/10/2026;01/10/2026;VIR SALAIRE OCTOBRE;;2 850,00
03/10/2026;03/10/2026;PRLV LOYER;950,00;
04/10/2026;05/10/2026;CB CARREFOUR 04/10;67,45;
04/10/2026;05/10/2026;CB CARREFOUR 04/10;67,45;
pas une date;;LIGNE CASSEE;10,00;
""".encode("cp1252")


def _account(api):
    return api.post("/api/accounts", json={"name": "Courant"}).get_json()["id"]


def _preview(api, account_id, raw, filename="releve.csv", mapping=None):
    data = {"file": (io.BytesIO(raw), filename), "account_id": str(account_id)}
    if mapping is not None:
        data["mapping"] = json.dumps(mapping)
    return api.post("/api/import/preview", data=data, content_type="multipart/form-data")


def test_detect_mapping_french_headers():
    m = importer.detect_mapping(["Date opération", "Date valeur", "Libellé", "Débit", "Crédit"])
    assert m == {"date": 0, "label": 2, "amount": None, "debit": 3, "credit": 4, "category": None}
    m = importer.detect_mapping(["Date", "Description", "Montant (EUR)", "Catégorie"])
    assert (m["date"], m["label"], m["amount"], m["category"]) == (0, 1, 2, 3)


def test_parsers():
    assert importer.parse_date("04/10/2026") == "2026-10-04"
    assert importer.parse_date("04/10/26") == "2026-10-04"
    assert importer.parse_date("2026-10-04T10:00:00") == "2026-10-04"
    assert importer.parse_date(46299) == "2026-10-04"  # numéro de série Excel
    assert importer.parse_amount("1 234,56 €") == 123456
    assert importer.parse_amount("-12.5") == -1250
    assert importer.parse_amount("(15,00)") == -1500
    assert importer.parse_amount(19.99) == 1999
    assert importer.parse_amount("") is None


def test_csv_preview_commit_and_dedupe(api):
    acc = _account(api)
    res = _preview(api, acc, BANK_CSV)
    assert res.status_code == 200, res.get_json()
    data = res.get_json()
    assert data["headers"][:3] == ["Date opération", "Date valeur", "Libellé"]
    assert data["summary"] == {"total": 5, "ok": 4, "duplicates": 0, "errors": 1}
    ok = [r for r in data["rows"] if r["status"] == "ok"]
    assert [r["amount_cents"] for r in ok] == [285000, -95000, -6745, -6745]
    assert ok[2]["import_hash"] != ok[3]["import_hash"]  # deux achats identiques le même jour
    error = next(r for r in data["rows"] if r["status"] == "error")
    assert error["line"] == 9 and "date" in error["error"].lower()

    res = api.post("/api/import/commit", json={"account_id": acc, "rows": ok})
    assert res.status_code == 201 and res.get_json() == {"inserted": 4, "skipped": 0}

    # Réimporter le même fichier : tout est détecté comme doublon
    again = _preview(api, acc, BANK_CSV).get_json()
    assert again["summary"]["duplicates"] == 4 and again["summary"]["ok"] == 0
    # Et même si on force la validation, rien n'est inséré deux fois
    res = api.post("/api/import/commit", json={"account_id": acc, "rows": [r for r in again["rows"] if r.get("import_hash")]})
    assert res.get_json() == {"inserted": 0, "skipped": 4}


def test_manual_entry_detected_as_duplicate(api):
    acc = _account(api)
    api.post("/api/transactions", json={"account_id": acc, "date": "2026-10-03", "label": "PRLV LOYER",
                                        "amount": "-950"})
    data = _preview(api, acc, BANK_CSV).get_json()
    loyer = next(r for r in data["rows"] if r.get("label") == "PRLV LOYER")
    assert loyer["status"] == "duplicate"


def test_categories_from_file_and_history(app, api):
    acc = _account(api)
    courses = api.get("/api/categories").get_json()["items"]
    courses_id = next(c["id"] for c in courses if c["name"] == "Courses")
    api.post("/api/transactions", json={"account_id": acc, "date": "2026-09-01", "label": "CB CARREFOUR 01/09",
                                        "amount": "-20", "category_id": courses_id})
    csv = "Date;Libellé;Montant;Catégorie\n05/10/2026;CB CARREFOUR 05/10;-30,00;\n06/10/2026;Ciné;-12;Loisirs\n"
    rows = _preview(api, acc, csv.encode()).get_json()["rows"]
    assert rows[0]["category_name"] == "Courses"   # appris de l'historique
    assert rows[1]["category_name"] == "Loisirs"   # lu dans le fichier


def test_xlsx_import(api):
    acc = _account(api)
    wb = Workbook()
    ws = wb.active
    ws.append(["Date", "Description", "Amount"])
    ws.append([datetime(2026, 10, 2), "Coffee", -3.2])
    ws.append([datetime(2026, 10, 3), "Refund", 15])
    buf = io.BytesIO()
    wb.save(buf)
    data = _preview(api, acc, buf.getvalue(), "export.xlsx").get_json()
    assert [(r["date"], r["amount_cents"]) for r in data["rows"]] == [("2026-10-02", -320), ("2026-10-03", 1500)]


def test_mapping_override_and_errors(api):
    acc = _account(api)
    csv = "Quand,Quoi,Combien\n2026-10-01,Truc,-5\n".encode()
    auto = _preview(api, acc, csv).get_json()
    assert auto["headers"] == ["Quand", "Quoi", "Combien"]  # renvoyés pour un choix manuel
    assert set(auto["mapping_errors"]) == {"date", "label", "amount"} and auto["rows"] == []
    res = _preview(api, acc, csv, mapping={"date": 0, "label": 1, "amount": 2})
    assert res.get_json()["rows"][0]["amount_cents"] == -500

    assert _preview(api, acc, b"", "vide.csv").status_code == 400
    assert _preview(api, acc, b"x", "ancien.xls").status_code == 400
    assert _preview(api, acc, b"x", "photo.png").status_code == 400
    assert _preview(api, 999, csv).status_code == 400
    assert api.post("/api/import/commit", json={"account_id": acc, "rows": [{"date": "x"}]}).status_code == 400
