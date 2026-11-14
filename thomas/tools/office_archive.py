"""Bounded, non-executing access to Office Open XML packages."""

from __future__ import annotations

import posixpath
import re
import zipfile
from io import BytesIO
from xml.etree import ElementTree as ET

MAX_EXPANDED_BYTES = 30_000_000
MAX_PART_BYTES = 8_000_000
MAX_MEMBERS = 2_000
MAX_COMPRESSION_RATIO = 1_000
REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"


class OfficeReadError(ValueError):
    """An Office package is malformed or exceeds the document budget."""


class OfficeArchive:
    def __init__(self, raw: bytes):
        self.zip = zipfile.ZipFile(BytesIO(raw))
        infos = self.zip.infolist()
        if len(infos) > MAX_MEMBERS:
            raise OfficeReadError("This Office file contains too many package parts. Attach a smaller document.")
        total = 0
        names: set[str] = set()
        for info in infos:
            name = info.filename.rstrip("/")
            if (
                not name
                or name.startswith("/")
                or "\\" in name
                or ":" in name
                or any(p in {"", ".", ".."} for p in name.split("/"))
            ):
                raise OfficeReadError("This Office file contains an unsafe package path.")
            if name.casefold() in names:
                raise OfficeReadError("This Office file contains duplicate package parts.")
            names.add(name.casefold())
            if info.flag_bits & 1:
                raise OfficeReadError("This Office file is encrypted. Attach an unlocked copy.")
            if info.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}:
                raise OfficeReadError("This Office file uses unsupported compression. Export it again.")
            total += info.file_size
            if (
                info.file_size > MAX_PART_BYTES
                or total > MAX_EXPANDED_BYTES
                or info.file_size > max(1, info.compress_size) * MAX_COMPRESSION_RATIO
            ):
                raise OfficeReadError("This Office file expands beyond the safe document limit. Attach a smaller file.")
        if "[Content_Types].xml" not in self.zip.namelist():
            raise OfficeReadError("This file is not an Office Open XML document.")

    def close(self):
        self.zip.close()

    def xml(self, name: str, *, optional: bool = False):
        try:
            with self.zip.open(name) as part:
                raw = part.read(MAX_PART_BYTES + 1)
        except KeyError as exc:
            if optional:
                return None
            raise OfficeReadError("This Office file is missing a required document part.") from exc
        if len(raw) > MAX_PART_BYTES:
            raise OfficeReadError("This Office document part exceeds the extraction limit.")
        encoding = "utf-16" if raw.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8-sig"
        text = raw.decode(encoding)
        if "\x00" in text:
            raise OfficeReadError("This Office XML uses an unsupported encoding.")
        if re.search(r"<!\s*(?:DOCTYPE|ENTITY)\b", text, re.IGNORECASE):
            raise OfficeReadError("XML entity declarations are not supported in Office attachments.")
        return ET.fromstring(text)

    def relationships(self, part: str) -> dict[str, str]:
        parent, filename = posixpath.split(part)
        root = self.xml(posixpath.join(parent, "_rels", filename + ".rels"), optional=True)
        result = {}
        if root is None:
            return result
        for rel in root:
            if rel.get("TargetMode", "").lower() == "external":
                continue  # Never fetch linked files, images, templates, or data.
            target = str(rel.get("Target") or "")
            if target.startswith("/"):
                target = target[1:]
            else:
                target = posixpath.join(parent, target)
            target = posixpath.normpath(target)
            if target.startswith("../") or "\\" in target or ":" in target:
                raise OfficeReadError("This Office file contains an unsafe relationship target.")
            result[str(rel.get("Id") or "")] = target
        return result

    def validate_kind(self, kind: str):
        required = {
            "docx": ("/word/document.xml", "wordprocessingml.document.main+xml"),
            "xlsx": ("/xl/workbook.xml", "spreadsheetml.sheet.main+xml"),
            "pptx": ("/ppt/presentation.xml", "presentationml.presentation.main+xml"),
        }
        part, content_type = required[kind]
        types = self.xml("[Content_Types].xml")
        if any("macroenabled" in str(item.get("ContentType") or "").lower() for item in types) or any(
            name.lower().endswith("vbaproject.bin") for name in self.zip.namelist()
        ):
            raise OfficeReadError("Macro-enabled Office files are not supported. Attach a macro-free copy.")
        if not any(
            item.get("PartName") == part and str(item.get("ContentType") or "").endswith(content_type) for item in types
        ):
            raise OfficeReadError("This Office file does not match its document extension.")


class TextBudget:
    def __init__(self, limit: int):
        self.limit = limit
        self.size = 0
        self.lines: list[str] = []
        self.truncated = False

    def add(self, text: str) -> bool:
        available = self.limit - self.size
        if available <= 0:
            self.truncated = True
            return False
        line = str(text) + "\n"
        self.lines.append(line[:available])
        self.size += min(len(line), available)
        if len(line) > available:
            self.truncated = True
            return False
        return True

    def text(self) -> str:
        return "".join(self.lines).strip()
