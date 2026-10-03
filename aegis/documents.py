"""Uploaded documents: everything in a file an agent (or its parser) may read, not just the visible text.

Instructions are smuggled into documents where people do not look: PDF metadata and XMP (XML), annotations
and form fields, Word document properties, comments and hidden runs. Each of these is returned as its own
labelled section so the content controls can check it and the report can say where a finding came from.
Active content (PDF JavaScript and auto-actions, launch actions, embedded files, Office macros) is listed
separately: it is not text, it is behaviour, and the `documents` control decides what to do with it.

XML inside DOCX files is read with bounded regular expressions, never with an XML parser, so entity
expansion and external entities cannot be triggered; ZIP members are read with a size cap.
"""

from __future__ import annotations

import html
import io
import os
import re
import shutil
import subprocess
import zipfile
from dataclasses import dataclass, field
from typing import Any

from aegis.models import GatewayError

MAX_BYTES = 10 * 1024 * 1024
MAX_MEMBER = 5 * 1024 * 1024  # largest ZIP member we decompress (zip-bomb guard)
MAX_SECTION = 20_000


@dataclass
class Document:
    name: str
    kind: str  # pdf | docx | text
    body: str
    pages: int | None = None
    sections: list[dict[str, str]] = field(default_factory=list)  # {"source", "text"}
    active: list[dict[str, str]] = field(default_factory=list)  # {"kind", "detail"}
    privacy: list[str] = field(default_factory=list)  # e.g. GPS position in a photo
    notes: list[str] = field(default_factory=list)  # limits of what could be read

    def add(self, source: str, text: Any) -> None:
        text = str(text or "").strip()
        if text:
            self.sections.append({"source": source, "text": text[:MAX_SECTION]})

    def analysis_text(self) -> str:
        """The body followed by every hidden part, each under a label: this is what the controls check."""
        parts = [self.body] + [f"[{s['source']}]\n{s['text']}" for s in self.sections]
        return "\n\n".join(p for p in parts if p.strip())

    def public(self) -> dict[str, Any]:
        return {"name": self.name, "kind": self.kind, "pages": self.pages, "chars": len(self.body),
                "text": self.body, "sections": self.sections, "active": self.active, "privacy": self.privacy,
                "notes": self.notes}


def ocr(image: bytes) -> str | None:
    """Text drawn in a picture or a scanned page, via the tesseract binary (Polish + English by default).
    None when OCR is not installed; the caller then says so instead of pretending the image is empty."""
    exe = shutil.which("tesseract")
    if not exe:
        return None
    from PIL import Image, ImageOps

    try:
        im = Image.open(io.BytesIO(image))
        im = ImageOps.exif_transpose(im).convert("L")
        if im.width < 1200:  # small scans read far better upscaled
            im = im.resize((im.width * 2, im.height * 2))
        buf = io.BytesIO()
        im.save(buf, format="PNG")
        out = subprocess.run([exe, "stdin", "stdout", "-l", os.environ.get("OCR_LANGS", "pol+eng")],
                             input=buf.getvalue(), capture_output=True, timeout=60, check=False)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return ""
    return out.stdout.decode("utf-8", "replace").strip()


def analyze(data: bytes, name: str = "document") -> Document:
    if len(data) > MAX_BYTES:
        raise GatewayError(413, "DOCUMENT_TOO_LARGE", "documents up to 10 MB")
    if data[:5] == b"%PDF-":
        return _pdf(data, name)
    if data[:4] == b"PK\x03\x04":
        return _office(data, name)
    if data[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
        return _legacy_office(data, name)
    if _is_image(data):
        return _image(data, name)
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise GatewayError(415, "UNSUPPORTED_DOCUMENT",
                           "send a PDF, an Office file (docx/xlsx/pptx/doc/xls/ppt), an image or UTF-8 text") from exc
    return Document(name=name, kind="text", body=text)  # HTML/XML/SVG are checked raw: comments and tags included


# ---------------------------------------------------------------- PDF


def _pdf(data: bytes, name: str) -> Document:
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise GatewayError(422, "PDF_ENCRYPTED", "the PDF is password-protected")
        pages = [page.extract_text() or "" for page in reader.pages]
        scanned = 0
        for i, page in enumerate(reader.pages[:30]):
            if len(pages[i].strip()) < 20:  # no text layer: a scan. Read the page images instead.
                texts = [t for img in list(page.images)[:5] if (t := ocr(img.data))]
                if texts:
                    pages[i] = "\n".join(texts)
                    scanned += 1
        doc = Document(name=name, kind="pdf", body="\n".join(pages).strip(), pages=len(pages))
        if scanned:
            doc.notes.append(f"OCR: {scanned} scanned page(s) were read from their images")
        _pdf_metadata(reader, doc)
        _pdf_annotations(reader, doc)
        _pdf_active(reader, data, doc)
    except GatewayError:
        raise
    except (PdfReadError, ValueError, KeyError, TypeError, AttributeError) as exc:
        raise GatewayError(422, "PDF_UNREADABLE", f"cannot read this PDF: {type(exc).__name__}") from exc
    return doc


def _pdf_metadata(reader, doc: Document) -> None:
    for key, value in (reader.metadata or {}).items():
        if key not in ("/CreationDate", "/ModDate", "/Producer", "/Trapped"):  # machine-written, not prose
            doc.add(f"PDF metadata {str(key).lstrip('/')}", value)
    root = reader.trailer["/Root"]
    if "/Metadata" in root:  # XMP packet: free-form XML, a favourite hiding place
        raw = root["/Metadata"].get_object().get_data()
        doc.add("XMP metadata (XML)", raw.decode("utf-8", "replace"))
    for fname, f in (reader.get_fields() or {}).items():
        for k in ("/V", "/TU", "/TM"):
            if f.get(k):
                doc.add(f"form field {fname}", f.get(k))


def _pdf_annotations(reader, doc: Document) -> None:
    for i, page in enumerate(reader.pages, 1):
        for ref in page.get("/Annots") or []:
            a = ref.get_object()
            for k in ("/Contents", "/T", "/Subj", "/RC"):
                if a.get(k):
                    doc.add(f"annotation on page {i} ({k.lstrip('/')})", a.get(k))
            action = a.get("/A")
            if action is not None:
                action = action.get_object()
                if action.get("/S") == "/URI":
                    doc.add(f"link on page {i}", action.get("/URI"))
                _pdf_action(action, f"annotation on page {i}", doc)


def _pdf_action(action, where: str, doc: Document) -> None:
    kind = action.get("/S")
    if kind == "/JavaScript":
        js = action.get("/JS")
        js = js.get_object().get_data().decode("latin-1", "replace") if hasattr(js, "get_object") and hasattr(js.get_object(), "get_data") else str(js)
        doc.active.append({"kind": "javascript", "detail": f"{where}: {js[:200]}"})
        doc.add(f"JavaScript ({where})", js)
    elif kind == "/Launch":
        doc.active.append({"kind": "launch", "detail": f"{where}: starts an external program or file"})
    elif kind in ("/SubmitForm", "/ImportData"):
        doc.active.append({"kind": "submit", "detail": f"{where}: sends or loads data ({str(kind).lstrip('/')})"})


def _pdf_active(reader, data: bytes, doc: Document) -> None:
    root = reader.trailer["/Root"]
    oa = root.get("/OpenAction")
    if oa is not None and hasattr(oa.get_object(), "get"):
        _pdf_action(oa.get_object(), "runs when the document opens", doc)
    aa = root.get("/AA")
    if aa is not None:
        for trigger, act in aa.get_object().items():
            _pdf_action(act.get_object(), f"automatic action {trigger}", doc)
    names = root.get("/Names")
    if names is not None:
        names = names.get_object()
        if "/JavaScript" in names:
            tree = names["/JavaScript"].get_object().get("/Names", [])
            for j in range(1, len(tree), 2):
                _pdf_action(tree[j].get_object(), "document-level script", doc)
    for fname in (reader.attachments or {}):
        doc.active.append({"kind": "embedded_file", "detail": f"embedded file: {fname}"})
        doc.add("embedded file name", fname)
    # scripts can also sit in compressed object streams the walk above does not reach
    if not any(a["kind"] == "javascript" for a in doc.active) and re.search(rb"/(JavaScript|JS)\b", data):
        doc.active.append({"kind": "javascript", "detail": "JavaScript marker found in the file"})


# ---------------------------------------------------------------- DOCX / Office Open XML

_TAG = re.compile(r"<[^>]{0,2000}>")


def _xml_text(xml: str) -> str:
    return html.unescape(_TAG.sub(" ", xml)).strip()


def _office(data: bytes, name: str) -> Document:
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
        names = set(z.namelist())
    except zipfile.BadZipFile as exc:
        raise GatewayError(422, "DOCUMENT_UNREADABLE", "not a valid DOCX/ZIP file") from exc

    def read(member: str) -> str:
        info = z.getinfo(member)
        if info.file_size > MAX_MEMBER:
            raise GatewayError(413, "DOCUMENT_TOO_LARGE", f"{member} is too large once unpacked")
        return z.read(member).decode("utf-8", "replace")

    if "word/document.xml" in names:
        doc = _docx(read, names, name)
    elif "xl/workbook.xml" in names:
        doc = _xlsx(read, names, name)
    elif "ppt/presentation.xml" in names:
        doc = _pptx(read, names, name)
    else:
        raise GatewayError(415, "UNSUPPORTED_DOCUMENT", "this ZIP is not a Word, Excel or PowerPoint file")
    _ooxml_common(read, names, doc)
    return doc


def _docx(read, names: set[str], name: str) -> Document:
    xml = read("word/document.xml")
    runs = re.findall(r"<w:r[ >].*?</w:r>", xml, re.S)
    hidden_runs = [r for r in runs if re.search(r"<w:vanish(?: [^>]*)?/>", r)]
    visible_xml = xml
    for r in hidden_runs:  # the body is what a person sees; hidden runs are reported as their own section
        visible_xml = visible_xml.replace(r, "")
    paragraphs = re.findall(r"<w:p[ >].*?</w:p>", visible_xml, re.S)
    body = "\n".join(html.unescape("".join(re.findall(r"<w:t(?: [^>]*)?>(.*?)</w:t>", p, re.S))) for p in paragraphs)
    doc = Document(name=name, kind="docx", body=body.strip())

    hidden = [html.unescape("".join(re.findall(r"<w:t(?: [^>]*)?>(.*?)</w:t>", r, re.S))) for r in hidden_runs]
    doc.add("hidden text (w:vanish)", " ".join(h for h in hidden if h))

    for member in ("word/footnotes.xml", "word/endnotes.xml"):
        if member in names:
            doc.add(member.split("/")[1].replace(".xml", ""), _xml_text(read(member)))
    if "word/comments.xml" in names:
        for author, body_xml in re.findall(r'<w:comment\b[^>]*w:author="([^"]*)"[^>]*>(.*?)</w:comment>', read("word/comments.xml"), re.S):
            doc.add(f"comment by {html.unescape(author)}", _xml_text(body_xml))
    return doc


def _ooxml_common(read, names: set[str], doc: Document) -> None:
    """Parts every Office Open XML file can carry: properties, external relationships, macros, embeddings."""
    for member, label in (("docProps/core.xml", "document properties"), ("docProps/app.xml", "application properties")):
        if member in names:
            for tag, value in re.findall(r"<(\w+:\w+|\w+)[^>]*>([^<]{1,5000})</\1>", read(member)):
                if tag.startswith("vt:"):  # typed values inside property vectors (slide titles, counts)
                    continue
                if tag.split(":")[-1] not in ("created", "modified", "revision", "TotalTime", "Pages", "Words",
                                              "Characters", "Lines", "Paragraphs", "DocSecurity", "AppVersion",
                                              "CharactersWithSpaces", "ScaleCrop", "LinksUpToDate", "SharedDoc",
                                              "HyperlinksChanged", "Template", "Application", "PresentationFormat",
                                              "Slides", "Notes", "HiddenSlides", "MMClips"):
                    doc.add(f"{label}: {tag.split(':')[-1]}", html.unescape(value))
    if "docProps/custom.xml" in names:
        for pname, value in re.findall(r'<property[^>]*name="([^"]{1,200})"[^>]*>(.*?)</property>', read("docProps/custom.xml"), re.S):
            doc.add(f"custom property {pname}", _xml_text(value))
    for rels in sorted(n for n in names if n.endswith(".rels")):
        for rel in re.findall(r"<Relationship\b[^>]{0,3000}>", read(rels)):
            attr = dict(re.findall(r'(\w+)="([^"]*)"', rel))
            if attr.get("TargetMode") != "External":
                continue
            target, rtype = html.unescape(attr.get("Target", "")), attr.get("Type", "").rsplit("/", 1)[-1]
            doc.add(f"external {rtype or 'link'}", target)
            if rtype in ("attachedTemplate", "oleObject", "frame", "subDocument") or re.match(
                    r"(?i)(file:|\\\\|https?://\S+\.(exe|dll|ps1|bat|cmd|hta|js|vbs|dotm|docm)$)", target):
                doc.active.append({"kind": "remote_content", "detail": f"loads {rtype or 'content'} from outside when opened: {target[:200]}"})
    if any(n.endswith("vbaProject.bin") for n in names):
        doc.active.append({"kind": "macro", "detail": "contains VBA macros (vbaProject.bin)"})
    for n in sorted(names):
        if re.match(r"(word|xl|ppt)/embeddings/", n):
            doc.active.append({"kind": "embedded_file", "detail": f"embedded object: {n.split('/')[-1]}"})


def _xlsx(read, names: set[str], name: str) -> Document:
    shared = []
    if "xl/sharedStrings.xml" in names:
        shared = ["".join(html.unescape(t) for t in re.findall(r"<t(?: [^>]*)?>(.*?)</t>", si, re.S))
                  for si in re.findall(r"<si>(.*?)</si>", read("xl/sharedStrings.xml"), re.S)]
    wb = read("xl/workbook.xml")
    rels = read("xl/_rels/workbook.xml.rels") if "xl/_rels/workbook.xml.rels" in names else ""
    targets = {rid: tgt for rid, tgt in re.findall(r'<Relationship\b[^>]*Id="([^"]+)"[^>]*Target="([^"]+)"', rels)}
    targets.update({rid: tgt for tgt, rid in re.findall(r'<Relationship\b[^>]*Target="([^"]+)"[^>]*Id="([^"]+)"', rels)})
    visible, formulas = [], []
    doc = Document(name=name, kind="xlsx", body="")
    for tag in re.findall(r"<sheet\b[^>]*/>", wb):
        attr = dict(re.findall(r'([\w:]+)="([^"]*)"', tag))
        member = "xl/" + targets.get(attr.get("r:id", ""), "").lstrip("/").removeprefix("xl/")
        if member not in names:
            continue
        xml = read(member)
        cells = []
        for c in re.findall(r"<c\b[^>]*>.*?</c>", xml, re.S):
            if 't="s"' in c:
                v = re.search(r"<v>(\d+)</v>", c)
                if v and int(v.group(1)) < len(shared):
                    cells.append(shared[int(v.group(1))])
            elif 't="inlineStr"' in c:
                cells.append(html.unescape("".join(re.findall(r"<t(?: [^>]*)?>(.*?)</t>", c, re.S))))
            else:
                v = re.search(r"<v>(.*?)</v>", c, re.S)
                if v:
                    cells.append(html.unescape(v.group(1)))
            f = re.search(r"<f(?: [^>]*)?>(.*?)</f>", c, re.S)
            if f:
                formulas.append(html.unescape(f.group(1)))
        text = "\n".join(x for x in cells if x.strip())
        sheet = html.unescape(attr.get("name", member))
        if attr.get("state") in ("hidden", "veryHidden"):
            doc.add(f"hidden sheet {sheet}", text)  # not visible in Excel, still read by any parser
        else:
            visible.append(text)
    doc.body = "\n\n".join(v for v in visible if v)
    for dn, val in re.findall(r'<definedName\b[^>]*name="([^"]*)"[^>]*>(.*?)</definedName>', wb, re.S):
        doc.add(f"defined name {html.unescape(dn)}", html.unescape(val))
    if formulas:
        doc.add("formulas", "\n".join(formulas))
        for f in formulas:  # formulas that call out or start programs: DDE, WEBSERVICE, external calls
            if re.search(r"(?i)\b(cmd|powershell|mshta|msexcel)\s*\||\bDDE(AUTO)?\b|\bWEBSERVICE\s*\(|\bCALL\s*\(|\bREGISTER(\.ID)?\s*\(|\bEXEC\s*\(", f):
                doc.active.append({"kind": "dde_formula", "detail": f"formula that calls out or runs a program: ={f[:160]}"})
    for c in sorted(n for n in names if re.match(r"xl/comments\d*\.xml$", n)):
        for text in re.findall(r"<comment\b[^>]*>(.*?)</comment>", read(c), re.S):
            doc.add("cell comment", _xml_text(text))
    for c in sorted(n for n in names if n.startswith("xl/threadedComments/")):
        doc.add("threaded comment", _xml_text(read(c)))
    if any(n.startswith("xl/externalLinks/") for n in names):
        doc.add("external workbook links", ", ".join(n for n in sorted(names) if n.startswith("xl/externalLinks/")))
    return doc


def _pptx(read, names: set[str], name: str) -> Document:
    order = lambda n: int(re.search(r"(\d+)\.xml$", n).group(1))  # noqa: E731
    slides = sorted((n for n in names if re.match(r"ppt/slides/slide\d+\.xml$", n)), key=order)
    body = []
    hidden_slides = [sl for sl in slides if re.search(r'<p:sld\b[^>]*show="0"', read(sl))]
    for sl in slides:
        if sl not in hidden_slides:  # a hidden slide is not on screen during the show: reported on its own
            body.append("\n".join(html.unescape(x) for x in re.findall(r"<a:t>(.*?)</a:t>", read(sl), re.S)))
    doc = Document(name=name, kind="pptx", body="\n\n".join(b for b in body if b.strip()), pages=len(slides))
    for sl in hidden_slides:
        doc.add(f"hidden slide {order(sl)}", "\n".join(html.unescape(x) for x in re.findall(r"<a:t>(.*?)</a:t>", read(sl), re.S)))
    for nt in sorted((n for n in names if re.match(r"ppt/notesSlides/notesSlide\d+\.xml$", n)), key=order):
        doc.add(f"speaker notes {order(nt)}", "\n".join(html.unescape(x) for x in re.findall(r"<a:t>(.*?)</a:t>", read(nt), re.S)))
    for c in sorted(n for n in names if n.startswith("ppt/comments/")):
        doc.add("slide comment", _xml_text(read(c)))
    return doc


# ---------------------------------------------------------------- legacy Office (OLE2: .doc, .xls, .ppt)

_OLE_META = ("title", "subject", "author", "keywords", "comments", "last_saved_by", "category", "company",
             "manager", "template")


def _strings(raw: bytes, minimum: int = 5) -> list[str]:
    """Readable runs in a binary stream: UTF-16LE (Word, Excel text) and single-byte cp1250."""
    out = [m.decode("utf-16le", "ignore")  # Basic Latin and Latin-1 (high byte 0), Latin Extended-A (high byte 1)
           for m in re.findall(rb"(?:[\x20-\x7e\xa0-\xff]\x00|[\x01-\xff]\x01){%d,}" % minimum, raw)]
    out += [m.decode("cp1250", "ignore") for m in re.findall(rb"[\x20-\x7e\x8a-\xff]{%d,}" % (minimum + 3), raw)]
    seen, uniq = set(), []
    for s in out:
        s = s.strip()
        letters = sum(ch.isalpha() for ch in s)
        if letters < 3 or letters < 0.4 * len(s):  # binary noise that happens to be printable
            continue
        if s and s not in seen:
            seen.add(s)
            uniq.append(s)
    return uniq


def _legacy_office(data: bytes, name: str) -> Document:
    import olefile

    try:
        ole = olefile.OleFileIO(io.BytesIO(data))
    except OSError as exc:
        raise GatewayError(422, "DOCUMENT_UNREADABLE", "not a valid .doc/.xls/.ppt file") from exc
    streams = ["/".join(s) for s in ole.listdir(streams=True, storages=True)]
    main = next((s for s in ("WordDocument", "Workbook", "Book", "PowerPoint Document") if ole.exists(s)), None)
    kind = {"WordDocument": "doc", "Workbook": "xls", "Book": "xls", "PowerPoint Document": "ppt"}.get(main, "ole")
    body = ""
    if main:
        raw = ole.openstream(main).read(MAX_MEMBER)
        if kind == "doc" and ole.exists("1Table"):
            raw += ole.openstream("1Table").read(MAX_MEMBER)
        body = "\n".join(_strings(raw))
    doc = Document(name=name, kind=kind, body=body[:200_000])
    doc.notes.append("legacy binary format: text is recovered from the file's streams, layout is not kept")
    meta = ole.get_metadata()
    for attr in _OLE_META:
        value = getattr(meta, attr, None)
        if isinstance(value, bytes):
            value = value.decode("cp1250", "replace")
        doc.add(f"document properties: {attr}", value)
    if any(s.split("/")[0] in ("Macros", "_VBA_PROJECT_CUR", "VBA") or s.endswith("/VBA") for s in streams):
        doc.active.append({"kind": "macro", "detail": "contains VBA macros"})
    for s in streams:
        if s.split("/")[-1] in ("\x01Ole10Native", "Package") or s.startswith("ObjectPool"):
            doc.active.append({"kind": "embedded_file", "detail": f"embedded object stream: {s.replace(chr(1), '')}"})
            break
    ole.close()
    return doc


# ---------------------------------------------------------------- images: EXIF, XMP, PNG text chunks, GPS

def _is_image(data: bytes) -> bool:
    return (data[:3] == b"\xff\xd8\xff" or data[:8] == b"\x89PNG\r\n\x1a\n" or data[:6] in (b"GIF87a", b"GIF89a")
            or data[:4] in (b"II*\x00", b"MM\x00*") or (data[:4] == b"RIFF" and data[8:12] == b"WEBP"))


_EXIF_TEXT = {0x010E: "ImageDescription", 0x013B: "Artist", 0x8298: "Copyright", 0x010F: "Make", 0x0110: "Model",
              0x0131: "Software", 0x9286: "UserComment", 0x9C9B: "XPTitle", 0x9C9C: "XPComment",
              0x9C9D: "XPAuthor", 0x9C9E: "XPKeywords", 0x9C9F: "XPSubject", 0xA430: "CameraOwnerName",
              0xA420: "ImageUniqueID"}


def _exif_value(tag: int, value: Any) -> str:
    if isinstance(value, bytes):
        if tag in (0x9C9B, 0x9C9C, 0x9C9D, 0x9C9E, 0x9C9F):  # Windows XP* tags are UTF-16LE
            return value.decode("utf-16le", "ignore").rstrip("\x00")
        if tag == 0x9286 and value[:8] in (b"ASCII\x00\x00\x00", b"UNICODE\x00", b"\x00" * 8):
            return value[8:].decode("utf-16" if value[:7] == b"UNICODE" else "latin-1", "ignore").rstrip("\x00")
        return value.decode("utf-8", "ignore").rstrip("\x00")
    if isinstance(value, tuple) and all(isinstance(v, int) for v in value):  # XP tags as int tuples
        return bytes(value).decode("utf-16le", "ignore").rstrip("\x00")
    return str(value)


def _image(data: bytes, name: str) -> Document:
    from PIL import Image, UnidentifiedImageError

    try:
        im = Image.open(io.BytesIO(data))
    except (UnidentifiedImageError, OSError) as exc:
        raise GatewayError(422, "DOCUMENT_UNREADABLE", "cannot read this image") from exc
    text = ocr(data)
    doc = Document(name=name, kind="image", body=text or "")
    doc.notes.append("OCR: text in the picture was read" if text is not None
                     else "OCR is not installed: only the metadata of this image was read")
    exif = im.getexif()
    tags = dict(exif)
    try:
        tags.update(exif.get_ifd(0x8769))  # Exif sub-IFD: UserComment, CameraOwnerName…
    except (KeyError, AttributeError):
        pass
    for tag, label in _EXIF_TEXT.items():
        if tag in tags and tags[tag] not in (None, b"", ""):
            doc.add(f"EXIF {label}", _exif_value(tag, tags[tag]))
    try:
        gps = exif.get_ifd(0x8825)
    except (KeyError, AttributeError):
        gps = {}
    if gps.get(2) and gps.get(4):
        def deg(v, ref):
            d = float(v[0]) + float(v[1]) / 60 + float(v[2]) / 3600
            return -d if ref in ("S", "W") else d
        lat, lon = deg(gps[2], gps.get(1, "N")), deg(gps[4], gps.get(3, "E"))
        doc.privacy.append(f"GPS position {lat:.5f}, {lon:.5f}")
        doc.add("EXIF GPS position", f"{lat:.5f}, {lon:.5f}")
    for key, value in (im.info or {}).items():  # PNG tEXt/iTXt/zTXt chunks, JPEG/GIF comments, XMP
        if key in ("exif", "icc_profile", "dpi", "gamma", "transparency", "duration", "loop", "background",
                   "progressive", "progression", "jfif", "jfif_version", "jfif_unit", "jfif_density", "adobe",
                   "adobe_transform", "aspect", "interlace", "srgb", "chromaticity", "compression"):
            continue
        if isinstance(value, bytes):
            value = value.decode("utf-8", "ignore")
        if isinstance(value, str) and value.strip():
            doc.add("XMP metadata (XML)" if key in ("xmp", "XML:com.adobe.xmp") else f"image text field {key}", value)
    if not any(x["source"].startswith("XMP") for x in doc.sections):
        m = re.search(rb"<x:xmpmeta.{0,200000}?</x:xmpmeta>", data, re.S)
        if m:
            doc.add("XMP metadata (XML)", m.group(0).decode("utf-8", "replace"))
    return doc
