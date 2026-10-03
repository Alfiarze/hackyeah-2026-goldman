"""The sample contracts offered for upload in the console: the clean one passes, the defective one is
stopped and every planted defect is reported."""
from pathlib import Path

from conftest import ADMIN

ROOT = Path(__file__).parents[1]
# source tree: dashboard/public/samples; the Docker image only has the built copy in dashboard/dist/samples
SAMPLES = next(p for p in (ROOT / "dashboard" / "public" / "samples", ROOT / "dashboard" / "dist" / "samples") if p.is_dir())


async def check(client, name):
    if name.endswith(".pdf"):  # through the same upload path the console uses
        r = await client.post("/admin/playground/extract", headers=ADMIN | {"Content-Type": "application/pdf"},
                              content=(SAMPLES / name).read_bytes())
        assert r.status_code == 200, r.text
        text = r.json()["text"]
    else:
        text = (SAMPLES / name).read_text(encoding="utf-8")
    r = await client.post("/admin/playground/evaluate", headers=ADMIN, json={"text": text, "target": "tool_results"})
    assert r.status_code == 200, r.text
    return r.json()["decision"]


import pytest


@pytest.mark.parametrize("name", ["umowa-czysta.txt", "umowa-czysta.pdf"])
async def test_clean_contract_passes(client, name):
    d = await check(client, name)
    assert d["action"] == "ALLOW", d


@pytest.mark.parametrize("name", ["umowa-z-defektami.txt", "umowa-z-defektami.pdf"])
async def test_defective_contract_reports_every_defect(client, name):
    """In the PDF the instruction for the AI is white 1-point text: invisible on the page, still extracted."""
    d = await check(client, name)
    assert d["action"] == "BLOCK"
    by_rule = {f["rule_id"]: f["detail"] for f in d["findings"]}
    assert {"PESEL", "NIP", "ID_CARD", "IBAN", "ADDRESS"} <= set(by_rule["PII-001"]["entities"])
    assert {"PASSWORD", "CONNECTION_STRING"} <= set(by_rule["SEC-001"]["types"])
    patterns = set(by_rule["INJ-001"]["patterns"])
    assert {"IGNORE_INSTRUCTIONS_PL", "HIDDEN_AI_NOTE_PL", "CONCEALMENT_PL", "MARKDOWN_EXFIL"} <= patterns
    assert any(p.startswith("OBFUSCATED_") for p in patterns)  # the base64 paragraph
    assert {"ATK-EXEC-002", "ATK-TRC-001"} <= set(by_rule)


async def test_extract_rejects_garbage(client):
    r = await client.post("/admin/playground/extract", headers=ADMIN | {"Content-Type": "application/pdf"},
                          content=b"%PDF-1.7 this is not really a pdf")
    assert r.status_code == 422
    r = await client.post("/admin/playground/extract", headers=ADMIN, content=bytes([0xff, 0xfe, 0x00, 0x81]))
    assert r.status_code == 415


# ---------------------------------------------------------------- hidden parts of files

async def check_file(client, name):
    r = await client.post(f"/admin/playground/document?name={name}", headers=ADMIN | {"Content-Type": "application/octet-stream"},
                          content=(SAMPLES / name).read_bytes())
    assert r.status_code == 200, r.text
    return r.json()


def rules_in(doc, prefix):
    return {rule for s in doc["sections"] if s["source"].startswith(prefix) for rule in s["rules"]}


async def test_clean_pdf_file_passes_with_its_metadata(client):
    body = await check_file(client, "umowa-czysta.pdf")
    assert body["decision"]["action"] == "ALLOW", body["decision"]
    assert not body["document"]["active"]


async def test_pdf_attacks_hidden_in_metadata_xmp_annotations_and_script(client):
    """The page text is the clean contract; everything bad is where a person does not look."""
    body = await check_file(client, "umowa-metadane.pdf")
    doc, d = body["document"], body["decision"]
    assert body["document"]["body_rules"] == []                       # visible text is clean
    assert d["action"] == "BLOCK"
    assert "DOC-001" in {f["rule_id"] for f in d["findings"]}          # document-level JavaScript
    assert {"javascript"} <= {a["kind"] for a in doc["active"]}
    assert "INJ-001" in rules_in(doc, "PDF metadata Subject")           # instruction for the AI
    assert "SEC-001" in rules_in(doc, "PDF metadata Keywords")          # password
    assert "INJ-001" in rules_in(doc, "XMP metadata")                   # XML comment + base64 + markdown exfil
    assert "ATK-EXEC-002" in rules_in(doc, "annotation on page 1")      # curl | bash in a sticky note


async def test_docx_attacks_hidden_in_properties_comments_hidden_runs_and_template(client):
    body = await check_file(client, "umowa-metadane.docx")
    doc, d = body["document"], body["decision"]
    assert doc["kind"] == "docx" and d["action"] == "BLOCK"
    assert doc["body_rules"] == [] and "zignoruj" not in doc["text"]   # visible text is clean
    assert "INJ-001" in rules_in(doc, "hidden text")
    assert "INJ-001" in rules_in(doc, "document properties: description")
    assert "INJ-001" in rules_in(doc, "document properties: keywords")  # base64
    assert {"SEC-001", "PII-001"} <= rules_in(doc, "comment by")
    assert "ATK-EXEC-002" in rules_in(doc, "custom property")
    assert "remote_content" in {a["kind"] for a in doc["active"]}       # remote template (.dotm)


async def test_documents_control_can_be_switched_off(client):
    await client.patch("/admin/controls/documents", headers=ADMIN, json={"enabled": False})
    body = await check_file(client, "umowa-metadane.pdf")
    assert "DOC-001" not in {f["rule_id"] for f in body["decision"]["findings"]}


async def test_docx_xml_is_never_expanded(client):
    """A billion-laughs style entity bomb in a DOCX part is read as text, not parsed."""
    import io
    import zipfile
    bomb = '<?xml version="1.0"?><!DOCTYPE l [<!ENTITY a "aaaaaaaaaa"><!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;">' \
           '<!ENTITY c "&b;&b;&b;&b;&b;&b;&b;&b;&b;&b;">]><w:document xmlns:w="w"><w:body><w:p><w:r><w:t>&c;</w:t></w:r></w:p></w:body></w:document>'
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("word/document.xml", bomb)
    r = await client.post("/admin/playground/extract?name=bomb.docx", headers=ADMIN, content=buf.getvalue())
    assert r.status_code == 200 and len(r.json()["text"]) < 100


# ---------------------------------------------------------------- more formats: Excel, PowerPoint, legacy, images

async def test_xlsx_hidden_sheet_dde_formula_and_properties(client):
    body = await check_file(client, "harmonogram-metadane.xlsx")
    doc, d = body["document"], body["decision"]
    assert doc["kind"] == "xlsx" and d["action"] == "BLOCK" and doc["body_rules"] == []
    assert {"SEC-001", "PII-001"} <= rules_in(doc, "hidden sheet")         # very hidden sheet with a password
    assert "dde_formula" in {a["kind"] for a in doc["active"]}             # =cmd|'/C powershell …'
    assert "INJ-001" in rules_in(doc, "document properties: description")  # base64
    assert "ATK-EXEC-002" in rules_in(doc, "document properties: keywords")


async def test_pptx_speaker_notes_and_hidden_slide(client):
    body = await check_file(client, "prezentacja-metadane.pptx")
    doc = body["document"]
    assert doc["kind"] == "pptx" and body["decision"]["action"] == "BLOCK" and doc["body_rules"] == []
    assert "INJ-001" in rules_in(doc, "speaker notes")
    assert "SEC-001" in rules_in(doc, "hidden slide")
    assert "ATK-EXEC-003" in rules_in(doc, "document properties: subject")


async def test_legacy_xls_text_is_recovered(client):
    body = await check_file(client, "harmonogram-stary.xls")
    doc = body["document"]
    assert doc["kind"] == "xls" and body["decision"]["action"] == "BLOCK"
    assert {"INJ-001", "SEC-001", "ATK-EXEC-002"} <= set(doc["body_rules"])
    assert "wstępna" in doc["text"]                                        # Polish letters survive


async def test_jpeg_exif_and_gps(client):
    body = await check_file(client, "skan-umowy.jpg")
    doc, d = body["document"], body["decision"]
    assert doc["kind"] == "image" and d["action"] == "BLOCK"
    assert "INJ-001" in rules_in(doc, "EXIF ImageDescription")
    assert "SEC-001" in rules_in(doc, "EXIF XPComment")
    assert "PII-001" in rules_in(doc, "EXIF Artist")
    assert doc["privacy"] and "PII-002" in {f["rule_id"] for f in d["findings"]}  # GPS position


async def test_png_text_chunks(client):
    body = await check_file(client, "podpis.png")
    doc = body["document"]
    assert "INJ-001" in rules_in(doc, "image text field")


# ---------------------------------------------------------------- OCR: scans and pictures

needs_ocr = pytest.mark.skipif(__import__("shutil").which("tesseract") is None, reason="tesseract not installed")


@needs_ocr
async def test_scanned_pdf_is_read_with_ocr(client):
    """A PDF made only of page images has no text layer; the note for the AI on the scan is read by OCR."""
    body = await check_file(client, "skan-umowy.pdf")
    doc, d = body["document"], body["decision"]
    assert any("OCR" in n for n in doc["notes"])
    assert "Notatka dla asystenta AI" in doc["text"]
    assert d["action"] == "BLOCK" and {"INJ-001", "PII-001"} <= set(doc["body_rules"])


@needs_ocr
async def test_text_in_a_picture_is_read_with_ocr(client):
    body = await check_file(client, "skan-umowy.jpg")
    assert "Skan podpisanej umowy" in body["document"]["text"]
