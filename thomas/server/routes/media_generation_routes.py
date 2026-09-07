"""Configured image, music, and video generation lanes for the chat create menu."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import secrets
import subprocess
import threading
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

from aiohttp import web

from thomas.chat.conversation import ConversationManager
from thomas.core import task_bot_runtime
from thomas.server.app_keys import APP_SECRETS
from thomas.server.routes.chat_v2_announcements import _announcement_lock_for
from thomas.server.routes.chat_v2_keys import APP_SESSION_STORE
from thomas.server.routes.chat_v2_session_guard import session_turn_lock
from thomas.server.routes.deliverable_listing import _WORKSPACES_BASE

_MEDIA = {
    "image": {
        "model": "stabilityai/sd-turbo",
        "filename": "generated-image.png",
        "mime": "image/png",
    },
    "music": {
        "model": "facebook/musicgen-small",
        "filename": "generated-music.wav",
        "mime": "audio/wav",
    },
    "video": {
        "model": "damo-vilab/text-to-video-ms-1.7b",
        "filename": "generated-video.mp4",
        "mime": "video/mp4",
    },
}
_LOCAL_LOCK = threading.Lock()
_LOG = logging.getLogger(__name__)
MEDIA_START = web.AppKey("media_generation_start", Callable)
_VIDEO_MODEL = "damo-vilab/text-to-video-ms-1.7b"
_LOCAL_CACHE_PATTERNS = {
    "image": ["*.json", "*.txt", "*.model", "*.fp16.safetensors", "*.fp16.bin"],
    "music": ["*.json", "*.txt", "*.model", "*.safetensors", "*.bin"],
    "video": ["*.json", "*.txt", "*.model", "*.fp16.safetensors", "*.fp16.bin"],
}


def _read_config(path: Path) -> dict[str, str]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    return {name: str(value.get(name) or "") for name in _MEDIA} if isinstance(value, dict) else {}


def _write_config(path: Path, value: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temp.replace(path)


def _ensure_local_model(medium: str) -> None:
    """Ensure the exact model files consumed by the selected local pipeline exist."""
    from huggingface_hub import snapshot_download

    model = _MEDIA[medium]["model"]
    patterns = _LOCAL_CACHE_PATTERNS[medium]
    try:
        snapshot_download(repo_id=model, allow_patterns=patterns, local_files_only=True)
    except FileNotFoundError:
        snapshot_download(repo_id=model, allow_patterns=patterns)


def _local_model_ready(medium: str) -> bool:
    """Check only the files the worker consumes, without installing during a status GET."""
    model = _MEDIA[medium]["model"]
    try:
        from huggingface_hub import snapshot_download

        snapshot_download(
            repo_id=model,
            allow_patterns=_LOCAL_CACHE_PATTERNS[medium],
            local_files_only=True,
        )
    except (ImportError, FileNotFoundError, OSError, ValueError):
        return False
    return True


def _api_generate(medium: str, prompt: str, api_key: str, output: Path) -> None:
    spec = _MEDIA[medium]
    url = f"https://router.huggingface.co/hf-inference/models/{spec['model']}"
    body = json.dumps({"inputs": prompt, "options": {"wait_for_model": True}}).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=600) as response:  # noqa: S310 - fixed HTTPS provider
            payload = response.read()
            content_type = str(response.headers.get("Content-Type") or "")
    except urllib.error.HTTPError as exc:
        detail = exc.read(1000).decode("utf-8", errors="replace")
        raise RuntimeError(f"Hugging Face generation failed ({exc.code}): {detail}") from exc
    if "application/json" in content_type:
        try:
            decoded = json.loads(payload)
            encoded = decoded.get("data") or decoded.get("b64_json")
            payload = base64.b64decode(encoded) if encoded else b""
        except (ValueError, TypeError) as exc:
            raise RuntimeError("The API returned JSON instead of generated media.") from exc
    if not payload:
        raise RuntimeError("The API returned an empty result.")
    output.write_bytes(payload)


def _local_image(prompt: str, output: Path, progress: Callable[[int, str], None]) -> None:
    import torch
    from diffusers import AutoPipelineForText2Image

    progress(20, "Loading SD Turbo from the local Hugging Face cache")
    pipe = AutoPipelineForText2Image.from_pretrained(
        "stabilityai/sd-turbo", torch_dtype=torch.float16, variant="fp16", local_files_only=True
    ).to("cuda")
    progress(55, "Rendering 2 diffusion steps on the GPU")
    image = pipe(prompt=prompt, num_inference_steps=2, guidance_scale=0.0).images[0]
    image.save(output, format="PNG")
    del pipe
    torch.cuda.empty_cache()


def _local_music(prompt: str, output: Path, progress: Callable[[int, str], None]) -> None:
    import torch
    from scipy.io import wavfile
    from transformers import AutoProcessor, MusicgenForConditionalGeneration

    progress(15, "Loading MusicGen Small from the local Hugging Face cache")
    processor = AutoProcessor.from_pretrained("facebook/musicgen-small", local_files_only=True)
    model = MusicgenForConditionalGeneration.from_pretrained(
        "facebook/musicgen-small", torch_dtype=torch.float16, local_files_only=True
    ).to("cuda")
    inputs = processor(text=[prompt], padding=True, return_tensors="pt").to("cuda")
    progress(45, "Composing 256 audio tokens on the GPU")
    audio = model.generate(**inputs, max_new_tokens=256)[0, 0].detach().float().cpu().numpy()
    wavfile.write(output, int(model.config.audio_encoder.sampling_rate), audio)
    del model, processor
    torch.cuda.empty_cache()


def _local_video(prompt: str, output: Path, progress: Callable[[int, str], None]) -> None:
    import torch
    from diffusers import DiffusionPipeline
    from diffusers.utils import export_to_video

    progress(10, "Loading Text-to-Video 1.7B from the local Hugging Face cache")
    pipe = DiffusionPipeline.from_pretrained(
        _VIDEO_MODEL,
        torch_dtype=torch.float16,
        variant="fp16",
        local_files_only=True,
    ).to("cuda")
    progress(35, "Rendering 16 frames in 25 diffusion steps")
    frames = pipe(prompt, num_inference_steps=25, num_frames=16).frames[0]
    progress(90, "Encoding the clip at 8 fps")
    export_to_video(frames, str(output), fps=8)
    del pipe
    torch.cuda.empty_cache()


def _local_generate(medium: str, prompt: str, output: Path, progress: Callable[[int, str], None]) -> None:
    with _LOCAL_LOCK:
        {"image": _local_image, "music": _local_music, "video": _local_video}[medium](prompt, output, progress)


def _verify_media(medium: str, output: Path) -> None:
    """Decode the requested media before publishing a successful delivery."""
    if not output.is_file() or output.stat().st_size == 0:
        raise ValueError("The generator did not produce a media file.")
    if medium == "image":
        from PIL import Image

        with Image.open(output) as result:
            if result.format != "PNG":
                raise ValueError("The image generator did not produce PNG output.")
            result.verify()
        with Image.open(output) as result:
            result.load()
    elif medium == "music":
        from scipy.io import wavfile

        sample_rate, samples = wavfile.read(output)
        if sample_rate <= 0 or samples.size == 0:
            raise ValueError("The music generator produced no audio samples.")
    else:
        import imageio_ffmpeg

        result = subprocess.run(
            [
                imageio_ffmpeg.get_ffmpeg_exe(),
                "-v",
                "error",
                "-i",
                str(output),
                "-map",
                "0:v:0",
                "-frames:v",
                "1",
                "-f",
                "null",
                "-",
            ],
            capture_output=True,
            timeout=30,
            check=False,
        )
        if result.returncode:
            raise ValueError("The video generator did not produce a decodable video.")


async def start_media_generation(
    app: web.Application,
    *,
    medium: str,
    prompt: str,
    session_id: str,
    allow_network: bool = True,
) -> dict[str, Any]:
    """Execute a structured model choice through the same service as Create."""
    starter = app.get(MEDIA_START)
    if starter is None:
        raise RuntimeError("Media generation is unavailable in this server.")
    return await starter(medium, prompt, session_id, persist_user=False, allow_network=allow_network)


def _process_started_at() -> float:
    import psutil

    return psutil.Process().create_time()


def _owner_is_alive(owner: dict[str, Any]) -> bool | None:
    """Distinguish a dead worker from an inaccessible process or a reused PID."""
    import psutil

    if not owner.get("owner_pid") or not owner.get("owner_started_at"):
        return None
    try:
        process = psutil.Process(int(owner["owner_pid"]))
        return abs(process.create_time() - float(owner["owner_started_at"])) < 0.001
    except psutil.NoSuchProcess:
        return False
    except (psutil.AccessDenied, ValueError, TypeError):
        return None


def _recover_job(job_id: str, data_root: Path) -> dict[str, Any] | None:
    if not job_id.startswith("exec-") or not all(char.isalnum() or char in "-_" for char in job_id):
        return None
    record = task_bot_runtime.get_execution(job_id, data_root)
    if not record or record.get("backend_type") != "media_generation":
        return None
    medium = str(record.get("intent") or record.get("execution_intent") or "").removeprefix("media_")
    if medium not in _MEDIA:
        return None
    state = str(record.get("state") or "")
    job = {
        "id": job_id,
        "medium": medium,
        "session_id": record.get("conversation_id", ""),
        "progress_text": record.get("progress_summary", ""),
        "state": state,
    }
    if state in {"completed", "verified"}:
        proof = record.get("proof") or {}
        filename = _MEDIA[medium]["filename"]
        if record.get("proof_status") != "verified" or not any(
            artifact.get("path") == filename for artifact in proof.get("artifacts", []) if isinstance(artifact, dict)
        ):
            return dict(job, state="unknown", error="The saved media job has no verified delivery receipt.")
        try:
            _verify_media(medium, _WORKSPACES_BASE / job_id / filename)
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError):
            return dict(job, state="unknown", error="The saved media file is unavailable or invalid.")
        return dict(
            job,
            state="completed",
            progress=100,
            deliverable={
                "name": filename,
                "kind": medium,
                "mime": _MEDIA[medium]["mime"],
                "url": f"/deliverable/{job_id}/{filename}",
            },
        )
    if state in {"failed", "cancelled", "abandoned"}:
        return dict(job, state="cancelled" if state == "abandoned" else state, error=record.get("blocker", ""))
    owner = (record.get("runtime_profile") or {}).get("media") or {}
    alive = _owner_is_alive(owner)
    if alive is False:
        reason = "The media worker exited before delivering a verified result."
        task_bot_runtime.update_execution(
            job_id, state="failed", blocker=reason, progress_summary=reason, repo_root=data_root, force=True
        )
        return dict(job, state="failed", error=reason, progress_text=reason)
    if alive is None:
        return dict(job, state="unknown", error="The saved job does not identify an observable worker.")
    return dict(job, state="running")


def setup_media_generation_routes(
    app: web.Application,
    *,
    data_root: Path,
    require_api_access: Callable[[web.Request], Any] | None = None,
) -> None:
    guard = require_api_access or (lambda _request: None)
    config_path = Path(data_root) / ".thomas" / "media_lanes.json"
    jobs: dict[str, dict[str, Any]] = {}
    tasks: set[asyncio.Task[Any]] = set()

    async def persist_media_message(
        session_id: str,
        role: str,
        content: str,
        *,
        artifact: dict[str, Any] | None = None,
    ) -> None:
        """Append media UI state to the durable conversation shown after reload."""
        if not session_id or APP_SESSION_STORE not in app:
            return
        store = app[APP_SESSION_STORE]
        # Use the same lock order as foreground turns: turn ownership, then
        # the shared conversation/announcement lock. Atomic file replacement
        # alone cannot protect a load/append/save from a stale turn snapshot.
        turn_lock = await session_turn_lock(app, session_id)
        if turn_lock is None:
            raise web.HTTPServiceUnavailable(reason="Chat persistence is not ready. Please retry.")
        async with turn_lock:
            async with _announcement_lock_for(app, session_id):
                conversation = await store.load(session_id) or ConversationManager()
                metadata = {"media_artifact": artifact} if artifact else {"media_request": True}
                updated = conversation.append_message(role, content, metadata=metadata)
                meta = await store.load_meta(session_id)
                if not await store.save(session_id, updated, meta, force=True):
                    raise web.HTTPServiceUnavailable(reason="The media request could not be saved. Please retry.")

    def lane_status() -> dict[str, dict[str, Any]]:
        config = _read_config(config_path)
        secrets = app[APP_SECRETS]
        lanes = {}
        for medium, spec in _MEDIA.items():
            provider = config.get(medium) or ""
            lanes[medium] = {
                "provider": provider,
                "configured": (provider == "local" and _local_model_ready(medium))
                or (provider == "api" and bool(secrets.get(f"media_{medium}_api"))),
                "model": spec["model"],
            }
        return lanes

    async def get_lanes(request: web.Request) -> web.Response:
        guard(request)
        return web.json_response({"lanes": await asyncio.to_thread(lane_status)})

    async def set_lane(request: web.Request) -> web.Response:
        guard(request)
        payload = await request.json()
        medium = str(request.match_info.get("medium") or payload.get("medium") or "").lower()
        provider = str(payload.get("provider") or "").lower()
        if medium not in _MEDIA or provider not in {"api", "local"}:
            return web.json_response(
                {"ok": False, "error": "Choose image, video, or music and API or local."},
                status=400,
            )
        if provider == "api":
            api_key = str(payload.get("api_key") or "").strip()
            if not api_key:
                return web.json_response({"ok": False, "error": "An API key is required."}, status=400)
            app[APP_SECRETS].set(f"media_{medium}_api", api_key, persist=True)
        else:
            await asyncio.to_thread(_ensure_local_model, medium)
        config = _read_config(config_path)
        config[medium] = provider
        _write_config(config_path, config)
        return web.json_response({"ok": True, "lane": (await asyncio.to_thread(lane_status))[medium]})

    async def run_job(job_id: str, medium: str, prompt: str, provider: str, output: Path) -> None:
        job = jobs[job_id]
        worker: asyncio.Task[None] | None = None

        def progress(percent: int, message: str) -> None:
            job.update(progress=percent, progress_text=message)

        try:
            progress(5, "Starting the background worker")
            output.parent.mkdir(parents=True, exist_ok=True)
            if provider == "local":
                worker = asyncio.create_task(asyncio.to_thread(_local_generate, medium, prompt, output, progress))
            else:
                progress(20, "Sending the prompt to Hugging Face")
                key = app[APP_SECRETS].get(f"media_{medium}_api") or ""
                worker = asyncio.create_task(asyncio.to_thread(_api_generate, medium, prompt, key, output))
            await asyncio.shield(worker)
            await asyncio.to_thread(_verify_media, medium, output)
            current = task_bot_runtime.get_execution(job_id, data_root) or {}
            if current.get("cancel_requested") or current.get("state") in {"cancelled", "abandoned"}:
                raise asyncio.CancelledError
            progress(95, "Adding the result to this conversation and Library")
            artifact = {
                "name": output.name,
                "kind": medium,
                "mime": _MEDIA[medium]["mime"],
                "url": f"/deliverable/{job_id}/{output.name}",
            }
            # Chat's existing completion announcer owns durable result messages.
            # The terminal execution is its receipt; a second writer here races
            # the live chat turn and can announce success before proof commits.
            task_bot_runtime.attach_proof(
                job_id,
                artifacts=[{"path": output.name, "kind": medium}],
                summary=f"Created {medium}: {prompt}",
                status="verified",
                actor="media-worker",
                repo_root=data_root,
            )
            task_bot_runtime.mark_verified(
                job_id,
                actor="media-worker",
                summary=f"Created {medium}: {prompt}",
                repo_root=data_root,
            )
            job.update(
                state="completed",
                progress=100,
                progress_text="Ready in this conversation and Library",
                deliverable=artifact,
            )
        except asyncio.CancelledError:
            job.update(state="cancelling", progress_text="Waiting for the media worker to stop")
            if worker is not None:
                await asyncio.gather(worker, return_exceptions=True)
            task_bot_runtime.update_execution(
                job_id,
                state="cancelled",
                blocker="Media worker stopped before delivery.",
                progress_summary="Media generation interrupted",
                actor="media-worker",
                force=True,
                repo_root=data_root,
            )
            job.update(state="cancelled", progress_text="Media generation interrupted")
            raise
        except Exception as exc:
            # Broad catch: a background worker must record any provider or model failure.
            _LOG.exception("%s generation failed in the background worker", medium.title())
            task_bot_runtime.update_execution(
                job_id,
                state="failed",
                blocker=str(exc),
                progress_summary=f"{medium.title()} generation failed",
                force=True,
                repo_root=data_root,
            )
            job.update(state="failed", progress_text=str(exc), error=str(exc))

    async def start_job(
        medium: str,
        prompt: str,
        session_id: str,
        *,
        persist_user: bool = True,
        user_message: str = "",
        allow_network: bool = True,
    ) -> dict[str, Any]:
        status = (await asyncio.to_thread(lane_status)).get(medium)
        if not status or not prompt.strip():
            raise web.HTTPBadRequest(reason="A valid medium and prompt are required.")
        if not status["configured"]:
            raise web.HTTPConflict(reason=f"No {medium} lane is set up yet.")
        if status["provider"] == "api" and not allow_network:
            raise PermissionError("The configured media provider requires network access.")
        if persist_user:
            await persist_media_message(session_id, "user", user_message or f"Create {medium}: {prompt}")
        record = task_bot_runtime.create_execution(
            session_id=session_id,
            summary=f"Create {medium}: {prompt}",
            task_id=f"media-{medium}-{secrets.token_hex(6)}",
            intent=f"media_{medium}",
            scope=[_MEDIA[medium]["filename"]],
            visibility="user",
            backend_type="media_generation",
            runtime_profile={
                "media": {
                    "provider": status["provider"],
                    "model": _MEDIA[medium]["model"],
                    "owner_pid": os.getpid(),
                    "owner_started_at": _process_started_at(),
                }
            },
            actor="media-menu",
            repo_root=data_root,
        )
        job_id = str(record["execution_id"])
        try:
            workspace = _WORKSPACES_BASE / job_id
            workspace.mkdir(parents=True, exist_ok=True)
            output = workspace / _MEDIA[medium]["filename"]
            task_bot_runtime.update_execution(
                job_id,
                state="executing",
                progress_summary=f"Creating {medium} in the background",
                actor="media-worker",
                force=True,
                repo_root=data_root,
            )
            jobs[job_id] = {
                "id": job_id,
                "medium": medium,
                "provider": status["provider"],
                "state": "running",
                "progress": 0,
                "progress_text": "Queued",
                "session_id": session_id,
            }
            task = asyncio.create_task(run_job(job_id, medium, prompt, str(status["provider"]), output))
            tasks.add(task)
            task.add_done_callback(tasks.discard)
            return {"ok": True, "job_id": job_id, "job": jobs[job_id], "execution": dict(record, state="executing")}
        except Exception:
            _LOG.exception("Media worker could not be started after execution creation")
            task_bot_runtime.update_execution(
                job_id,
                state="failed",
                blocker="Media worker could not start.",
                progress_summary="Media generation failed to start",
                repo_root=data_root,
                force=True,
            )
            if job_id in jobs:
                jobs[job_id].update(state="failed", error="Media worker could not start.")
            raise

    app[MEDIA_START] = start_job

    async def stop_workers(_app: web.Application) -> None:
        pending = list(tasks)
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)

    app.on_cleanup.append(stop_workers)

    async def generate(request: web.Request) -> web.Response:
        try:
            guard(request)
            payload = await request.json()
            result = await start_job(
                str(payload.get("medium") or "").lower(),
                str(payload.get("prompt") or "").strip(),
                str(payload.get("session_id") or ""),
                user_message=str(payload.get("user_message") or "").strip(),
            )
            return web.json_response(result, status=202)
        except web.HTTPException as exc:
            return web.json_response(
                {"ok": False, "error": exc.reason or "Media generation request failed."},
                status=exc.status,
            )
        except Exception as exc:
            # Broad catch: this HTTP boundary must convert all startup failures into JSON for chat.
            _LOG.exception("Media generation request failed before the background job started")
            return web.json_response(
                {"ok": False, "error": str(exc) or "Media generation could not start."},
                status=500,
            )

    async def get_job(request: web.Request) -> web.Response:
        guard(request)
        job_id = str(request.match_info.get("job_id") or "")
        job = jobs.get(job_id)
        if job is None:
            job = await asyncio.to_thread(_recover_job, job_id, data_root)
        if not job:
            raise web.HTTPNotFound(text="Media job not found")
        return web.json_response({"job": job})

    app.router.add_get("/api/media/lanes", get_lanes)
    app.router.add_put("/api/media/lanes/{medium}", set_lane)
    app.router.add_post("/api/media/generate", generate)
    app.router.add_get("/api/media/jobs/{job_id}", get_job)


__all__ = ["setup_media_generation_routes"]
