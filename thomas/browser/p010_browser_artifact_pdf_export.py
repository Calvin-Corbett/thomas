from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import zipfile
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path

SUPPORTED_IMAGE_EXTENSIONS: tuple[str, ...] = (".png", ".jpg", ".jpeg", ".webp")


class BrowserArtifactPdfExportError(Exception):
    """Base error for browser artifact PDF export failures."""

    code: str = "BROWSER_ARTIFACT_PDF_EXPORT_ERROR"
    exit_code: int = 1

    def __init__(self, message: str, *, details: dict[str, object] | None = None) -> None:
        super().__init__(message)
        self.details = details or {}

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {"code": self.code, "message": str(self)}
        if self.details:
            payload["details"] = self.details
        return payload


class InvalidInputError(BrowserArtifactPdfExportError):
    code = "INVALID_INPUT"
    exit_code = 2


class MissingConfigError(BrowserArtifactPdfExportError):
    code = "MISSING_CONFIG"
    exit_code = 2


class ArtifactNotFoundError(BrowserArtifactPdfExportError):
    code = "ARTIFACT_NOT_FOUND"
    exit_code = 2


class ArtifactNoImagesError(BrowserArtifactPdfExportError):
    code = "NO_IMAGES_FOUND"
    exit_code = 2


class OutputExistsError(BrowserArtifactPdfExportError):
    code = "OUTPUT_EXISTS"
    exit_code = 2


class PdfRenderFailedError(BrowserArtifactPdfExportError):
    code = "PDF_RENDER_FAILED"
    exit_code = 1


@dataclass(frozen=True)
class BrowserArtifactPdfExportRequest:
    """
    Contract for exporting a browser artifact (directory of images) to a PDF.

    artifact_ref:
        Either a filesystem path to an artifact directory / image file,
        or an artifact id that can be resolved relative to an artifacts root.

    output_path:
        Target output path. When output_format resolves to:
        - "pdf": path must end with ".pdf" (if provided). If omitted, exporter writes
                 "<artifact_name>.pdf" in the current working directory.
        - "zip": path must end with ".zip" (if provided). If omitted, exporter writes
                 "<artifact_name>.zip" in the current working directory.

    output_format:
        "auto" | "pdf" | "zip"
        - auto: infer from output_path extension if given, else default to "pdf".

    include_images_in_zip:
        When output_format="zip", include the original images under "images/" in the bundle.

    artifacts_root:
        Optional override for resolving artifact ids. If omitted, resolution uses:
        - THOMAS_BROWSER_ARTIFACTS_DIR
        - THOMAS_ARTIFACTS_DIR
        - (best-effort) any artifact directory hint exposed by thomas.tools.browser
    """

    artifact_ref: str
    output_path: str | None = None
    overwrite: bool = False
    page_size: str = "letter"  # "letter" | "a4" | "auto"
    artifacts_root: str | None = None
    output_format: str = "auto"  # "auto" | "pdf" | "zip"
    include_images_in_zip: bool = False


@dataclass(frozen=True)
class BrowserArtifactPdfExportResult:
    """
    Machine-readable result contract.

    output_format:
        "pdf" or "zip"
    output_path:
        Path to the produced file (PDF or ZIP).
    pdf_path:
        Present only for output_format="pdf".
    zip_path:
        Present only for output_format="zip".
    pdf_name_in_zip:
        Present only for output_format="zip".
    manifest_name_in_zip:
        Present only for output_format="zip".
    """

    output_format: str
    output_path: str
    artifact_path: str
    pages: int
    images: int
    image_paths: tuple[str, ...] = field(default_factory=tuple)
    pdf_path: str | None = None
    zip_path: str | None = None
    pdf_name_in_zip: str | None = None
    manifest_name_in_zip: str | None = None
    sha256: str | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


_DIGIT_RE = re.compile(r"(\d+)")


def _natural_sort_key(path: Path) -> list[object]:
    parts: list[object] = []
    for chunk in _DIGIT_RE.split(str(path).lower()):
        if chunk.isdigit():
            parts.append(int(chunk))
        else:
            parts.append(chunk)
    return parts


def _looks_like_path(value: str) -> bool:
    # Heuristic: anything with path separators, a drive spec, or an extension.
    return ("/" in value) or ("\\" in value) or (":" in value) or ("." in Path(value).name)


def _sha256_bytes(data: bytes) -> str:
    h = hashlib.sha256()
    h.update(data)
    return h.hexdigest()


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _resolve_default_artifacts_root() -> Path:
    env = os.environ.get("THOMAS_BROWSER_ARTIFACTS_DIR") or os.environ.get("THOMAS_ARTIFACTS_DIR")
    if env:
        return Path(env)

    # Best-effort: try to discover a default from thomas.tools.browser without importing
    # unrelated heavy dependencies at module import time.
    try:
        from thomas.tools import browser as browser_tool  # type: ignore
    except (ImportError, ModuleNotFoundError):
        browser_tool = None

    if browser_tool is not None:
        for attr in (
            "DEFAULT_BROWSER_ARTIFACTS_DIR",
            "DEFAULT_ARTIFACTS_DIR",
            "DEFAULT_ARTIFACT_DIR",
            "BROWSER_ARTIFACTS_DIR",
            "ARTIFACTS_DIR",
            "ARTIFACT_DIR",
        ):
            val = getattr(browser_tool, attr, None)
            if isinstance(val, (str, os.PathLike)):
                return Path(val)

        for fn_name in (
            "get_browser_artifacts_dir",
            "get_artifacts_dir",
            "get_artifact_dir",
            "default_artifacts_dir",
        ):
            fn = getattr(browser_tool, fn_name, None)
            if callable(fn):
                try:
                    val = fn()
                except TypeError:
                    continue
                if isinstance(val, (str, os.PathLike)):
                    return Path(val)

    raise MissingConfigError(
        "No artifacts root configured. Provide a filesystem path, set THOMAS_BROWSER_ARTIFACTS_DIR, "
        "or pass an explicit artifacts_root.",
    )


def _resolve_artifact_path(artifact_ref: str, artifacts_root: str | None) -> Path:
    ref = artifact_ref.strip()
    if not ref:
        raise InvalidInputError("artifact_ref is required.")

    # Prefer explicit filesystem paths.
    candidate = Path(ref)
    if candidate.exists():
        return candidate

    # If it *looks* like a path and doesn't exist, treat it as missing rather than an id.
    if _looks_like_path(ref):
        raise ArtifactNotFoundError(f"Artifact not found: {ref}")

    root = Path(artifacts_root) if artifacts_root else _resolve_default_artifacts_root()
    resolved = root / ref
    if not resolved.exists():
        raise ArtifactNotFoundError(
            f"Artifact not found: {ref}",
            details={"resolved_path": str(resolved), "artifacts_root": str(root)},
        )
    return resolved


def _collect_images(artifact_path: Path) -> list[Path]:
    if artifact_path.is_file():
        if artifact_path.suffix.lower() in SUPPORTED_IMAGE_EXTENSIONS:
            return [artifact_path]
        return []

    images: list[Path] = []
    for p in artifact_path.rglob("*"):
        if p.is_file() and p.suffix.lower() in SUPPORTED_IMAGE_EXTENSIONS:
            images.append(p)
    images.sort(key=_natural_sort_key)
    return images


def _normalize_page_size(value: str) -> str:
    v = (value or "").strip().lower()
    if v in {"letter", "a4", "auto"}:
        return v
    raise InvalidInputError(f"Unsupported page_size: {value}. Expected one of: letter, a4, auto.")


def _normalize_output_format(value: str) -> str:
    v = (value or "").strip().lower()
    if v in {"auto", "pdf", "zip"}:
        return v
    raise InvalidInputError(f"Unsupported output_format: {value}. Expected one of: auto, pdf, zip.")


def _detect_output_format(output_path: str | None, output_format: str) -> str:
    fmt = _normalize_output_format(output_format)
    if fmt != "auto":
        return fmt
    if output_path is None:
        return "pdf"
    suffix = Path(output_path).suffix.lower()
    if suffix == ".pdf":
        return "pdf"
    if suffix == ".zip":
        return "zip"
    raise InvalidInputError(
        "When output_format=auto and output_path is provided, output_path must end with .pdf or .zip.",
        details={"output_path": output_path},
    )


def _default_output_path(*, artifact_path: Path, output_format: str) -> Path:
    name = artifact_path.name if artifact_path.is_dir() else artifact_path.stem
    ext = ".zip" if output_format == "zip" else ".pdf"
    return Path.cwd() / f"{name}{ext}"


def _validate_output_extension(*, output_path: Path, output_format: str) -> None:
    suffix = output_path.suffix.lower()
    if output_format == "pdf" and suffix and suffix != ".pdf":
        raise InvalidInputError("PDF output_path must end with .pdf.", details={"output_path": str(output_path)})
    if output_format == "zip" and suffix and suffix != ".zip":
        raise InvalidInputError("ZIP output_path must end with .zip.", details={"output_path": str(output_path)})


_ZIP_FIXED_DATETIME = (1980, 1, 1, 0, 0, 0)


def _zip_write_bytes(zf: zipfile.ZipFile, arcname: str, data: bytes) -> None:
    # Stable timestamp + permissions for deterministic bundles.
    zi = zipfile.ZipInfo(filename=arcname, date_time=_ZIP_FIXED_DATETIME)
    zi.compress_type = zipfile.ZIP_DEFLATED
    zi.external_attr = 0o644 << 16
    zf.writestr(zi, data)


def _zip_write_file(zf: zipfile.ZipFile, arcname: str, path: Path) -> None:
    _zip_write_bytes(zf, arcname, path.read_bytes())


def export_browser_artifact_to_pdf(req: BrowserArtifactPdfExportRequest) -> BrowserArtifactPdfExportResult:
    """
    Export a browser artifact to a multi-page PDF OR to a ZIP bundle containing a PDF.

    Deterministic behavior:
    - Images are discovered recursively and natural-sorted by path.
    - Output format is inferred from output_path (unless overridden).
    - If output exists and overwrite is False, OutputExistsError is raised.
    - Errors expose stable `code` values via BrowserArtifactPdfExportError subclasses.
    - ZIP bundles are written with stable entry timestamps/permissions.
    """
    artifact_path = _resolve_artifact_path(req.artifact_ref, req.artifacts_root)
    page_size_mode = _normalize_page_size(req.page_size)
    output_format = _detect_output_format(req.output_path, req.output_format)

    image_paths = _collect_images(artifact_path)
    if not image_paths:
        raise ArtifactNoImagesError(
            f"No renderable images found in artifact: {artifact_path}",
            details={"supported_extensions": list(SUPPORTED_IMAGE_EXTENSIONS)},
        )

    # Output path defaults to CWD/<artifact_name>.<ext> for shareability.
    if req.output_path:
        out_path = Path(req.output_path)
    else:
        out_path = _default_output_path(artifact_path=artifact_path, output_format=output_format)

    _validate_output_extension(output_path=out_path, output_format=output_format)

    if out_path.exists() and not req.overwrite:
        raise OutputExistsError(f"Output already exists: {out_path}")

    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise PdfRenderFailedError(
            f"Failed to create output directory: {out_path.parent}",
            details={"os_error": str(e)},
        ) from e

    if output_format == "pdf":
        return _export_as_pdf(
            artifact_path=artifact_path,
            image_paths=image_paths,
            out_path=out_path,
            page_size_mode=page_size_mode,
        )

    return _export_as_zip(
        artifact_path=artifact_path,
        image_paths=image_paths,
        out_path=out_path,
        page_size_mode=page_size_mode,
        include_images=req.include_images_in_zip,
    )


def _export_as_pdf(
    *,
    artifact_path: Path,
    image_paths: Sequence[Path],
    out_path: Path,
    page_size_mode: str,
) -> BrowserArtifactPdfExportResult:
    # Write atomically to avoid leaving partial PDFs on external failure.
    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix=out_path.stem + ".",
            suffix=".pdf",
            dir=str(out_path.parent),
            delete=False,
        ) as tmp:
            tmp_path = Path(tmp.name)

        _render_pdf(
            image_paths=image_paths,
            output_path=tmp_path,
            page_size_mode=page_size_mode,
        )

        if out_path.exists():
            # Caller already checked overwrite semantics; this is the atomic swap stage.
            out_path.unlink()
        tmp_path.replace(out_path)
    except BrowserArtifactPdfExportError:
        raise
    except Exception as e:  # noqa: BLE001
        if tmp_path is not None:
            try:
                if tmp_path.exists():
                    tmp_path.unlink()
            except OSError:
                pass
        raise PdfRenderFailedError("Failed to render PDF.", details={"error": str(e)}) from e

    sha = _sha256_file(out_path)
    return BrowserArtifactPdfExportResult(
        output_format="pdf",
        output_path=str(out_path),
        pdf_path=str(out_path),
        zip_path=None,
        pdf_name_in_zip=None,
        manifest_name_in_zip=None,
        artifact_path=str(artifact_path),
        pages=len(image_paths),
        images=len(image_paths),
        image_paths=tuple(str(p) for p in image_paths),
        sha256=sha,
    )


def _export_as_zip(
    *,
    artifact_path: Path,
    image_paths: Sequence[Path],
    out_path: Path,
    page_size_mode: str,
    include_images: bool,
) -> BrowserArtifactPdfExportResult:
    tmp_zip_path: Path | None = None
    tmp_pdf_path: Path | None = None

    artifact_name = artifact_path.name if artifact_path.is_dir() else artifact_path.stem
    pdf_name_in_zip = f"{artifact_name}.pdf"
    manifest_name_in_zip = "manifest.json"

    # Prepare manifest with stable ordering (json.dumps sort_keys=True later).
    manifest: dict[str, object] = {
        "artifact_path": str(artifact_path),
        "pages": len(image_paths),
        "images": len(image_paths),
        "page_size": page_size_mode,
        "pdf_name": pdf_name_in_zip,
        "include_images": include_images,
    }

    # Compute relative paths used in the manifest (and in the ZIP, if include_images=True).
    if artifact_path.is_dir():
        rel_image_paths = [p.relative_to(artifact_path).as_posix() for p in image_paths]
    else:
        rel_image_paths = [Path(image_paths[0].name).as_posix()]
    manifest["image_paths"] = rel_image_paths

    try:
        # Render PDF into a temp file first.
        with tempfile.NamedTemporaryFile(
            prefix=artifact_name + ".",
            suffix=".pdf",
            dir=str(out_path.parent),
            delete=False,
        ) as tmp_pdf:
            tmp_pdf_path = Path(tmp_pdf.name)

        _render_pdf(image_paths=image_paths, output_path=tmp_pdf_path, page_size_mode=page_size_mode)
        pdf_bytes = tmp_pdf_path.read_bytes()
        manifest["pdf_sha256"] = _sha256_bytes(pdf_bytes)

        # Create ZIP atomically.
        with tempfile.NamedTemporaryFile(
            prefix=out_path.stem + ".",
            suffix=".zip",
            dir=str(out_path.parent),
            delete=False,
        ) as tmp_zip:
            tmp_zip_path = Path(tmp_zip.name)

        with zipfile.ZipFile(tmp_zip_path, mode="w") as zf:
            _zip_write_bytes(zf, pdf_name_in_zip, pdf_bytes)

            if include_images:
                # Write images under images/<relative path>
                for rel, abs_path in zip(rel_image_paths, image_paths, strict=False):
                    arc = f"images/{rel}"
                    _zip_write_file(zf, arc, abs_path)

            manifest_bytes = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")
            _zip_write_bytes(zf, manifest_name_in_zip, manifest_bytes)

        if out_path.exists():
            out_path.unlink()
        tmp_zip_path.replace(out_path)

        sha = _sha256_file(out_path)
        return BrowserArtifactPdfExportResult(
            output_format="zip",
            output_path=str(out_path),
            pdf_path=None,
            zip_path=str(out_path),
            pdf_name_in_zip=pdf_name_in_zip,
            manifest_name_in_zip=manifest_name_in_zip,
            artifact_path=str(artifact_path),
            pages=len(image_paths),
            images=len(image_paths),
            image_paths=tuple(str(p) for p in image_paths),
            sha256=sha,
        )

    except BrowserArtifactPdfExportError:
        raise
    except Exception as e:  # noqa: BLE001
        raise PdfRenderFailedError("Failed to render ZIP bundle.", details={"error": str(e)}) from e
    finally:
        for p in (tmp_pdf_path, tmp_zip_path):
            if p is None:
                continue
            try:
                if p.exists():
                    p.unlink()
            except OSError:
                pass


def _render_pdf(*, image_paths: Sequence[Path], output_path: Path, page_size_mode: str) -> None:
    try:
        from reportlab.lib.pagesizes import A4, landscape, letter, portrait
        from reportlab.lib.utils import ImageReader
        from reportlab.pdfgen import canvas
    except Exception as e:  # noqa: BLE001
        raise PdfRenderFailedError(
            "PDF rendering dependencies are unavailable (reportlab).",
            details={"error": str(e)},
        ) from e

    base_page_sizes = {"letter": letter, "a4": A4}
    base_size = base_page_sizes.get(page_size_mode, letter)

    # Create with an initial pagesize; we may change it per page.
    c = canvas.Canvas(str(output_path), pagesize=base_size)

    for img_path in image_paths:
        try:
            reader = ImageReader(str(img_path))
            iw, ih = reader.getSize()
        except Exception as e:  # noqa: BLE001
            raise PdfRenderFailedError(
                f"Failed to read image: {img_path}",
                details={"error": str(e), "image_path": str(img_path)},
            ) from e

        if page_size_mode == "auto":
            c.setPageSize((iw, ih))
            c.drawImage(reader, 0, 0, width=iw, height=ih)
            c.showPage()
            continue

        # Auto-orient pages for readability: landscape image => landscape page.
        page_size = landscape(base_size) if iw > ih else portrait(base_size)
        page_w, page_h = page_size
        c.setPageSize((page_w, page_h))

        # Scale image to fit inside the page with a small margin.
        margin_scale = 0.95
        scale = min(page_w / float(iw), page_h / float(ih)) * margin_scale
        w = float(iw) * scale
        h = float(ih) * scale
        x = (page_w - w) / 2.0
        y = (page_h - h) / 2.0

        c.drawImage(reader, x, y, width=w, height=h)
        c.showPage()

    try:
        c.save()
    except Exception as e:  # noqa: BLE001
        raise PdfRenderFailedError("Failed to finalize PDF.", details={"error": str(e)}) from e
