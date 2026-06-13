"""Tests for the bounded local-Ollama auto-start helper."""

from __future__ import annotations

import pytest

from thomas.core import ollama_autostart


class TestIsLocalOllamaUrl:
    def test_default_local_url(self):
        assert ollama_autostart.is_local_ollama_url("http://localhost:11434/v1")
        assert ollama_autostart.is_local_ollama_url("http://127.0.0.1:11434")

    def test_remote_or_other_port_rejected(self):
        assert not ollama_autostart.is_local_ollama_url("https://api.openai.com/v1")
        assert not ollama_autostart.is_local_ollama_url("http://localhost:8899")
        assert not ollama_autostart.is_local_ollama_url("http://192.168.1.5:11434")

    def test_garbage_rejected(self):
        assert not ollama_autostart.is_local_ollama_url("")
        assert not ollama_autostart.is_local_ollama_url(None)
        assert not ollama_autostart.is_local_ollama_url("not a url")


class TestMaybeAutostart:
    @pytest.fixture(autouse=True)
    def _reset_cooldown(self):
        ollama_autostart._LAST_ATTEMPT_TS = 0.0
        yield
        ollama_autostart._LAST_ATTEMPT_TS = 0.0

    def test_opt_out_env(self, monkeypatch):
        monkeypatch.setenv("THOMAS_OLLAMA_AUTOSTART", "0")
        assert not ollama_autostart.maybe_autostart_ollama("http://localhost:11434/v1")

    def test_non_local_url_never_spawns(self, monkeypatch):
        spawned = []
        monkeypatch.setattr(ollama_autostart.subprocess, "Popen", lambda *a, **k: spawned.append(a))
        assert not ollama_autostart.maybe_autostart_ollama("https://api.example.com/v1")
        assert spawned == []

    def test_spawns_once_then_cooldown(self, monkeypatch):
        spawned = []
        monkeypatch.setattr(ollama_autostart, "_find_ollama_binary", lambda: "/fake/ollama")
        monkeypatch.setattr(ollama_autostart.subprocess, "Popen", lambda cmd, **k: spawned.append(cmd))
        assert ollama_autostart.maybe_autostart_ollama("http://localhost:11434/v1")
        assert not ollama_autostart.maybe_autostart_ollama("http://localhost:11434/v1")
        assert len(spawned) == 1
        assert spawned[0][1] == "serve"

    def test_no_binary_no_spawn(self, monkeypatch):
        monkeypatch.setattr(ollama_autostart, "_find_ollama_binary", lambda: None)
        assert not ollama_autostart.maybe_autostart_ollama("http://localhost:11434/v1")

    def test_popen_failure_swallowed(self, monkeypatch):
        def _boom(*a, **k):
            raise OSError("nope")

        monkeypatch.setattr(ollama_autostart, "_find_ollama_binary", lambda: "/fake/ollama")
        monkeypatch.setattr(ollama_autostart.subprocess, "Popen", _boom)
        assert not ollama_autostart.maybe_autostart_ollama("http://localhost:11434/v1")
