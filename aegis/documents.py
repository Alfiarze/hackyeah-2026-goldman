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
import re
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
                "text": self.body, "sections": self.sections, "active": self.active}


def analyze(data: bytes, name: str = "document") -> Document:
    if len(data) > MAX_BYTES:
        raise GatewayError(413, "DOCUMENT_TOO_LARGE", "documents up to 10 MB")
    if data[:5] == b"%PDF-":
        return _pdf(data, name)
    if data[:4] == b"PK\x03\x04":
        return _office(data, name)
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise GatewayError(415, "UNSUPPORTED_DOCUMENT", "send a PDF, a DOCX or UTF-8 text") from exc
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
        doc = Document(name=name, kind="pdf", body="\n".join(pages).strip(), pages=len(pages))
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

    if "word/document.xml" not in names:
        raise GatewayError(415, "UNSUPPORTED_DOCUMENT", "only Word (.docx) documents are supported")
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

    for member, label in (("docProps/core.xml", "document properties"), ("docProps/app.xml", "application properties")):
        if member in names:
            for tag, value in re.findall(r"<(\w+:\w+)[^>]*>([^<]{1,5000})</\1>", read(member)):
                if tag.split(":")[1] not in ("created", "modified", "revision", "TotalTime", "Pages", "Words",
                                              "Characters", "Lines", "Paragraphs", "DocSecurity", "AppVersion",
                                              "CharactersWithSpaces", "ScaleCrop", "LinksUpToDate", "SharedDoc",
                                              "HyperlinksChanged", "Template"):
                    doc.add(f"{label}: {tag.split(':')[1]}", html.unescape(value))
    if "docProps/custom.xml" in names:
        for pname, value in re.findall(r'<property[^>]*name="([^"]{1,200})"[^>]*>(.*?)</property>', read("docProps/custom.xml"), re.S):
            doc.add(f"custom property {pname}", _xml_text(value))
    if "word/comments.xml" in names:
        for author, body_xml in re.findall(r'<w:comment\b[^>]*w:author="([^"]*)"[^>]*>(.*?)</w:comment>', read("word/comments.xml"), re.S):
            doc.add(f"comment by {html.unescape(author)}", _xml_text(body_xml))
    for member in ("word/footnotes.xml", "word/endnotes.xml"):
        if member in names:
            doc.add(member.split("/")[1].replace(".xml", ""), _xml_text(read(member)))
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
        if n.startswith("word/embeddings/"):
            doc.active.append({"kind": "embedded_file", "detail": f"embedded object: {n.split('/')[-1]}"})
    return doc
