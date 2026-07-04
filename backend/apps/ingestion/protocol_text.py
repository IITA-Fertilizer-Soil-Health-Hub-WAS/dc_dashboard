"""Extract plain text from an uploaded protocol/questionnaire.

No heavy parsers required: plain-text formats decode directly, and .docx is a zip
whose ``word/document.xml`` we strip to text. PDFs aren't parsed here (no bundled
extractor) — the upload UI lets the user paste text instead.
"""
from __future__ import annotations

import io
import re
import zipfile

TEXT_EXTS = (".txt", ".md", ".csv", ".tsv")


class ProtocolError(ValueError):
    """The uploaded file can't be read as text."""


def extract_text(filename: str, data: bytes) -> str:
    name = (filename or "").lower()
    if name.endswith(".docx"):
        return _docx_text(data)
    if name.endswith(TEXT_EXTS) or not name:
        return _decode(data)
    if name.endswith(".pdf"):
        raise ProtocolError(
            "PDF isn't supported here — export the protocol to .docx/.txt, or paste the text.")
    # Unknown extension: try a best-effort decode.
    return _decode(data)


def _decode(data: bytes) -> str:
    for enc in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    raise ProtocolError("Couldn't decode the file as text.")


def _docx_text(data: bytes) -> str:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            xml = z.read("word/document.xml").decode("utf-8", "ignore")
    except (zipfile.BadZipFile, KeyError) as exc:
        raise ProtocolError(f"Not a readable .docx file: {exc}")
    # Paragraph breaks, then keep only the text runs.
    xml = re.sub(r"</w:p>", "\n", xml)
    xml = re.sub(r"<w:tab[^>]*/>", "\t", xml)
    runs = re.findall(r"<w:t[^>]*>(.*?)</w:t>", xml, flags=re.DOTALL)
    text = "".join(runs)
    # Un-escape the handful of XML entities that appear in run text.
    for a, b in (("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"), ("&quot;", '"'), ("&apos;", "'")):
        text = text.replace(a, b)
    return text.strip()
