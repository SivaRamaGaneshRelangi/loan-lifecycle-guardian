"""Document locker: validated uploads, simulated automated verification, officer review.

Real deployments would call an OCR/DigiLocker/KYC provider. Here we do what is honestly possible
without one: validate file type by magic bytes, size, extract text from uncompressed PDFs, and compare
name / PAN / income against the customer's profile. Anything we cannot read goes to manual review.
"""
import hashlib
import json
import os
import re
import uuid
from pathlib import Path

from ..config import settings
from ..models import Document
from .errors import BusinessError
from .notify import audit

DOC_LABELS = {
    "ID_PROOF": "Identity proof (PAN / Aadhaar)",
    "ADDRESS_PROOF": "Address proof",
    "INCOME_PROOF": "Income proof (salary slip / ITR)",
    "PROPERTY_PAPERS": "Property papers",
    "VEHICLE_QUOTATION": "Vehicle quotation",
    "ADMISSION_LETTER": "Admission letter",
    "GOLD_VALUATION": "Gold valuation certificate",
}
ALLOWED_EXT = {".pdf", ".png", ".jpg", ".jpeg"}
MIN_BYTES = 200


# ---------- helpers ----------
def _detect(content: bytes):
    if content.startswith(b"%PDF"):
        return ".pdf", "application/pdf"
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png", "image/png"
    if content.startswith(b"\xff\xd8\xff"):
        return ".jpg", "image/jpeg"
    return None


def _pdf_text(content: bytes) -> str:
    """Extract text drawn with simple (Tj) operators. Compressed/scanned PDFs yield '' -> manual review."""
    out = []
    for m in re.finditer(rb"\(((?:\\.|[^()\\])*)\)\s*Tj", content):
        t = m.group(1).decode("latin-1")
        t = re.sub(r"\\([()\\])", r"\1", t)
        out.append(t)
    return "\n".join(out)


def simple_pdf(lines):
    def esc(s):
        s = s.encode("ascii", "replace").decode()
        return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    content = "BT /F1 12 Tf 50 780 Td 18 TL\n" + "\n".join(f"({esc(l)}) Tj T*" for l in lines) + "\nET"
    objs = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R "
        "/Resources << /Font << /F1 5 0 R >> >> >>",
        f"<< /Length {len(content)} >>\nstream\n{content}\nendstream",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out, offs = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += f"{i} 0 obj\n{o}\nendobj\n".encode("latin-1")
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    for o in offs:
        out += f"{o:010d} 00000 n \n".encode()
    out += (f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n").encode()
    return out


def _check(name, ok, detail):
    return {"name": name, "passed": bool(ok), "detail": detail}


# ---------- verification ----------
def auto_verify(doc_type, user, profile, content, ext, other_types_with_same_hash=()):
    """Returns (status, checks). VERIFIED only if every automated check passes."""
    checks = [_check("File type", True, f"Valid {ext[1:].upper()} file"),
              _check("Readable size", len(content) >= MIN_BYTES, f"{len(content):,} bytes")]
    if len(content) < MIN_BYTES:
        return "REJECTED", checks
    if other_types_with_same_hash:
        checks.append(_check("Unique file", False,
                             f"Same file already uploaded as {', '.join(sorted(other_types_with_same_hash))}"))
    if ext != ".pdf":
        checks.append(_check("Text extraction", False, "Image uploaded - cannot be read automatically; "
                                                      "queued for officer review"))
        return "UPLOADED", checks
    text = _pdf_text(content)
    if not text.strip():
        checks.append(_check("Text extraction", False, "No machine-readable text (scanned/compressed PDF); "
                                                      "queued for officer review"))
        return "UPLOADED", checks
    low = text.lower()
    checks.append(_check("Text extraction", True, f"{len(text.split())} words read"))
    m = re.search(r"(?i:document type):\s*([A-Z_]+)", text)
    if m and m.group(1) != doc_type:
        checks.append(_check("Document type", False, f"File looks like {m.group(1)}, uploaded as {doc_type}"))
    else:
        checks.append(_check("Document type", True, "Matches the selected type"))
    name_ok = all(t.lower() in low for t in user.full_name.split())
    checks.append(_check("Name matches profile", name_ok,
                         f"'{user.full_name}' found" if name_ok else f"'{user.full_name}' not found on document"))
    if doc_type == "ID_PROOF":
        pan_ok = profile.pan.lower() in low
        checks.append(_check("PAN matches profile", pan_ok,
                             "PAN found" if pan_ok else "Registered PAN not found on document"))
    if doc_type == "INCOME_PROOF":
        mi = re.search(r"monthly income[^0-9]*([0-9][0-9,]*)", low)
        if mi:
            val = float(mi.group(1).replace(",", ""))
            ok = abs(val - profile.monthly_income) <= 0.15 * profile.monthly_income
            checks.append(_check("Income vs declared", ok,
                                 f"Document shows {val:,.0f}; declared {profile.monthly_income:,.0f}"))
        else:
            checks.append(_check("Income vs declared", False, "No monthly income figure found"))
    return ("VERIFIED" if all(c["passed"] for c in checks) else "UPLOADED"), checks


# ---------- storage ----------
def _root() -> Path:
    p = Path(settings.UPLOAD_DIR).resolve()
    p.mkdir(parents=True, exist_ok=True)
    return p


def file_path(doc: Document) -> Path:
    root = _root()
    p = (root / str(doc.user_id) / doc.stored_name).resolve()
    if root not in p.parents:
        raise BusinessError("Invalid file path")
    return p


def store(db, user, doc_type, filename, content, source="UPLOAD", actor_id=None):
    doc_type = doc_type.upper()
    if doc_type not in DOC_LABELS:
        raise BusinessError("Unknown document type")
    if not user.profile:
        raise BusinessError("Customer profile missing")
    if len(content) > settings.MAX_UPLOAD_MB * 1024 * 1024:
        raise BusinessError(f"File too large (max {settings.MAX_UPLOAD_MB} MB)")
    clean = re.sub(r"[^A-Za-z0-9._ -]", "_", os.path.basename(filename or "document"))[:120] or "document"
    if Path(clean).suffix.lower() not in ALLOWED_EXT:
        raise BusinessError("Only PDF, PNG or JPG files are accepted")
    kind = _detect(content)
    if not kind:
        raise BusinessError("File content is not a valid PDF/PNG/JPG (extension mismatch or corrupt file)")
    ext, mime = kind
    digest = hashlib.sha256(content).hexdigest()
    same = db.query(Document).filter(Document.user_id == user.id, Document.sha256 == digest,
                                     Document.status != "REJECTED").all()
    if any(d.doc_type == doc_type for d in same):
        raise BusinessError("This exact file is already in your locker for this document type")
    status, checks = auto_verify(doc_type, user, user.profile, content, ext, {d.doc_type for d in same})
    stored = uuid.uuid4().hex + ext
    path = _root() / str(user.id)
    path.mkdir(parents=True, exist_ok=True)
    (path / stored).write_bytes(content)
    doc = Document(user_id=user.id, doc_type=doc_type, filename=clean, stored_name=stored, content_type=mime,
                   size=len(content), sha256=digest, status=status, source=source,
                   checks_json=json.dumps(checks))
    db.add(doc)
    db.flush()
    audit(db, actor_id or user.id, "DOC_UPLOADED", "document", doc.id, f"{doc_type} -> {status}")
    return doc


def make_sample(db, user, doc_type):
    """Demo helper: generate a realistic text PDF from the customer's own profile and upload it."""
    p = user.profile
    dt = doc_type.upper()
    head = {"ID_PROOF": "PAN CARD (SAMPLE)", "ADDRESS_PROOF": "UTILITY BILL (SAMPLE)",
            "INCOME_PROOF": "SALARY SLIP (SAMPLE)", "PROPERTY_PAPERS": "PROPERTY TITLE DEED (SAMPLE)",
            "VEHICLE_QUOTATION": "VEHICLE QUOTATION (SAMPLE)", "ADMISSION_LETTER": "ADMISSION LETTER (SAMPLE)",
            "GOLD_VALUATION": "GOLD VALUATION CERTIFICATE (SAMPLE)"}.get(dt, "DOCUMENT (SAMPLE)")
    lines = [head, "DEMO DOCUMENT - NOT A REAL RECORD", f"Document type: {dt}", f"Name: {user.full_name}"]
    if dt == "ID_PROOF":
        lines += [f"PAN: {p.pan}", f"Date of birth: {p.dob}"]
    elif dt == "ADDRESS_PROOF":
        lines += [f"Address: {p.address or '12 MG Road'}, {p.city or 'Kadapa'} {p.pincode or '516001'}"]
    elif dt == "INCOME_PROOF":
        lines += [f"Employer: {p.employer or 'Demo Employer Pvt Ltd'}", f"Monthly income: {p.monthly_income:,.0f}"]
    else:
        lines += [f"Issued to: {user.full_name}", "Value: as declared in application"]
    lines += ["Issued by: Demo Issuer", "This file was generated by Loan Guardian for demonstration."]
    return store(db, user, dt, f"sample_{dt.lower()}.pdf", simple_pdf(lines), source="SAMPLE")


# ---------- state ----------
def received(db, user_id):
    """(types the bank can count as received, subset still pending officer verification)."""
    rows = db.query(Document).filter(Document.user_id == user_id, Document.status != "REJECTED").all()
    verified = {d.doc_type for d in rows if d.status == "VERIFIED"}
    pending = {d.doc_type for d in rows if d.status == "UPLOADED"} - verified
    return sorted(verified | pending), sorted(pending)


def review(db, officer, doc, verdict, note):
    if verdict == "reject" and len(note.strip()) < 5:
        raise BusinessError("Give a reason when rejecting a document")
    doc.status = "VERIFIED" if verdict == "verify" else "REJECTED"
    doc.reviewer_id, doc.review_note = officer.id, note.strip() or None
    audit(db, officer.id, f"DOC_{doc.status}", "document", doc.id, f"{doc.doc_type} {note.strip()}"[:500])
    return doc


def remove(db, user, doc):
    try:
        file_path(doc).unlink(missing_ok=True)
    except OSError:
        pass
    audit(db, user.id, "DOC_DELETED", "document", doc.id, doc.doc_type)
    db.delete(doc)


def doc_view(d: Document):
    return {"id": d.id, "doc_type": d.doc_type, "label": DOC_LABELS.get(d.doc_type, d.doc_type),
            "filename": d.filename, "size": d.size, "status": d.status, "source": d.source,
            "checks": json.loads(d.checks_json or "[]"), "review_note": d.review_note,
            "uploaded_at": d.created_at.isoformat()}
