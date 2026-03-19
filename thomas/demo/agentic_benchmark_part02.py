async def _run_thomas_api_task(
    *,
    api_base: str,
    api_token: str,
    profile: str,
    prompt: str,
    mode: str,
    token_economy: str,
    max_iterations: int | None,
    tools_policy: str = "auto",
    job_type: str = "coding",
    watch: bool = False,
    watch_prefix: str = "",
) -> dict[str, Any]:
    base = str(api_base or "").rstrip("/")
    if not base:
        raise ValueError("thomas api base URL is empty")
    headers: dict[str, str] = {}
    token = str(api_token or "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"

    started = time.monotonic()
    chat_started = started
    reported_elapsed_ms: float | None = None
    reported_first_token_ms: float | None = None
    first_stream_event_elapsed_seconds: float | None = None
    first_text_delta_elapsed_seconds: float | None = None
    stream_event_count = 0
    text_event_count = 0
    text_parts: list[str] = []
    final_text = ""
    usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    tool_calls = 0
    token_report: dict[str, Any] = {}
    error = ""

    timeout = httpx.Timeout(connect=10.0, read=1200.0, write=30.0, pool=30.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        session_resp = await client.post(f"{base}/api/session/new", headers=headers)
        session_resp.raise_for_status()
        sid = str((session_resp.json() or {}).get("session_id") or "").strip()
        if not sid:
            raise ValueError("thomas api did not return session_id")
        chat_started = time.monotonic()

        payload: dict[str, Any] = {
            "session_id": sid,
            "profile": profile,
            "mode": mode,
            "text": str(prompt or ""),
            "token_economy": token_economy,
            "tools_policy": str(tools_policy or "auto"),
            "job_type": str(job_type or "coding"),
        }
        if max_iterations is not None:
            payload["max_iterations"] = int(max_iterations)
        _watch_line(watch, f"{watch_prefix} api session: {sid}")
        _watch_line(watch, f"{watch_prefix} started mode={mode} economy={token_economy}")

        async with client.stream("POST", f"{base}/api/chat", headers=headers, json=payload) as resp:
            resp.raise_for_status()
            async for raw_line in resp.aiter_lines():
                line = str(raw_line or "").strip()
                if not line:
                    continue
                try:
                    evt = json.loads(line)
                except json.JSONDecodeError:
                    continue
                stream_event_count += 1
                if first_stream_event_elapsed_seconds is None:
                    first_stream_event_elapsed_seconds = max(0.0, time.monotonic() - chat_started)
                et = str(evt.get("type") or "")
                if et == "text":
                    chunk = str(evt.get("text") or "")
                    text_parts.append(chunk)
                    text_event_count += 1
                    if chunk and first_text_delta_elapsed_seconds is None:
                        first_text_delta_elapsed_seconds = max(0.0, time.monotonic() - chat_started)
                    _watch_text(watch, chunk)
                elif et == "tool_start":
                    _watch_line(watch, f"\n{watch_prefix} tool_start: {evt.get('name', '')}")
                elif et == "tool_result":
                    _watch_line(
                        watch,
                        f"\n{watch_prefix} tool_result: {evt.get('name', '')} ok={bool(evt.get('ok', False))}",
                    )
                elif et == "iteration":
                    _watch_line(
                        watch,
                        f"\n{watch_prefix} iteration={evt.get('iteration')} token_estimate={evt.get('token_estimate')}",
                    )
                elif et == "error":
                    error = str(evt.get("error") or "unknown error")
                    _watch_line(watch, f"\n{watch_prefix} error: {error}")
                elif et == "done":
                    final_text = str(evt.get("response") or "")
                    usage = _normalize_usage(evt.get("run_usage") or evt.get("usage"))
                    tool_calls = int(evt.get("tool_calls") or 0)
                    token_report = dict(evt.get("token_report") or {})
                    elapsed_raw = _safe_float(evt.get("elapsed_ms"))
                    if elapsed_raw is not None and elapsed_raw >= 0:
                        reported_elapsed_ms = float(elapsed_raw)
                    first_token_raw = _extract_reported_first_token_ms(evt, token_report=token_report)
                    if first_token_raw is not None:
                        reported_first_token_ms = float(first_token_raw)
                    _watch_line(watch, f"\n{watch_prefix} done tools={tool_calls}")
                elif et == "swarm_done":
                    final_text = str(evt.get("final") or "")
                    usage = _normalize_usage(evt.get("run_usage") or evt.get("usage"))
                    tool_calls = int(evt.get("tool_calls") or 0)
                    token_report = dict(evt.get("token_report") or {})
                    elapsed_raw = _safe_float(evt.get("elapsed_ms"))
                    if elapsed_raw is not None and elapsed_raw >= 0:
                        reported_elapsed_ms = float(elapsed_raw)
                    first_token_raw = _extract_reported_first_token_ms(evt, token_report=token_report)
                    if first_token_raw is not None:
                        reported_first_token_ms = float(first_token_raw)
                    _watch_line(watch, f"\n{watch_prefix} swarm_done tools={tool_calls}")

    elapsed = _select_elapsed_seconds(
        reported_elapsed_ms=reported_elapsed_ms,
        fallback_elapsed_seconds=max(0.0, time.monotonic() - chat_started),
    )
    if not final_text:
        # Preserve leading indentation in generated code blocks.
        final_text = "".join(text_parts).strip("\n")
    usage = _ensure_usage_telemetry(
        usage,
        prompt_text=str(prompt or ""),
        response_text=final_text,
        token_report=token_report,
    )
    first_token_fallback = (
        first_text_delta_elapsed_seconds
        if first_text_delta_elapsed_seconds is not None
        else first_stream_event_elapsed_seconds
    )
    first_token_seconds = _select_optional_elapsed_seconds(
        reported_elapsed_ms=reported_first_token_ms,
        fallback_elapsed_seconds=first_token_fallback,
    )
    return {
        "ok": not bool(error),
        "text": final_text,
        "error": error,
        "usage": usage,
        "tool_calls": int(tool_calls),
        "token_report": token_report,
        "elapsed_seconds": float(elapsed),
        "setup_elapsed_seconds": round(max(0.0, chat_started - started), 3),
        "reported_elapsed_ms": (round(float(reported_elapsed_ms), 3) if reported_elapsed_ms is not None else None),
        "first_token_seconds": first_token_seconds,
        "first_text_delta_seconds": (
            round(float(first_text_delta_elapsed_seconds), 3) if first_text_delta_elapsed_seconds is not None else None
        ),
        "first_stream_event_seconds": (
            round(float(first_stream_event_elapsed_seconds), 3)
            if first_stream_event_elapsed_seconds is not None
            else None
        ),
        "reported_first_token_ms": (
            round(float(reported_first_token_ms), 3) if reported_first_token_ms is not None else None
        ),
        "stream_event_count": int(stream_event_count),
        "text_event_count": int(text_event_count),
    }


async def run_agentic_benchmark(args: argparse.Namespace) -> Path:
    config_path = _resolve_config_path(str(args.config or ""))
    config = load_config(config_path)

    task_pack = load_agentic_task_pack(Path(args.task_pack).resolve())
    quality_min = int((task_pack.get("quality_scale") or {}).get("min", 1))
    quality_max = int((task_pack.get("quality_scale") or {}).get("max", 5))

    run_id = str(args.run_id).strip() or datetime.now(timezone.utc).strftime("agentic-%Y%m%d-%H%M%S")
    workspace_root = Path(args.workspace).resolve()
    runs_dir = Path(args.runs_dir).resolve()
    artifact_root_rel = Path("runtime") / "agentic_bench" / run_id

    baseline_name = str(args.baseline_name).strip() or "baseline_raw"
    thomas_name = str(args.thomas_name).strip() or "thomas_os"
    tracks: list[TrackSpec] = []
    if not bool(args.skip_baseline):
        tracks.append(TrackSpec(name=baseline_name, kind="raw", profile=args.profile))
    if not bool(args.skip_thomas):
        tracks.append(
            TrackSpec(
                name=thomas_name,
                kind="thomas",
                profile=args.profile,
                mode=args.thomas_mode,
                token_economy=args.thomas_token_economy,
                max_iterations=args.max_iterations,
            )
        )
    if not tracks:
        raise ValueError("Nothing to run: both baseline and thomas tracks are disabled.")

    if bool(args.thomas_max_mode):
        for track in tracks:
            if track.kind != "thomas":
                continue
            track.token_economy = "max"
            if args.thomas_runner == "api":
                track.mode = "swarm"
            else:
                track.mode = "thinking"
            if track.max_iterations is None:
                track.max_iterations = 20

    if args.thomas_runner == "embedded":
        for track in tracks:
            if track.kind == "thomas" and track.mode == "swarm":
                raise ValueError("mode=swarm requires --thomas-runner api")

    records: list[dict[str, Any]] = []
    detailed_rows: list[dict[str, Any]] = []
    transcript_blobs: dict[str, str] = {}
    watch = bool(getattr(args, "watch", False))

    for task in list(task_pack.get("tasks") or []):
        task_id = str(task.get("id") or "").strip()
        for track in tracks:
            context = {
                "run_id": run_id,
                "track": track.name,
                "artifact_dir": str((artifact_root_rel / track.name).as_posix()),
                "workspace": str(workspace_root.as_posix()),
            }
            rendered = render_task(task, context)
            prompt = str(rendered.get("prompt") or "")
            (workspace_root / Path(context["artifact_dir"])).mkdir(parents=True, exist_ok=True)
            watch_prefix = f"[{task_id}/{track.name}]"

            if track.kind == "raw":
                run = await _run_raw_task(
                    config,
                    profile=track.profile,
                    prompt=prompt,
                    watch=watch,
                    watch_prefix=watch_prefix,
                )
            elif args.thomas_runner == "api":
                run = await _run_thomas_api_task(
                    api_base=args.thomas_api_base,
                    api_token=args.thomas_api_token,
                    profile=track.profile,
                    prompt=prompt,
                    mode=track.mode,
                    token_economy=track.token_economy,
                    max_iterations=track.max_iterations,
                    watch=watch,
                    watch_prefix=watch_prefix,
                )
            else:
                run = await _run_thomas_embedded_task(
                    config,
                    profile=track.profile,
                    prompt=prompt,
                    mode=track.mode,
                    token_economy=track.token_economy,
                    max_iterations=track.max_iterations,
                    watch=watch,
                    watch_prefix=watch_prefix,
                )

            checks = evaluate_task_success(
                rendered,
                response_text=str(run.get("text") or ""),
                workspace_root=workspace_root,
            )
            success = bool(run.get("ok")) and bool(checks.get("success"))
            notes = []
            err = str(run.get("error") or "").strip()
            if err:
                notes.append(f"runner_error={err}")
            notes.extend(list(checks.get("reasons") or []))
            notes_text = "; ".join(notes).strip()

            transcript_rel = str((Path("transcripts") / track.name / f"{task_id}.md").as_posix())
            transcript_blobs[transcript_rel] = "\n".join(
                [
                    f"# Task {task_id} - {track.name}",
                    "",
                    f"- run_id: {run_id}",
                    f"- track_kind: {track.kind}",
                    f"- profile: {track.profile}",
                    f"- mode: {track.mode if track.kind == 'thomas' else 'raw'}",
                    f"- token_economy: {track.token_economy if track.kind == 'thomas' else 'n/a'}",
                    f"- elapsed_seconds: {run.get('elapsed_seconds')}",
                    f"- first_token_seconds: {run.get('first_token_seconds')}",
                    f"- first_text_delta_seconds: {run.get('first_text_delta_seconds')}",
                    f"- first_stream_event_seconds: {run.get('first_stream_event_seconds')}",
                    f"- setup_elapsed_seconds: {run.get('setup_elapsed_seconds')}",
                    f"- stream_event_count: {run.get('stream_event_count')}",
                    f"- text_event_count: {run.get('text_event_count')}",
                    f"- success: {str(success).lower()}",
                    f"- tool_calls: {run.get('tool_calls')}",
                    f"- usage: {json.dumps(run.get('usage') or {}, ensure_ascii=False)}",
                    "",
                    "## Prompt",
                    "",
                    "```text",
                    prompt,
                    "```",
                    "",
                    "## Response",
                    "",
                    "```text",
                    str(run.get("text") or ""),
                    "```",
                    "",
                    "## Checks",
                    "",
                    "```json",
                    json.dumps(checks, ensure_ascii=False, indent=2),
                    "```",
                    "",
                ]
            )

            quality_score = quality_max if success else quality_min
            records.append(
                {
                    "task_id": task_id,
                    "competitor": track.name,
                    "success": bool(success),
                    "elapsed_seconds": float(run.get("elapsed_seconds") or 0.0),
                    "follow_up_prompts": 0,
                    "quality_score": int(quality_score),
                    "evidence": transcript_rel,
                    "notes": notes_text,
                    "captured_at": _now_iso(),
                }
            )
            detailed_rows.append(
                {
                    "task_id": task_id,
                    "track": track.name,
                    "track_kind": track.kind,
                    "mode": track.mode,
                    "token_economy": track.token_economy,
                    "max_iterations": track.max_iterations,
                    "run": run,
                    "checks": checks,
                    "success": bool(success),
                }
            )

    harness_pack = _harness_pack(task_pack)
    competitors = [t.name for t in tracks]
    execution_plan = build_execution_plan(
        task_pack=harness_pack,
        competitors=competitors,
        randomize=False,
        seed=None,
    )
    summary = compute_summary(harness_pack, records)

    run_dir = write_run_artifacts(
        runs_dir=runs_dir,
        run_id=run_id,
        task_pack=harness_pack,
        competitors=competitors,
        execution_plan=execution_plan,
        randomized_order=False,
        random_seed=None,
        require_evidence=False,
        records=records,
        summary=summary,
    )

    for rel, body in transcript_blobs.items():
        target = run_dir / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")

    before_after = compute_before_after_delta(
        summary,
        baseline_name=baseline_name,
        thomas_name=thomas_name,
    )

    _write_json(run_dir / "benchmark_results.raw.json", detailed_rows)
    _write_json(run_dir / "task_pack.agentic.snapshot.json", task_pack)
    _write_json(
        run_dir / "agentic_benchmark.config.json",
        {
            "created_at": _now_iso(),
            "profile": args.profile,
            "workspace": str(workspace_root),
            "thomas_runner": args.thomas_runner,
            "thomas_api_base": str(args.thomas_api_base or ""),
            "thomas_mode": str(args.thomas_mode or ""),
            "thomas_token_economy": str(args.thomas_token_economy or ""),
            "thomas_max_mode": bool(args.thomas_max_mode),
            "max_iterations": args.max_iterations,
            "watch": watch,
            "baseline_enabled": not bool(args.skip_baseline),
            "thomas_enabled": not bool(args.skip_thomas),
            "artifact_root": str(artifact_root_rel.as_posix()),
            "config_path": str(config_path) if config_path else "",
        },
    )
    _write_json(run_dir / "before_after.delta.json", before_after)
    return run_dir


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run local-first agentic benchmark: raw model vs Thomas OS.")
    parser.add_argument("--task-pack", default=str(DEFAULT_TASK_PACK), help="Path to benchmark task pack JSON.")
    parser.add_argument("--runs-dir", default=str(DEFAULT_RUNS_DIR), help="Output directory for benchmark runs.")
    parser.add_argument("--run-id", default="", help="Optional run id (default: UTC timestamp).")
    parser.add_argument("--config", default="", help="Optional path to thomas.toml.")
    parser.add_argument("--workspace", default=".", help="Workspace root for file-based checks.")
    parser.add_argument("--profile", default="local", help="Model profile to benchmark (default: local).")
    parser.add_argument("--baseline-name", default="baseline_raw", help="Competitor label for raw baseline.")
    parser.add_argument("--thomas-name", default="thomas_os", help="Competitor label for Thomas track.")
    parser.add_argument("--skip-baseline", action="store_true", help="Skip raw baseline track.")
    parser.add_argument("--skip-thomas", action="store_true", help="Skip Thomas track.")
    parser.add_argument("--thomas-runner", choices=("embedded", "api"), default="embedded")
    parser.add_argument(
        "--thomas-api-base", default="http://127.0.0.1:8899", help="Thomas API base URL when --thomas-runner=api."
    )
    parser.add_argument("--thomas-api-token", default="", help="Thomas API bearer token for remote mode.")
    parser.add_argument("--thomas-mode", choices=("fast", "auto", "thinking", "swarm"), default="auto")
    parser.add_argument("--thomas-token-economy", choices=("cheap", "optimal", "max"), default="optimal")
    parser.add_argument(
        "--thomas-max-mode",
        action="store_true",
        help="Enable high-budget Thomas mode (max token economy; swarm via API runner).",
    )
    parser.add_argument("--max-iterations", type=int, default=None, help="Optional max iterations for Thomas track.")
    parser.add_argument("--watch", action="store_true", help="Stream live model/tool output while benchmark runs.")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if not str(args.thomas_api_token or "").strip():
        env_token = str(__import__("os").environ.get("THOMAS_API_TOKEN", "")).strip()
        if env_token:
            args.thomas_api_token = env_token
    run_dir = asyncio.run(run_agentic_benchmark(args))
    print(f"Agentic benchmark completed: {run_dir}")
    print(f"  - {run_dir / 'scorecard.json'}")
    print(f"  - {run_dir / 'before_after.delta.json'}")
    print(f"  - {run_dir / 'benchmark_results.raw.json'}")
    print(f"  - {run_dir / 'report.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
