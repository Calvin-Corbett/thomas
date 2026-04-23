import json
import wave
from pathlib import Path

import pytest

from thomas.cli.commands.messages import p071_message_voice_metadata_stub as cli
from thomas.messages.p071_message_voice_metadata_stub import (
    InvalidVoiceMetadataRequestError,
    MissingVoiceMetadataConfigError,
    VoiceMetadataExternalFailureError,
    VoiceMetadataStubRequest,
    create_voice_metadata_stub,
)


def _write_wav(path: Path, *, seconds: float = 1.0, sample_rate: int = 8000) -> None:
    frames = int(seconds * sample_rate)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)  # 16-bit PCM
        wf.setframerate(sample_rate)
        wf.writeframes(b"\x00\x00" * frames)


def test_voice_metadata_stub_success_with_wav(tmp_path: Path) -> None:
    wav_path = tmp_path / "sample.wav"
    _write_wav(wav_path, seconds=1.0, sample_rate=8000)

    req = VoiceMetadataStubRequest(message_id="msg-123", audio_path=str(wav_path))
    res = create_voice_metadata_stub(req)

    d = res.to_dict()
    assert d["schema_version"] == 1
    assert d["message_id"] == "msg-123"
    assert d["is_stub"] is False
    assert d["source"]["kind"] == "file"
    assert d["source"]["inspection_mode"] == "file_best_effort"
    assert d["metadata"]["size_bytes"] is not None
    assert d["metadata"]["sha256"] is not None
    assert d["metadata"]["container"] == "wav"
    assert d["metadata"]["sample_rate_hz"] == 8000
    assert d["metadata"]["channels"] == 1
    assert d["metadata"]["duration_ms"] == 1000


def test_voice_metadata_stub_no_source_is_ok_stub() -> None:
    req = VoiceMetadataStubRequest(message_id="m")
    res = create_voice_metadata_stub(req)
    d = res.to_dict()
    assert d["ok"] is False if "ok" in d else True  # defensive; core result has no ok field
    assert d["is_stub"] is True
    assert d["warnings"] == ["no_audio_source"]
    assert d["source"]["kind"] == "none"


def test_voice_metadata_stub_invalid_message_id() -> None:
    req = VoiceMetadataStubRequest(message_id="")
    with pytest.raises(InvalidVoiceMetadataRequestError) as ei:
        create_voice_metadata_stub(req)
    assert ei.value.code == "invalid_request"


def test_voice_metadata_stub_both_sources_invalid() -> None:
    req = VoiceMetadataStubRequest(message_id="m", audio_path="a.wav", audio_url="https://example.com/a.wav")
    with pytest.raises(InvalidVoiceMetadataRequestError) as ei:
        create_voice_metadata_stub(req)
    assert ei.value.code == "invalid_request"


def test_voice_metadata_stub_missing_file(tmp_path: Path) -> None:
    missing = tmp_path / "nope.wav"
    req = VoiceMetadataStubRequest(message_id="m", audio_path=str(missing))
    with pytest.raises(VoiceMetadataExternalFailureError) as ei:
        create_voice_metadata_stub(req)
    assert ei.value.code == "external_failure"
    assert "audio_path" in ei.value.details


def test_voice_metadata_stub_audio_url_requires_config() -> None:
    req = VoiceMetadataStubRequest(message_id="m", audio_url="https://example.com/a.wav")
    with pytest.raises(MissingVoiceMetadataConfigError) as ei:
        create_voice_metadata_stub(req, config=None)
    assert ei.value.code == "missing_config"


def test_voice_metadata_stub_audio_url_disabled_by_policy() -> None:
    req = VoiceMetadataStubRequest(message_id="m", audio_url="https://example.com/a.wav")
    with pytest.raises(MissingVoiceMetadataConfigError) as ei:
        create_voice_metadata_stub(req, config={"voice_metadata_allow_urls": False})
    assert ei.value.code == "missing_config"


def test_voice_metadata_stub_audio_url_allowed_records_only() -> None:
    req = VoiceMetadataStubRequest(message_id="m", audio_url="https://example.com/a.wav")
    res = create_voice_metadata_stub(req, config={"voice_metadata_allow_urls": True})
    d = res.to_dict()
    assert d["source"]["kind"] == "url"
    assert d["source"]["inspection_mode"] == "url_record_only"
    assert d["is_stub"] is True
    assert "url_source_not_fetched" in d["warnings"]
    assert d["metadata"]["sha256"] is None


def test_cli_json_success(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    wav_path = tmp_path / "sample.wav"
    _write_wav(wav_path, seconds=0.5, sample_rate=8000)

    exit_code = cli.main(["--message-id", "m1", "--audio-path", str(wav_path), "--json"])
    assert exit_code == 0

    out = capsys.readouterr().out.strip()
    payload = json.loads(out)
    assert payload["ok"] is True
    assert payload["result"]["message_id"] == "m1"


def test_cli_json_failure(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = cli.main(["--message-id", "", "--json"])
    assert exit_code == 2

    out = capsys.readouterr().out.strip()
    payload = json.loads(out)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "invalid_request"


def test_cli_json_url_allowed_with_flag(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = cli.main(
        [
            "--message-id",
            "m-url",
            "--audio-url",
            "https://example.com/a.wav",
            "--allow-urls",
            "--json",
        ]
    )
    assert exit_code == 0

    out = capsys.readouterr().out.strip()
    payload = json.loads(out)
    assert payload["ok"] is True
    assert payload["result"]["source"]["kind"] == "url"
    assert payload["result"]["is_stub"] is True
