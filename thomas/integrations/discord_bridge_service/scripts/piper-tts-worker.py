import argparse
import json
import sys
import wave
from pathlib import Path

from piper import PiperVoice, SynthesisConfig
from piper.download_voices import download_voice


def emit(message: dict) -> None:
    print(json.dumps(message, ensure_ascii=False), flush=True)


def ensure_voice(model_name: str, download_dir: Path) -> Path:
    model_path = download_dir / f"{model_name}.onnx"
    config_path = download_dir / f"{model_name}.onnx.json"
    if model_path.exists() and config_path.exists():
        return model_path

    download_dir.mkdir(parents=True, exist_ok=True)
    download_voice(model_name, download_dir)
    return model_path


def write_synthesized_wav(
    voice: PiperVoice, text: str, wav_file: wave.Wave_write, syn_config: SynthesisConfig, sentence_pause_ms: int
) -> None:
    first_chunk = True
    silence_bytes = b""
    wrote_audio = False

    for audio_chunk in voice.synthesize(text, syn_config=syn_config):
        if first_chunk:
            wav_file.setframerate(audio_chunk.sample_rate)
            wav_file.setsampwidth(audio_chunk.sample_width)
            wav_file.setnchannels(audio_chunk.sample_channels)
            if sentence_pause_ms > 0:
                silence_samples = int(audio_chunk.sample_rate * (sentence_pause_ms / 1000))
                silence_bytes = b"\x00" * (silence_samples * audio_chunk.sample_width * audio_chunk.sample_channels)
            first_chunk = False

        if wrote_audio and silence_bytes:
            wav_file.writeframes(silence_bytes)

        wav_file.writeframes(audio_chunk.audio_int16_bytes)
        wrote_audio = True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    parser.add_argument("--data-dir", dest="data_dir", required=True)
    parser.add_argument("--cuda", action="store_true")
    parser.add_argument("--speaker", dest="speaker", type=int)
    parser.add_argument("--sentence-pause-ms", dest="sentence_pause_ms", type=int, default=140)
    parser.add_argument("--length-scale", dest="length_scale", type=float)
    parser.add_argument("--noise-scale", dest="noise_scale", type=float)
    parser.add_argument("--noise-w-scale", dest="noise_w_scale", type=float)
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    model_path = ensure_voice(args.model, data_dir)
    voice = PiperVoice.load(model_path, use_cuda=args.cuda)
    syn_config = SynthesisConfig(
        speaker_id=args.speaker,
        length_scale=args.length_scale,
        noise_scale=args.noise_scale,
        noise_w_scale=args.noise_w_scale,
    )

    emit(
        {
            "type": "ready",
            "backend": "piper",
            "model": args.model,
            "data_dir": str(data_dir),
            "cuda": args.cuda,
        }
    )

    for raw_line in sys.stdin:
        line = raw_line.strip()
        if not line:
            continue

        request_id = None
        try:
            request = json.loads(line)
            request_id = request["id"]
            text = request["text"]
            output_path = Path(request["output_path"])
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with wave.open(str(output_path), "wb") as wav_file:
                write_synthesized_wav(
                    voice,
                    text,
                    wav_file,
                    syn_config=syn_config,
                    sentence_pause_ms=max(0, int(args.sentence_pause_ms)),
                )
            emit({"type": "result", "id": request_id, "output_path": str(output_path)})
        except Exception as error:
            emit({"type": "result", "id": request_id, "error": str(error)})

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
