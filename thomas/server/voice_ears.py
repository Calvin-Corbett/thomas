"""Thomas's own ears: live listening on this computer, with no other program to run and nothing to accept.

Voice Studio would only listen live after a licence click, and that click is its own rule: it asks for one on every
model it has not marked commercial (its services/model_acceptance.py calls the gate "a local, honest-acknowledgement
gate"). The model it wanted, NVIDIA Parakeet TDT 0.6B v3, is CC-BY-4.0: anyone may use it, commercially too, giving
credit (CREDIT below). Thomas runs that model itself with sherpa-onnx (Apache-2.0). On this computer's processor,
2026-11-06: 4 s to load once, then 3.8 s of speech written down in 0.42 s, with punctuation, in 25 European languages.

The page sends 16 kHz 16-bit mono sound in small frames, exactly as for Voice Studio's live stream, and gets the same
events back: ``{"type": "partial", "text"}`` while you speak and ``{"type": "final", "final_kind": "utterance", "text"}``
each time you pause. Where speech starts and stops is found from its loudness against the room's own quiet (Segmenter);
the browser's echo cancelling keeps Thomas's own voice out.

Which models Thomas can use, and the default, are in voice_ears_models; voice_ears_setup puts one on this
computer. The model loads on the first live talk and stays loaded in this process, so later talks start at once.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Any

from thomas.server import voice_ears_models

if TYPE_CHECKING:  # numpy costs ~0.4 s to import; the Segmenter loads it when a live talk starts, not at boot
    import numpy as np

_DEFAULT = voice_ears_models.get()
MODEL_NAME = _DEFAULT["id"]  # the default model; the others are listed in voice_ears_models
LABEL = _DEFAULT["label"]
CREDIT = _DEFAULT["credit"]
FILES = tuple(_DEFAULT["files"])
RATE = 16000


def model_dir(settings_path: Path, model_id: str | None = None) -> Path:
    """Where Thomas keeps a listening model: beside his voice settings, one folder per model."""
    return Path(settings_path).parent / "models" / voice_ears_models.get(model_id)["id"]


# Thomas's install folder (the checkout this code runs from) has its own .thomas, which git leaves alone. The caged
# server's data folder is in its own Windows account, where nobody else can put a model; its install folder is shared.
INSTALL_DIR = Path(__file__).resolve().parents[2] / ".thomas" / "models" / MODEL_NAME


def find_model(settings_path: Path, model_id: str | None = None) -> Path:
    """The first folder that holds the whole model: beside the voice settings, then in the install folder.

    When neither does, the folder beside the voice settings, which is where setting it up puts it.
    """
    entry = voice_ears_models.get(model_id)
    for folder in (model_dir(settings_path, entry["id"]), INSTALL_DIR.parent / entry["id"]):
        if all((folder / name).is_file() for name in entry["files"]):
            return folder
    return model_dir(settings_path, entry["id"])


def why_not(folder: Path, model_id: str | None = None) -> str:
    """'' when Thomas can listen live by himself, otherwise why he cannot, in words to show."""
    if importlib.util.find_spec("sherpa_onnx") is None:
        return "Thomas's speech engine (sherpa-onnx) is not installed in his Python"
    missing = [name for name in voice_ears_models.get(model_id)["files"] if not (Path(folder) / name).is_file()]
    if missing:
        return f"Thomas's listening model is not in {folder} (missing {', '.join(missing)})"
    return ""


_loaded: dict[str, tuple[Any, threading.Lock]] = {}
_loading = threading.Lock()


def recognizer(folder: Path, model_id: str | None = None) -> tuple[Any, threading.Lock]:
    """The loaded model in ``folder`` and the lock its decoding takes; loads it the first time (about 4 s)."""
    entry = voice_ears_models.get(model_id)
    key = str(Path(folder).resolve())
    with _loading:
        if key not in _loaded:
            import sherpa_onnx

            if entry["kind"] not in ("nemo_transducer", "transducer"):
                raise ValueError(f"Thomas cannot run a {entry['kind']} model yet")
            roles = {role: str(Path(folder) / name) for role, name in entry["roles"].items()}
            model = sherpa_onnx.OfflineRecognizer.from_transducer(
                **roles, num_threads=4, model_type=entry["kind"], provider="cpu"
            )
            _loaded[key] = (model, threading.Lock())
        return _loaded[key]


def transcribe(loaded: tuple[Any, threading.Lock], samples: np.ndarray) -> str:
    """The words in ``samples`` (float32 at RATE). Blocking: run it off the event loop."""
    model, lock = loaded
    with lock:
        stream = model.create_stream()
        stream.accept_waveform(RATE, samples)
        model.decode_stream(stream)
        return str(stream.result.text or "").strip()


class Segmenter:
    """Cuts a live microphone into what you said between pauses, from loudness alone.

    Each 100 ms block is speech when it is clearly louder than the room's quiet, which is learned from the quiet blocks
    as they come. A pause of PAUSE_BLOCKS quiet blocks ends what was said; a little sound from just before the first loud
    block is kept so the first word is whole. ``feed`` returns ("partial", samples) about every PARTIAL_BLOCKS of
    speech, so the words can show while you talk, and ("final", samples) at each pause.
    """

    BLOCK = RATE // 10
    PAUSE_BLOCKS = 7  # 700 ms of quiet ends a turn
    LEAD_BLOCKS = 3  # 300 ms kept from before the first loud block
    MIN_BLOCKS = 3  # anything shorter than 300 ms is a click, not speech
    PARTIAL_BLOCKS = 8  # show the words so far about every 800 ms
    MAX_BLOCKS = 250  # 25 s: say it is finished even without a pause
    PARTIAL_LIMIT = 120  # past 12 s only the final is written, so partials stay quick
    FLOOR_START = 0.003
    LOUDER = 3.0
    MIN_LOUD = 0.006

    def __init__(self) -> None:
        import numpy as np

        self._pending = np.zeros(0, dtype=np.float32)
        self._floor = self.FLOOR_START
        self._lead: list[np.ndarray] = []
        self._said: list[np.ndarray] = []
        self._loud = 0
        self._quiet = 0
        self._since_partial = 0

    def feed(self, pcm: bytes) -> list[tuple[str, np.ndarray]]:
        """Take raw 16-bit little-endian sound; return what is ready to be written down."""
        import numpy as np

        usable = len(pcm) - len(pcm) % 2
        fresh = np.frombuffer(pcm[:usable], dtype="<i2").astype(np.float32) / 32768.0
        self._pending = np.concatenate([self._pending, fresh])
        out: list[tuple[str, np.ndarray]] = []
        while len(self._pending) >= self.BLOCK:
            block, self._pending = self._pending[: self.BLOCK], self._pending[self.BLOCK :]
            out.extend(self._block(block))
        return out

    def flush(self) -> list[tuple[str, np.ndarray]]:
        """The microphone stopped: whatever was being said is finished."""
        return self._finish()

    def _block(self, block: np.ndarray) -> list[tuple[str, np.ndarray]]:
        import numpy as np

        loudness = float(np.sqrt(np.mean(block * block)))
        loud = loudness > max(self.MIN_LOUD, self._floor * self.LOUDER)
        if not self._said:
            if not loud:
                self._floor = 0.95 * self._floor + 0.05 * loudness
                self._lead = (self._lead + [block])[-self.LEAD_BLOCKS :]
                return []
            self._said, self._lead = [*self._lead, block], []
            self._loud, self._quiet, self._since_partial = 1, 0, 1
            return []
        self._said.append(block)
        self._since_partial += 1
        if loud:
            self._loud += 1
            self._quiet = 0
        else:
            self._quiet += 1
        if self._quiet >= self.PAUSE_BLOCKS or len(self._said) >= self.MAX_BLOCKS:
            return self._finish()
        if loud and self._since_partial >= self.PARTIAL_BLOCKS and len(self._said) <= self.PARTIAL_LIMIT:
            self._since_partial = 0
            return [("partial", np.concatenate(self._said))]
        return []

    def _finish(self) -> list[tuple[str, np.ndarray]]:
        import numpy as np

        said, loud = self._said, self._loud
        self._said, self._loud, self._quiet, self._since_partial = [], 0, 0, 0
        if not said or loud < self.MIN_BLOCKS:
            return []
        return [("final", np.concatenate(said))]


async def serve(page: Any, folder: Path, model_id: str | None = None) -> None:
    """Listen to the page's microphone over its websocket and send the words back, until the page stops."""
    from aiohttp import WSMsgType

    loaded = await asyncio.to_thread(recognizer, folder, model_id)
    await page.send_json({"type": "live.started", "model": voice_ears_models.get(model_id)["label"]})
    cut = Segmenter()
    async for message in page:
        ending = False
        if message.type == WSMsgType.BINARY:
            ready = cut.feed(message.data)
        elif message.type == WSMsgType.TEXT:
            try:
                ending = (json.loads(message.data) or {}).get("type") == "input_audio.end"
            except (ValueError, AttributeError):
                ending = False
            ready = cut.flush() if ending else []
        else:
            break
        for kind, samples in ready:
            text = await asyncio.to_thread(transcribe, loaded, samples)
            if text:
                event = {"type": kind, "text": text}
                if kind == "final":
                    event["final_kind"] = "utterance"
                await page.send_json(event)
        if ending:
            break


__all__ = ["CREDIT", "LABEL", "MODEL_NAME", "Segmenter", "model_dir", "serve", "transcribe", "why_not"]
