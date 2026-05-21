from __future__ import annotations

import hashlib
import json
import os
import time
from collections.abc import Sequence
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from PIL import Image, ImageOps
from pydantic import BaseModel

router = APIRouter(prefix="/api/chat", tags=["chat"])


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ImportError:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ImportError:
        return default


def get_upload_dir() -> Path:
    return Path(os.getenv("THOMAS_UPLOAD_DIR", "runtime/uploads")).resolve()


def get_upload_ttl_seconds() -> int:
    return _env_int("THOMAS_UPLOAD_TTL_SECONDS", 3600)


def get_max_upload_bytes() -> int:
    mb = _env_float("THOMAS_MAX_UPLOAD_MB", 12.0)
    return int(mb * 1024 * 1024)


def get_max_image_pixels() -> int:
    return _env_int("THOMAS_MAX_IMAGE_PIXELS", 40_000_000)


def get_max_image_dim() -> int:
    return _env_int("THOMAS_MAX_IMAGE_DIM", 8000)


def should_downscale_large_images() -> bool:
    return os.getenv("THOMAS_DOWNSCALE_LARGE_IMAGES", "1").strip() not in ("0", "false", "False", "")


def _ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def _safe_json_dump(p: Path, obj: dict) -> None:
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, p)


def _cleanup_pair(image_path: Path) -> None:
    meta_path = image_path.with_suffix(image_path.suffix + ".json")
    try:
        image_path.unlink(missing_ok=True)
    except json.JSONDecodeError:
        pass
    try:
        meta_path.unlink(missing_ok=True)
    except json.JSONDecodeError:
        pass


def cleanup_old_uploads(upload_dir: Path, ttl_seconds: int, *, max_delete: int = 500) -> int:
    """Best-effort delete for files older than ttl_seconds.

    Deletes both image files and their sidecar metadata (*.json) if present.
    """
    if ttl_seconds <= 0:
        return 0

    now = time.time()
    deleted = 0

    try:
        for child in upload_dir.glob("*"):
            if deleted >= max_delete:
                break
            try:
                if not child.is_file():
                    continue
                # Only act on actual image blobs (ignore sidecars; we'll delete them via pair logic)
                if child.suffix.lower() == ".json" or child.name.endswith(".json.tmp"):
                    continue

                age = now - child.stat().st_mtime
                if age > ttl_seconds:
                    _cleanup_pair(child)
                    deleted += 1
            except json.JSONDecodeError:
                continue
    except json.JSONDecodeError:
        return deleted

    return deleted


def _guess_ext(fmt: str | None) -> str:
    f = (fmt or "").upper()
    if f == "JPEG":
        return ".jpg"
    if f == "PNG":
        return ".png"
    if f == "WEBP":
        return ".webp"
    if f == "GIF":
        return ".gif"
    if f == "BMP":
        return ".bmp"
    if f in ("TIFF", "TIF"):
        return ".tiff"
    return ".img"


def _downscale_if_needed(img: Image.Image, max_dim: int) -> Image.Image:
    w, h = img.size
    if max(w, h) <= max_dim:
        return img
    # Keep aspect ratio; use Pillow's thumbnail for good quality
    out = img.copy()
    out.thumbnail((max_dim, max_dim))
    return out


class UploadItem(BaseModel):
    image_id: str
    token: str
    filename: str
    content_type: str
    size_bytes: int
    sha256: str
    width: int
    height: int
    format: str


class UploadResponse(BaseModel):
    uploads: list[UploadItem]


@router.post("/upload")
async def upload_image(file: list[UploadFile] = File(...)) -> JSONResponse:
    """Upload one or many images (repeat the 'file' form key)."""
    upload_dir = get_upload_dir()
    _ensure_dir(upload_dir)

    # TTL cleanup before save (cheap + keeps dir sane)
    cleanup_old_uploads(upload_dir, get_upload_ttl_seconds())

    max_bytes = get_max_upload_bytes()

    # Pillow decompression bomb protection (global)
    Image.MAX_IMAGE_PIXELS = get_max_image_pixels()  # type: ignore[attr-defined]

    max_dim = get_max_image_dim()
    do_downscale = should_downscale_large_images()

    uploads: list[UploadItem] = []

    for uf in file:
        if not uf.content_type or not uf.content_type.lower().startswith("image/"):
            raise HTTPException(status_code=415, detail="Only image uploads are supported")

        size = 0
        sha_stream = hashlib.sha256()

        # Stream bytes into a temp file while tracking size and sha.
        tmp_path = upload_dir / f".tmp-{int(time.time() * 1000)}-{os.getpid()}.bin"
        try:
            with tmp_path.open("wb") as out:
                while True:
                    chunk = await uf.read(1024 * 1024)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > max_bytes:
                        out.close()
                        tmp_path.unlink(missing_ok=True)
                        raise HTTPException(status_code=413, detail=f"File too large (max {max_bytes} bytes)")
                    sha_stream.update(chunk)
                    out.write(chunk)
        finally:
            await uf.close()

        # Decode + normalize
        try:
            with Image.open(tmp_path) as im:
                fmt = im.format or "PNG"
                im = ImageOps.exif_transpose(im)

                if do_downscale:
                    im = _downscale_if_needed(im, max_dim)
                else:
                    w, h = im.size
                    if max(w, h) > max_dim:
                        raise HTTPException(status_code=413, detail=f"Image exceeds max dimension {max_dim}px")

                w, h = im.size
                ext = _guess_ext(fmt)
                # Encode to bytes (normalized output), then content-address with sha256
                Path(tmp_path).read_bytes()
                # Re-encode normalized output to ensure EXIF transpose/downscale applied
                import io

                bio = io.BytesIO()
                save_kwargs = {}
                if fmt.upper() == "JPEG":
                    save_kwargs["quality"] = 92
                    save_kwargs["optimize"] = True
                im.save(bio, format=fmt, **save_kwargs)
                normalized_bytes = bio.getvalue()

                sha_final = hashlib.sha256(normalized_bytes).hexdigest()
                image_id = sha_final  # content-addressed
                final_path = upload_dir / f"{image_id}{ext}"

                if not final_path.exists():
                    # Atomic write
                    tmp_out = final_path.with_suffix(final_path.suffix + ".tmp")
                    tmp_out.write_bytes(normalized_bytes)
                    os.replace(tmp_out, final_path)

                meta = {
                    "image_id": image_id,
                    "token": f"thomas-upload://{image_id}",
                    "filename": final_path.name,
                    "content_type": uf.content_type,
                    "size_bytes": final_path.stat().st_size,
                    "sha256": sha_final,
                    "width": w,
                    "height": h,
                    "format": fmt,
                    "created_at": time.time(),
                    "original_filename": uf.filename,
                    "sha256_raw_stream": sha_stream.hexdigest(),
                }
                _safe_json_dump(final_path.with_suffix(final_path.suffix + ".json"), meta)

                uploads.append(
                    UploadItem(
                        image_id=image_id,
                        token=meta["token"],
                        filename=meta["filename"],
                        content_type=meta["content_type"],
                        size_bytes=meta["size_bytes"],
                        sha256=sha_final,
                        width=w,
                        height=h,
                        format=fmt,
                    )
                )

        except HTTPException:
            raise
        except (OSError, FileNotFoundError):
            raise HTTPException(status_code=415, detail="Uploaded bytes are not a valid image")
        finally:
            tmp_path.unlink(missing_ok=True)

    return JSONResponse(UploadResponse(uploads=uploads).model_dump())


def resolve_upload_paths(image_ids: Sequence[str]) -> list[Path]:
    """Resolve image IDs to existing file paths under the upload dir.

    - Accepts either bare IDs or tokens like thomas-upload://<id>
    - Returns only existing image blobs (not metadata sidecars)
    """
    if not image_ids:
        return []

    upload_dir = get_upload_dir()
    out: list[Path] = []

    for raw in image_ids:
        image_id = (raw or "").replace("thomas-upload://", "").strip()
        if not image_id:
            continue

        # Prefer common formats first to avoid picking up a stray file.
        for ext in (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tiff", ".img"):
            p = upload_dir / f"{image_id}{ext}"
            if p.exists() and p.is_file():
                out.append(p)
                break

    return out
