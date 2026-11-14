"""Thomas uses what this computer has: a 16 GB PC still works, a 64 GB PC gets most of its 64.

You said: "it needs to work on 16 GB of RAM. But at the same time, like, it needs to also dynamically be more.
I have 64, so you can do a lot more on mine ... it should automatically be set to [the] computer's RAM."

Regression for thomas.core.machine_capacity's reserve (a quarter, at least 4 GiB, at most 8 GiB), for the free
commit it reads on Windows, and for numpy no longer coming into every Thomas process through thomas.server.app
(its math library set aside ~480 MB per process; thomas.memory.embedder._numpy).
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from thomas.core import machine_capacity as mc
from thomas.server.precard import pool
from thomas.server.proof.environment import sandbox_env

GIB = 1024**3
REPO = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    ("total_gib", "reserve_gib"),
    [(8, 4), (16, 4), (24, 6), (32, 8), (64, 8), (128, 8)],
)
def test_the_reserve_is_a_quarter_between_4_and_8_gib(total_gib: int, reserve_gib: int) -> None:
    assert mc._reserve_bytes(total_gib * GIB) == reserve_gib * GIB


def test_a_64_gib_pc_gets_56_gib_and_a_16_gib_pc_keeps_12() -> None:
    assert mc.usable_memory_bytes(64 * GIB, None) == 56 * GIB
    assert mc.usable_memory_bytes(16 * GIB, None) == 12 * GIB
    assert mc.usable_memory_bytes(64 * GIB, 20 * GIB) == 20 * GIB, "what is free right now still bounds it"


def test_more_memory_means_more_room_until_the_cpus_are_the_limit() -> None:
    sizes = [mc.estimate(cpus=64, total_ram_bytes=gib * GIB, run_budget_mb=1600) for gib in (16, 32, 64, 128)]
    assert sizes == sorted(sizes) and sizes[0] < sizes[-1]
    assert mc.estimate(cpus=16, total_ram_bytes=64 * GIB, run_budget_mb=1600) == 32, "64 GiB: the 16 CPUs bind"
    assert pool.size(cpus=64, total_ram_bytes=64 * GIB, shard_mb=1024) == 56
    assert pool.size(cpus=64, total_ram_bytes=16 * GIB, shard_mb=1024) == 12


@pytest.mark.skipif(os.name != "nt", reason="free commit is a Windows reading")
def test_free_memory_on_windows_never_exceeds_free_commit() -> None:
    measured = mc._windows_memory()
    assert measured is not None
    total, available = measured
    assert 0 < available <= total
    _total, combined = mc._memory()
    assert combined is not None and combined <= available + 256 * 1024**2, "psutil's reading is bounded by commit too"


def test_the_server_starts_without_numpy() -> None:
    probe = "import sys, thomas.server.app; print('numpy' in sys.modules)"
    env = {**os.environ, "PYTHONPATH": str(REPO)}
    done = subprocess.run(
        [sys.executable, "-c", probe], cwd=str(REPO), env=env, capture_output=True, text=True, timeout=300, check=False
    )
    assert done.returncode == 0, done.stderr[-2000:]
    assert done.stdout.strip().splitlines()[-1] == "False", "numpy came back into every Thomas process"


def test_dense_vectors_still_round_trip() -> None:
    np = pytest.importorskip("numpy")
    from thomas.memory.embedder import bytes_to_dense, cosine_similarity_dense, dense_to_bytes
    from thomas.memory.rerank import CandidateFeatures, Tier2Reranker

    vec = np.array([0.6, 0.8], dtype=np.float64)
    back = bytes_to_dense(dense_to_bytes(vec))
    assert back.dtype == np.float32 and np.allclose(back, vec)
    assert np.allclose(cosine_similarity_dense(back, np.stack([back, -back])), [1.0, -1.0])
    candidate = CandidateFeatures(event_id=1)
    Tier2Reranker().score([candidate], back, {1: back}, weight=1.0)
    assert candidate.dense_score == pytest.approx(1.0) and candidate.final_score == pytest.approx(1.0)


def test_check_shards_run_numpy_on_one_math_thread(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENBLAS_NUM_THREADS", raising=False)
    assert sandbox_env(tmp_path, tmp_path)["OPENBLAS_NUM_THREADS"] == "1"
    monkeypatch.setenv("OPENBLAS_NUM_THREADS", "4")
    assert sandbox_env(tmp_path, tmp_path)["OPENBLAS_NUM_THREADS"] == "4", "a value you set yourself wins"
