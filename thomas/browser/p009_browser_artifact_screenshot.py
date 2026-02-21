from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Optional


class BrowserArtifactScreenshotErrorCode(str, Enum):
    INVALID_INPUT = "INVALID_INPUT"
    MISSING_CONFIG = "MISSING_CONFIG"
    EXTERNAL_FAILURE = "EXTERNAL_FAILURE"


@dataclass(frozen=True)
class BrowserArtifactScreenshotRequest:
    """Input contract for artifact screenshot.

    `artifact` can be either:
      - a filesystem path to an artifact (HTML/PDF/image/etc), or
      - an artifact identifier resolvable via `artifact_root` or Thomas config.
    """

    artifact: str
    output: Optional[str] = None
    full_page: bool = True
    viewport_width: int = 1280
    viewport_height: int = 720
    wait_ms: int = 250
    timeout_ms: int = 30_000
    artifact_root: Optional[str] = None


@dataclass(frozen=True)
class BrowserArtifactScreenshotResult:
    artifact_path: str
    screenshot_path: str
    renderer: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "artifact_path": self.artifact_path,
            "screenshot_path": self.screenshot_path,
            "renderer": self.renderer,
        }


class BrowserArtifactScreenshotError(RuntimeError):
    """Deterministic error for artifact screenshot."""

    def __init__(
        self,
        code: BrowserArtifactScreenshotErrorCode,
        message: str,
        *,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "code": self.code.value,
            "message": self.message,
            "details": dict(self.details),
        }


def _guess_artifact_root_from_thomas() -> Optional[Path]:
    """Best-effort lookup of an artifact root from the existing Thomas browser tool.

    This keeps the feature usable even when the caller passes an artifact id instead
    of a direct path, but it never hard-fails if Thomas internals evolve.
    """
    try:
        from thomas.tools import browser as browser_tool  # type: ignore
    except Exception:
        return None

    candidates: list[Any] = []
    for attr_name in (
        "artifact_root",
        "artifacts_root",
        "ARTIFACT_ROOT",
        "ARTIFACTS_ROOT",
        "default_artifact_root",
        "DEFAULT_ARTIFACT_ROOT",
    ):
        if hasattr(browser_tool, attr_name):
            candidates.append(getattr(browser_tool, attr_name))

    for func_name in (
        "get_artifact_root",
        "get_artifacts_root",
        "default_artifacts_root",
        "get_default_artifact_root",
        "get_default_artifacts_root",
    ):
        func = getattr(browser_tool, func_name, None)
        if callable(func):
            candidates.append(func)

    for cand in candidates:
        try:
            val = cand() if callable(cand) else cand
        except Exception:
            continue
        if not val:
            continue
        try:
            p = Path(val)
        except Exception:
            continue
        if p.exists() and p.is_dir():
            return p
    return None


def _is_within_root(candidate: Path, root: Path) -> bool:
    try:
        candidate.resolve().relative_to(root.resolve())
        return True
    except Exception:
        return False


def _resolve_artifact_path(req: BrowserArtifactScreenshotRequest) -> Path:
    artifact_path = Path(req.artifact)

    # Direct path?
    if artifact_path.exists():
        if artifact_path.is_file():
            return artifact_path.resolve()
        raise BrowserArtifactScreenshotError(
            BrowserArtifactScreenshotErrorCode.INVALID_INPUT,
            f"Artifact path is not a file: {artifact_path}",
            details={"artifact": req.artifact},
        )

    roots: list[Path] = []

    if req.artifact_root is not None:
        root_path = Path(req.artifact_root)
        if not root_path.exists() or not root_path.is_dir():
            raise BrowserArtifactScreenshotError(
                BrowserArtifactScreenshotErrorCode.MISSING_CONFIG,
                "artifact_root is set but does not point to an existing directory.",
                details={"artifact_root": str(root_path)},
            )
        roots.append(root_path)

    thomas_root = _guess_artifact_root_from_thomas()
    if thomas_root:
        roots.append(thomas_root)

    for root in roots:
        candidate = (root / req.artifact)
        if not _is_within_root(candidate, root):
            continue
        candidate = candidate.resolve()
        if candidate.exists() and candidate.is_file():
            return candidate

    if roots:
        raise BrowserArtifactScreenshotError(
            BrowserArtifactScreenshotErrorCode.INVALID_INPUT,
            "Artifact was not found in any configured artifact root.",
            details={"artifact": req.artifact, "artifact_roots": [str(r) for r in roots]},
        )

    raise BrowserArtifactScreenshotError(
        BrowserArtifactScreenshotErrorCode.INVALID_INPUT,
        "Artifact path does not exist. Provide a valid path or pass --artifact-root to resolve an artifact id.",
        details={"artifact": req.artifact},
    )


def _default_output_path(artifact_path: Path) -> Path:
    # Avoid clobbering a sibling file named <stem>.png by using a dedicated suffix.
    return artifact_path.with_name(f"{artifact_path.stem}.screenshot.png")


def _ensure_output_path(req_out: Optional[str], artifact_path: Path) -> Path:
    output_path = Path(req_out) if req_out else _default_output_path(artifact_path)

    if output_path.exists() and output_path.is_dir():
        output_path = output_path / _default_output_path(artifact_path).name

    if output_path.suffix.lower() != ".png":
        raise BrowserArtifactScreenshotError(
            BrowserArtifactScreenshotErrorCode.INVALID_INPUT,
            "Output path must end with .png",
            details={"output": str(output_path)},
        )

    try:
        if artifact_path.resolve() == output_path.resolve():
            raise BrowserArtifactScreenshotError(
                BrowserArtifactScreenshotErrorCode.INVALID_INPUT,
                "Output path must be different from the artifact path.",
                details={"artifact_path": str(artifact_path), "output": str(output_path)},
            )
    except BrowserArtifactScreenshotError:
        raise
    except Exception:
        # If resolve fails due to non-existent paths or permissions, we'll let downstream creation handle it.
        pass

    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        raise BrowserArtifactScreenshotError(
            BrowserArtifactScreenshotErrorCode.INVALID_INPUT,
            "Failed to create the output directory for the screenshot.",
            details={"output_path": str(output_path), "exception": repr(e)},
        ) from e

    return output_path


def _capture_pdf_with_pymupdf(*, artifact_path: Path, output_path: Path) -> None:
    try:
        import fitz  # PyMuPDF
    except Exception as e:  # pragma: no cover
        raise BrowserArtifactScreenshotError(
            BrowserArtifactScreenshotErrorCode.MISSING_CONFIG,
            "PyMuPDF is required to render PDF artifacts, but it could not be imported.",
            details={"exception": repr(e)},
        ) from e

    try:
        doc = fitz.open(str(artifact_path))
        if doc.page_count < 1:
            raise BrowserArtifactScreenshotError(
                BrowserArtifactScreenshotErrorCode.EXTERNAL_FAILURE,
                "PDF artifact has no pages to render.",
                details={"artifact_path": str(artifact_path)},
            )
        page = doc.load_page(0)
        # Render at 2x scale for readability. Deterministic for our purposes.
        pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
        pix.save(str(output_path))
        doc.close()
    except BrowserArtifactScreenshotError:
        raise
    except Exception as e:
        raise BrowserArtifactScreenshotError(
            BrowserArtifactScreenshotErrorCode.EXTERNAL_FAILURE,
            "Failed to render PDF artifact to a screenshot.",
            details={"artifact_path": str(artifact_path), "exception": repr(e)},
        ) from e


def _capture_image_with_pillow(*, artifact_path: Path, output_path: Path) -> None:
    try:
        from PIL import Image
    except Exception as e:  # pragma: no cover
        raise BrowserArtifactScreenshotError(
            BrowserArtifactScreenshotErrorCode.MISSING_CONFIG,
            "Pillow is required to convert image artifacts to PNG, but it could not be imported.",
            details={"exception": repr(e)},
        ) from e

    try:
        with Image.open(artifact_path) as im:
            # Ensure a standard, browser-friendly output.
            if im.mode not in ("RGB", "RGBA"):
                im = im.convert("RGBA")
            im.save(output_path, format="PNG")
    except Exception as e:
        raise BrowserArtifactScreenshotError(
            BrowserArtifactScreenshotErrorCode.EXTERNAL_FAILURE,
            "Failed to convert image artifact to PNG screenshot.",
            details={"artifact_path": str(artifact_path), "output_path": str(output_path), "exception": repr(e)},
        ) from e


def _capture_with_playwright(
    *,
    artifact_path: Path,
    output_path: Path,
    viewport_width: int,
    viewport_height: int,
    full_page: bool,
    wait_ms: int,
    timeout_ms: int,
) -> None:
    try:
        from playwright.sync_api import Error as PlaywrightError  # type: ignore
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError  # type: ignore
        from playwright.sync_api import sync_playwright  # type: ignore
    except Exception as e:  # pragma: no cover
        raise BrowserArtifactScreenshotError(
            BrowserArtifactScreenshotErrorCode.MISSING_CONFIG,
            "Playwright is required to render HTML or other non-PDF artifacts, but it could not be imported.",
            details={"exception": repr(e)},
        ) from e

    uri = artifact_path.resolve().as_uri()

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": viewport_width, "height": viewport_height})
            page.goto(uri, wait_until="load", timeout=timeout_ms)
            if wait_ms:
                page.wait_for_timeout(wait_ms)
            page.screenshot(path=str(output_path), full_page=full_page)
            browser.close()
    except PlaywrightTimeoutError as e:
        raise BrowserArtifactScreenshotError(
            BrowserArtifactScreenshotErrorCode.EXTERNAL_FAILURE,
            "Timed out while rendering the artifact for screenshot.",
            details={"artifact_path": str(artifact_path), "timeout_ms": timeout_ms},
        ) from e
    except PlaywrightError as e:
        raise BrowserArtifactScreenshotError(
            BrowserArtifactScreenshotErrorCode.EXTERNAL_FAILURE,
            "Playwright failed while capturing the screenshot.",
            details={"artifact_path": str(artifact_path)},
        ) from e
    except BrowserArtifactScreenshotError:
        raise
    except Exception as e:
        raise BrowserArtifactScreenshotError(
            BrowserArtifactScreenshotErrorCode.EXTERNAL_FAILURE,
            "Unexpected failure while capturing the screenshot.",
            details={"artifact_path": str(artifact_path), "exception": repr(e)},
        ) from e


def take_artifact_screenshot(req: BrowserArtifactScreenshotRequest) -> BrowserArtifactScreenshotResult:
    """Render an artifact and save a PNG screenshot."""

    if req.viewport_width <= 0 or req.viewport_height <= 0:
        raise BrowserArtifactScreenshotError(
            BrowserArtifactScreenshotErrorCode.INVALID_INPUT,
            "Viewport width and height must be positive integers.",
            details={"viewport_width": req.viewport_width, "viewport_height": req.viewport_height},
        )
    if req.wait_ms < 0 or req.timeout_ms <= 0:
        raise BrowserArtifactScreenshotError(
            BrowserArtifactScreenshotErrorCode.INVALID_INPUT,
            "wait_ms must be >= 0 and timeout_ms must be > 0.",
            details={"wait_ms": req.wait_ms, "timeout_ms": req.timeout_ms},
        )

    artifact_path = _resolve_artifact_path(req)
    output_path = _ensure_output_path(req.output, artifact_path)

    # Route by artifact type:
    suffix = artifact_path.suffix.lower()

    if suffix in {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tiff", ".tif"}:
        _capture_image_with_pillow(artifact_path=artifact_path, output_path=output_path)
        renderer = "pillow"
    elif suffix == ".pdf":
        _capture_pdf_with_pymupdf(artifact_path=artifact_path, output_path=output_path)
        renderer = "pymupdf"
    else:
        _capture_with_playwright(
            artifact_path=artifact_path,
            output_path=output_path,
            viewport_width=req.viewport_width,
            viewport_height=req.viewport_height,
            full_page=req.full_page,
            wait_ms=req.wait_ms,
            timeout_ms=req.timeout_ms,
        )
        renderer = "playwright"

    if not output_path.exists():
        raise BrowserArtifactScreenshotError(
            BrowserArtifactScreenshotErrorCode.EXTERNAL_FAILURE,
            "Screenshot capture reported success but the output file was not created.",
            details={"output_path": str(output_path)},
        )

    return BrowserArtifactScreenshotResult(
        artifact_path=str(artifact_path),
        screenshot_path=str(output_path),
        renderer=renderer,
    )
