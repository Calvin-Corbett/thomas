from __future__ import annotations

import argparse
import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, MutableMapping, Optional, Sequence, Tuple

from thomas.cli.live_browser import (
    LiveBrowserSmokeError,
    _cdp_ready,
    _CdpClient,
    _eval_js,
    _find_fallback_cdp_url,
    _launch_browser_with_cdp,
    _list_page_targets,
    _wait_for_cdp,
)
from thomas.demo.harness import (
    DEFAULT_TASK_PACK,
    build_execution_plan,
    load_task_pack,
)

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RUNS_DIR = ROOT / "demo" / "browser-runs"


@dataclass(frozen=True)
class BrowserAdapter:
    composer_selector: str
    send_selector: str
    assistant_container_selector: str
    assistant_role_selector: str
    assistant_role_text: str
    assistant_text_selector: str
    status_selector: str
    status_done_substrings: tuple[str, ...]


def default_adapter() -> BrowserAdapter:
    return BrowserAdapter(
        composer_selector="#composerTextarea",
        send_selector="#sendBtn",
        assistant_container_selector=".message",
        assistant_role_selector=".message-role",
        assistant_role_text="Thomas",
        assistant_text_selector=".message-content",
        status_selector="#statusText",
        status_done_substrings=("done", "ready"),
    )


def parse_target_args(pairs: Sequence[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for raw in pairs:
        text = str(raw or "").strip()
        if not text:
            continue
        if "=" not in text:
            raise ValueError(f"Invalid --target '{text}'. Expected format: competitor=url")
        name, url = text.split("=", 1)
        name = name.strip()
        url = url.strip()
        if not name or not url:
            raise ValueError(f"Invalid --target '{text}'. Expected format: competitor=url")
        out[name] = url
    if len(out) < 2:
        raise ValueError("Provide at least two --target entries.")
    return out


def load_adapters(path: Path | None, competitors: Sequence[str]) -> dict[str, BrowserAdapter]:
    adapter = default_adapter()
    merged: dict[str, BrowserAdapter] = {str(c): adapter for c in competitors}
    if path is None:
        return merged
    raw = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(raw, dict):
        raise ValueError("selectors JSON must be an object keyed by competitor.")
    for competitor, spec in raw.items():
        if not isinstance(spec, dict):
            continue
        base = merged.get(str(competitor), adapter)
        status_done = spec.get("status_done_substrings", list(base.status_done_substrings))
        if not isinstance(status_done, list):
            status_done = list(base.status_done_substrings)
        merged[str(competitor)] = BrowserAdapter(
            composer_selector=str(spec.get("composer_selector", base.composer_selector)),
            send_selector=str(spec.get("send_selector", base.send_selector)),
            assistant_container_selector=str(
                spec.get("assistant_container_selector", base.assistant_container_selector)
            ),
            assistant_role_selector=str(spec.get("assistant_role_selector", base.assistant_role_selector)),
            assistant_role_text=str(spec.get("assistant_role_text", base.assistant_role_text)),
            assistant_text_selector=str(spec.get("assistant_text_selector", base.assistant_text_selector)),
            status_selector=str(spec.get("status_selector", base.status_selector)),
            status_done_substrings=tuple(str(x).lower() for x in status_done if str(x).strip()),
        )
    return merged


def _open_client_for(cdp_url: str, target_url: str) -> tuple[_CdpClient, Mapping[str, Any]]:
    targets = _list_page_targets(cdp_url)
    if not targets:
        raise LiveBrowserSmokeError("No page targets found in browser.")
    selected: Mapping[str, Any] | None = None
    for row in targets:
        page_url = str(row.get("url") or "")
        if page_url.startswith(target_url):
            selected = row
            break
    if selected is None:
        selected = targets[0]
    ws_url = str(selected.get("webSocketDebuggerUrl") or "").strip()
    if not ws_url:
        raise LiveBrowserSmokeError("Selected target missing webSocketDebuggerUrl.")
    return _CdpClient(ws_url), selected


def _ensure_cdp(
    *,
    cdp_url: str,
    launch_browser: bool,
    browser: str,
    app_url: str,
    runtime_root: Path,
) -> str:
    active = cdp_url
    if _cdp_ready(active):
        return active
    if not launch_browser:
        raise LiveBrowserSmokeError(f"CDP is not reachable at {active}.")
    _launch_browser_with_cdp(
        browser=browser,
        cdp_url=active,
        app_url=app_url,
        runtime_root=runtime_root,
    )
    if _wait_for_cdp(active, timeout_s=15.0):
        return active
    alt = _find_fallback_cdp_url(active)
    if not alt:
        raise LiveBrowserSmokeError(f"Timed out waiting for CDP endpoint: {active}")
    _launch_browser_with_cdp(
        browser=browser,
        cdp_url=alt,
        app_url=app_url,
        runtime_root=runtime_root,
    )
    if not _wait_for_cdp(alt, timeout_s=15.0):
        raise LiveBrowserSmokeError(f"Timed out waiting for fallback CDP endpoint: {alt}")
    return alt


def _wait_for_ready(client: _CdpClient, adapter: BrowserAdapter, timeout_s: float) -> None:
    composer = json.dumps(adapter.composer_selector)
    send = json.dumps(adapter.send_selector)
    deadline = time.monotonic() + max(5.0, float(timeout_s))
    while time.monotonic() < deadline:
        ready = _eval_js(
            client,
            f"Boolean(document.querySelector({composer}) && document.querySelector({send}))",
        )
        if bool(ready):
            return
        time.sleep(0.25)
    raise LiveBrowserSmokeError(
        f"Composer/send selectors not found: {adapter.composer_selector} / {adapter.send_selector}"
    )


def _assistant_count(client: _CdpClient, adapter: BrowserAdapter) -> int:
    container = json.dumps(adapter.assistant_container_selector)
    role_sel = json.dumps(adapter.assistant_role_selector)
    role_txt = json.dumps(adapter.assistant_role_text.lower())
    expr = f"""
(() => {{
  const msgs = Array.from(document.querySelectorAll({container}));
  const roleSel = {role_sel};
  const roleTxt = {role_txt};
  const assistant = msgs.filter((m) => {{
    if (!roleSel || !roleTxt) return true;
    const rt = (m.querySelector(roleSel)?.textContent || '').trim().toLowerCase();
    return rt === roleTxt;
  }});
  return assistant.length;
}})()
""".strip()
    return int(_eval_js(client, expr) or 0)


def _prepare_and_type(client: _CdpClient, adapter: BrowserAdapter, prompt: str, type_delay_ms: int) -> None:
    composer = json.dumps(adapter.composer_selector)
    send = json.dumps(adapter.send_selector)
    prep = _eval_js(
        client,
        f"""
(() => {{
  const ta = document.querySelector({composer});
  const btn = document.querySelector({send});
  if (!ta || !btn) return {{ ok: false }};
  ta.focus();
  ta.value = '';
  ta.dispatchEvent(new Event('input', {{ bubbles: true }}));
  return {{ ok: true }};
}})()
""".strip(),
    )
    if not isinstance(prep, dict) or not bool(prep.get("ok")):
        raise LiveBrowserSmokeError("Failed to prepare composer in target UI.")

    delay_s = max(0, int(type_delay_ms)) / 1000.0
    for ch in str(prompt or ""):
        chj = json.dumps(ch)
        ok = _eval_js(
            client,
            f"""
(() => {{
  const ta = document.querySelector({composer});
  if (!ta) return false;
  ta.value = ta.value + {chj};
  ta.dispatchEvent(new Event('input', {{ bubbles: true }}));
  return true;
}})()
""".strip(),
        )
        if not bool(ok):
            raise LiveBrowserSmokeError("Composer disappeared while typing.")
        if delay_s > 0:
            time.sleep(delay_s)

    sent = _eval_js(
        client,
        f"""
(() => {{
  const btn = document.querySelector({send});
  if (!btn || btn.disabled) return {{ ok: false }};
  btn.click();
  return {{ ok: true }};
}})()
""".strip(),
    )
    if not isinstance(sent, dict) or not bool(sent.get("ok")):
        raise LiveBrowserSmokeError("Failed to click send in target UI.")


def _wait_for_response(
    client: _CdpClient,
    adapter: BrowserAdapter,
    *,
    previous_count: int,
    timeout_s: float,
) -> tuple[str, str]:
    container = json.dumps(adapter.assistant_container_selector)
    role_sel = json.dumps(adapter.assistant_role_selector)
    role_txt = json.dumps(adapter.assistant_role_text.lower())
    text_sel = json.dumps(adapter.assistant_text_selector)
    status_sel = json.dumps(adapter.status_selector)
    deadline = time.monotonic() + max(5.0, float(timeout_s))
    stable_rounds = 0
    last_text = ""
    while time.monotonic() < deadline:
        snap = _eval_js(
            client,
            f"""
(() => {{
  const msgs = Array.from(document.querySelectorAll({container}));
  const roleSel = {role_sel};
  const roleTxt = {role_txt};
  const assistant = msgs.filter((m) => {{
    if (!roleSel || !roleTxt) return true;
    const rt = (m.querySelector(roleSel)?.textContent || '').trim().toLowerCase();
    return rt === roleTxt;
  }});
  const last = assistant[assistant.length - 1];
  const txt = (last?.querySelector({text_sel})?.innerText || '').trim();
  const status = (document.querySelector({status_sel})?.textContent || '').trim().toLowerCase();
  return {{
    count: assistant.length,
    text: txt,
    status: status,
    url: location.href
  }};
}})()
""".strip(),
        )
        if not isinstance(snap, dict):
            time.sleep(0.35)
            continue
        count = int(snap.get("count") or 0)
        text = str(snap.get("text") or "")
        status = str(snap.get("status") or "")
        url = str(snap.get("url") or "")
        done = False
        if count > previous_count:
            done_tokens = tuple(adapter.status_done_substrings)
            if adapter.status_selector and done_tokens:
                done = any(tok in status for tok in done_tokens)
            else:
                if text and text == last_text:
                    stable_rounds += 1
                else:
                    stable_rounds = 0
                done = stable_rounds >= 2
        last_text = text
        if done:
            return text, url
        time.sleep(0.35)
    raise LiveBrowserSmokeError("Timed out waiting for assistant completion in target UI.")


def build_results_from_browser(
    *,
    browser_results: Sequence[Mapping[str, Any]],
    quality_min: int,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in browser_results:
        transcript = str(row.get("transcript_relpath") or "").strip()
        out.append(
            {
                "task_id": str(row.get("task_id") or ""),
                "competitor": str(row.get("competitor") or ""),
                "success": bool(row.get("success")),
                "elapsed_seconds": float(row.get("elapsed_seconds") or 0.0),
                "follow_up_prompts": 0,
                "quality_score": int(quality_min),
                "evidence": transcript,
                "notes": str(row.get("error") or ""),
                "captured_at": str(row.get("completed_at") or ""),
            }
        )
    return out


def run_dual_browser_demo(
    *,
    task_pack: Mapping[str, Any],
    execution_plan: Sequence[Mapping[str, Any]],
    targets: Mapping[str, str],
    adapters: Mapping[str, BrowserAdapter],
    cdp_url: str,
    launch_browser: bool,
    browser: str,
    type_delay_ms: int,
    reply_timeout_s: float,
    runtime_root: Path,
    run_dir: Path,
) -> list[dict[str, Any]]:
    run_dir.mkdir(parents=True, exist_ok=True)
    transcript_root = run_dir / "browser_transcripts"
    transcript_root.mkdir(parents=True, exist_ok=True)

    first_url = str(next(iter(targets.values())))
    active_cdp = _ensure_cdp(
        cdp_url=cdp_url,
        launch_browser=launch_browser,
        browser=browser,
        app_url=first_url,
        runtime_root=runtime_root,
    )

    task_map = {str(task.get("id") or ""): str(task.get("prompt") or "") for task in (task_pack.get("tasks") or [])}
    results: list[dict[str, Any]] = []

    for row in execution_plan:
        step = int(row.get("step") or 0)
        task_id = str(row.get("task_id") or "")
        competitor = str(row.get("competitor") or "")
        prompt = task_map.get(task_id, "")
        target_url = str(targets.get(competitor) or "")
        adapter = adapters.get(competitor) or default_adapter()
        started_at = datetime.now(timezone.utc)
        error = ""
        response_text = ""
        page_url = target_url
        ok = False

        try:
            client, selected = _open_client_for(active_cdp, target_url)
            try:
                client.call("Runtime.enable")
                client.call("Page.enable")
                client.call("Page.bringToFront")
                current_url = str(selected.get("url") or "")
                if not current_url.startswith(target_url):
                    client.call("Page.navigate", {"url": target_url})
                _wait_for_ready(client, adapter, timeout_s=reply_timeout_s)
                before = _assistant_count(client, adapter)
                _prepare_and_type(client, adapter, prompt, type_delay_ms=type_delay_ms)
                response_text, page_url = _wait_for_response(
                    client,
                    adapter,
                    previous_count=before,
                    timeout_s=reply_timeout_s,
                )
                ok = True
            finally:
                client.close()
        except Exception as exc:
            error = str(exc)
            ok = False

        completed_at = datetime.now(timezone.utc)
        elapsed = max(0.0, (completed_at - started_at).total_seconds())
        transcript_name = f"step-{step:03d}_{competitor}_{task_id}.txt"
        transcript_path = transcript_root / transcript_name
        transcript_path.write_text(
            (
                f"step: {step}\n"
                f"task_id: {task_id}\n"
                f"competitor: {competitor}\n"
                f"target_url: {target_url}\n"
                f"page_url: {page_url}\n"
                f"started_at: {started_at.isoformat()}\n"
                f"completed_at: {completed_at.isoformat()}\n"
                f"elapsed_seconds: {elapsed:.3f}\n"
                f"success: {str(ok).lower()}\n"
                f"error: {error}\n\n"
                f"PROMPT:\n{prompt}\n\n"
                f"RESPONSE:\n{response_text}\n"
            ),
            encoding="utf-8",
        )

        results.append(
            {
                "step": step,
                "task_id": task_id,
                "competitor": competitor,
                "target_url": target_url,
                "page_url": page_url,
                "prompt": prompt,
                "response_text": response_text,
                "started_at": started_at.isoformat(),
                "completed_at": completed_at.isoformat(),
                "elapsed_seconds": round(elapsed, 3),
                "success": bool(ok),
                "error": error,
                "transcript_relpath": str(Path("browser_transcripts") / transcript_name).replace("\\", "/"),
            }
        )
    return results


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a dual-browser head-to-head demo with timestamps.")
    parser.add_argument("--task-pack", default=str(DEFAULT_TASK_PACK), help="Path to task pack JSON.")
    parser.add_argument("--run-id", default="", help="Run id. Default: UTC timestamp.")
    parser.add_argument("--runs-dir", default=str(DEFAULT_RUNS_DIR), help="Run output directory.")
    parser.add_argument("--target", action="append", default=[], help="Target mapping competitor=url (repeatable).")
    parser.add_argument("--selectors-json", default="", help="Optional selectors config JSON by competitor.")
    parser.add_argument("--cdp-url", default="http://127.0.0.1:9222", help="Chrome DevTools endpoint.")
    parser.add_argument("--browser", default="chrome", choices=["chrome", "edge"], help="Browser for launch fallback.")
    parser.add_argument(
        "--launch-browser",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Auto launch browser if CDP down.",
    )
    parser.add_argument("--type-delay-ms", type=int, default=20, help="Per-character typing delay.")
    parser.add_argument("--reply-timeout", type=float, default=90.0, help="Per-step completion timeout seconds.")
    parser.add_argument("--randomize-order", action="store_true", help="Randomize execution plan order.")
    parser.add_argument("--seed", type=int, default=0, help="Randomization seed.")
    parser.add_argument(
        "--runtime-root",
        default="",
        help="Runtime root for browser launch profile. Default: repository runtime/",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    targets = parse_target_args(args.target)
    competitors = tuple(targets.keys())
    task_pack = load_task_pack(Path(args.task_pack).resolve())
    execution_plan = build_execution_plan(
        task_pack=task_pack,
        competitors=competitors,
        randomize=bool(args.randomize_order),
        seed=int(args.seed),
    )
    selectors_path = Path(args.selectors_json).resolve() if str(args.selectors_json or "").strip() else None
    adapters = load_adapters(selectors_path, competitors)

    run_id = str(args.run_id).strip() or datetime.now(timezone.utc).strftime("browser-run-%Y%m%d-%H%M%S")
    run_dir = Path(args.runs_dir).resolve() / run_id
    run_dir.mkdir(parents=True, exist_ok=False)

    runtime_root = (
        Path(args.runtime_root).resolve()
        if str(args.runtime_root or "").strip()
        else (ROOT / "runtime")
    )
    runtime_root.mkdir(parents=True, exist_ok=True)

    _write_json(run_dir / "task_pack.snapshot.json", task_pack)
    _write_json(run_dir / "execution_plan.json", execution_plan)
    _write_json(run_dir / "targets.json", targets)
    _write_json(
        run_dir / "selectors.snapshot.json",
        {
            competitor: {
                "composer_selector": adapter.composer_selector,
                "send_selector": adapter.send_selector,
                "assistant_container_selector": adapter.assistant_container_selector,
                "assistant_role_selector": adapter.assistant_role_selector,
                "assistant_role_text": adapter.assistant_role_text,
                "assistant_text_selector": adapter.assistant_text_selector,
                "status_selector": adapter.status_selector,
                "status_done_substrings": list(adapter.status_done_substrings),
            }
            for competitor, adapter in adapters.items()
        },
    )

    results = run_dual_browser_demo(
        task_pack=task_pack,
        execution_plan=execution_plan,
        targets=targets,
        adapters=adapters,
        cdp_url=str(args.cdp_url),
        launch_browser=bool(args.launch_browser),
        browser=str(args.browser),
        type_delay_ms=int(args.type_delay_ms),
        reply_timeout_s=float(args.reply_timeout),
        runtime_root=runtime_root,
        run_dir=run_dir,
    )
    _write_json(run_dir / "browser_results.raw.json", results)

    quality_min = int((task_pack.get("quality_scale") or {"min": 1}).get("min") or 1)
    template = build_results_from_browser(browser_results=results, quality_min=quality_min)
    _write_json(run_dir / "results.template.from_browser.json", template)

    ok_count = sum(1 for row in results if bool(row.get("success")))
    print(f"Dual browser run completed: {run_dir}")
    print(f"  steps: {len(results)}")
    print(f"  successful steps: {ok_count}")
    print(f"  failed steps: {len(results) - ok_count}")
    print(f"  - {run_dir / 'browser_results.raw.json'}")
    print(f"  - {run_dir / 'results.template.from_browser.json'}")
    print(f"  - {run_dir / 'browser_transcripts'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
