"""The listening models Thomas can set up, one entry each. Adding a model is adding an entry here.

Every entry names the model's makers, its licence and the credit that licence asks for, where its files are published
(pinned to one revision, so the files cannot change under Thomas), and each file's size and SHA-256, so a download is
checked before it is ever used. ``roles`` says which file is which part of the model for sherpa-onnx, the speech engine
that runs it (``kind`` is sherpa-onnx's name for the model's shape). ``DEFAULT`` is the one Thomas offers to set up.

None of these files are in the Thomas repository: setting up downloads them from their makers onto your computer.
"""

from __future__ import annotations

from typing import Any

ENGINE = "sherpa-onnx==1.13.6"  # Apache-2.0; also pinned in pyproject.toml, so the installer puts it in already

MODELS: tuple[dict[str, Any], ...] = (
    {
        "id": "parakeet-tdt-0.6b-v3-int8",
        "label": "Parakeet v3, on this computer",
        "name": "NVIDIA Parakeet TDT 0.6B v3",
        "about": "Writes down what you say in 25 European languages, with punctuation, on this computer's processor.",
        "licence": "CC-BY-4.0",
        "credit": (
            "NVIDIA Parakeet TDT 0.6B v3 (CC-BY-4.0, huggingface.co/nvidia/parakeet-tdt-0.6b-v3), run with sherpa-onnx"
        ),
        "source": (
            "https://huggingface.co/csukuangfj/sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8/resolve/"
            "2bda32ec70b097a55adaa07d9a7173915b43cc78/"
        ),
        "kind": "nemo_transducer",
        "roles": {
            "encoder": "encoder.int8.onnx",
            "decoder": "decoder.int8.onnx",
            "joiner": "joiner.int8.onnx",
            "tokens": "tokens.txt",
        },
        "files": {
            "encoder.int8.onnx": (652184281, "acfc2b4456377e15d04f0243af540b7fe7c992f8d898d751cf134c3a55fd2247"),
            "decoder.int8.onnx": (11845275, "179e50c43d1a9de79c8a24149a2f9bac6eb5981823f2a2ed88d655b24248db4e"),
            "joiner.int8.onnx": (6355277, "3164c13fc2821009440d20fcb5fdc78bff28b4db2f8d0f0b329101719c0948b3"),
            "tokens.txt": (93939, "d58544679ea4bc6ac563d1f545eb7d474bd6cfa467f0a6e2c1dc1c7d37e3c35d"),
        },
    },
)
DEFAULT = MODELS[0]["id"]


def get(model_id: str | None = None) -> dict[str, Any]:
    """The entry for ``model_id``; '' or None or 'default' is DEFAULT. An id not listed raises ValueError."""
    wanted = DEFAULT if model_id in (None, "", "default") else model_id
    for entry in MODELS:
        if entry["id"] == wanted:
            return entry
    raise ValueError(f"Thomas has no listening model called {wanted}")


def size(entry: dict[str, Any]) -> int:
    """How many bytes setting the model up downloads, all its files together."""
    return sum(int(found[0]) for found in entry["files"].values())


__all__ = ["DEFAULT", "ENGINE", "MODELS", "get", "size"]
