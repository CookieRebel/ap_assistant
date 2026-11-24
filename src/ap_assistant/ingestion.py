"""Reads the Markdown corpus and splits each document into one chunk per `## n. Heading` section."""

import re
from pathlib import Path

from ap_assistant.schemas import Chunk

SECTION_HEADING = re.compile(r"^## (\d+)\.\s*(.*)$", re.MULTILINE)


class IngestError(Exception):
    pass


def _front_matter(text: str, name: str) -> tuple[dict[str, str], str]:
    """Splits `key: value` lines between the two `---` lines from the body."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---" or "---" not in [line.strip() for line in lines[1:]]:
        raise IngestError(f"{name}: no front matter")
    end = 1 + [line.strip() for line in lines[1:]].index("---")
    meta = {}
    for line in lines[1:end]:
        if ":" in line:
            key, value = line.split(":", 1)
            meta[key.strip()] = value.strip()
    return meta, "\n".join(lines[end + 1 :])


def _drop_title(text: str) -> str:
    return re.sub(r"^# .*$", "", text, count=1, flags=re.MULTILINE).strip()


def parse_document(path: Path) -> list[Chunk]:
    meta, body = _front_matter(path.read_text(), path.name)
    if not meta.get("document_id"):
        raise IngestError(f"{path.name}: no document_id")
    document_id = meta["document_id"]

    def chunk(section: str, heading: str, text: str) -> Chunk:
        return Chunk(
            chunk_id=f"{document_id}#{section}",
            document_id=document_id,
            document_type="policy" if document_id.startswith("FIN-POL-") else "external",
            title=meta.get("title", ""),
            version=meta.get("version", ""),
            status=meta.get("status", ""),
            classification=meta.get("classification", ""),
            section=section,
            heading=heading,
            source=path.name,
            text=text,
        )

    matches = list(SECTION_HEADING.finditer(body))
    if not matches:
        return [chunk("0", "", _drop_title(body))]

    chunks = []
    preamble = _drop_title(body[: matches[0].start()])
    if preamble:
        chunks.append(chunk("0", "", preamble))
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        chunks.append(chunk(m.group(1), m.group(2).strip(), body[m.end() : end].strip()))
    return chunks


def read_corpus(corpus_dir: Path) -> list[Chunk]:
    """Parses every .md file. Raises IngestError on the first bad file, so nothing partial is returned."""
    files = sorted(corpus_dir.glob("*.md"))
    if not files:
        raise IngestError(f"{corpus_dir}: no Markdown files")
    return [c for f in files for c in parse_document(f)]
