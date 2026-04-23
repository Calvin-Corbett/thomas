import argparse
import json
import sys

from faster_whisper import WhisperModel


def parse_bool(value: str) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def emit(message: dict) -> None:
    print(json.dumps(message, ensure_ascii=False), flush=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--compute-type", dest="compute_type", default="float16")
    parser.add_argument("--beam-size", dest="beam_size", type=int, default=5)
    parser.add_argument("--vad-filter", dest="vad_filter", default="true")
    parser.add_argument("--vad-min-silence-ms", dest="vad_min_silence_ms", type=int, default=500)
    parser.add_argument("--language", default="en")
    args = parser.parse_args()

    model = WhisperModel(args.model, device=args.device, compute_type=args.compute_type)

    emit(
        {
            "type": "ready",
            "backend": "faster-whisper",
            "model": args.model,
            "device": args.device,
            "compute_type": args.compute_type,
        }
    )

    for raw_line in sys.stdin:
        line = raw_line.strip()
        if not line:
            continue

        try:
            request = json.loads(line)
            request_id = request["id"]
            input_path = request["input_path"]
            language = (args.language or "").strip() or None
            hotwords = request.get("hotwords") or []
            if isinstance(hotwords, list):
                hotwords = ", ".join(str(item).strip() for item in hotwords if str(item).strip())
            else:
                hotwords = str(hotwords).strip()
            initial_prompt = str(request.get("initial_prompt") or "").strip() or None

            transcribe_kwargs = dict(
                beam_size=args.beam_size,
                language=language,
                vad_filter=parse_bool(args.vad_filter),
                condition_on_previous_text=False,
                without_timestamps=True,
                temperature=0.0,
            )
            if transcribe_kwargs["vad_filter"]:
                transcribe_kwargs["vad_parameters"] = {
                    "min_silence_duration_ms": max(0, int(args.vad_min_silence_ms)),
                }
            if hotwords:
                transcribe_kwargs["hotwords"] = hotwords
            if initial_prompt:
                transcribe_kwargs["initial_prompt"] = initial_prompt

            segments, _info = model.transcribe(
                input_path,
                **transcribe_kwargs,
            )
            text = " ".join(segment.text.strip() for segment in segments if segment.text).strip()
            emit({"type": "result", "id": request_id, "text": text})
        except Exception as error:
            request_id = None
            try:
                request_id = json.loads(line).get("id")
            except Exception:
                request_id = None
            emit({"type": "result", "id": request_id, "error": str(error)})

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
