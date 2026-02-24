from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any, Mapping

from thomas.integrations.github_automation import (
    fetch_issue,
    fetch_pull_request,
    fetch_pull_request_files,
    normalize_issue_to_task,
    summarize_pr_risk,
)


def _safe_string(value: Any) -> str:
    return str(value or "").strip()


def _resolve_token(token: str, token_env: str) -> str:
    direct = _safe_string(token)
    if direct:
        return direct
    env_key = _safe_string(token_env)
    if env_key:
        env_value = _safe_string(os.environ.get(env_key))
        if env_value:
            return env_value
    raise ValueError(f"missing auth token (use --token or set {_safe_string(token_env) or 'TOKEN env'})")


def _http_get_json(url: str, *, headers: Mapping[str, str], timeout_s: float) -> Any:
    req = urllib.request.Request(_safe_string(url), headers={str(k): str(v) for k, v in headers.items()})
    with urllib.request.urlopen(req, timeout=max(1.0, float(timeout_s))) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
    return json.loads(raw)


def _http_request_json(
    url: str,
    *,
    method: str,
    headers: Mapping[str, str],
    timeout_s: float,
    body: Mapping[str, Any] | None = None,
) -> Any:
    data = None
    if body is not None:
        data = json.dumps(dict(body), ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        _safe_string(url),
        headers={str(k): str(v) for k, v in headers.items()},
        data=data,
        method=_safe_string(method).upper() or "GET",
    )
    with urllib.request.urlopen(req, timeout=max(1.0, float(timeout_s))) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
    return json.loads(raw)


def _write_optional_json(path: str, payload: Mapping[str, Any]) -> None:
    target = _safe_string(path)
    if not target:
        return
    out = Path(target).expanduser().resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(dict(payload), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _extract_notion_title(page: Mapping[str, Any]) -> str:
    props = page.get("properties")
    if not isinstance(props, Mapping):
        return ""
    for value in props.values():
        if not isinstance(value, Mapping):
            continue
        title_items = value.get("title")
        if not isinstance(title_items, list):
            continue
        chunks = []
        for item in title_items:
            if isinstance(item, Mapping):
                plain = _safe_string(item.get("plain_text"))
                if plain:
                    chunks.append(plain)
        if chunks:
            return " ".join(chunks).strip()
    return ""


def notion_pull_page(args: argparse.Namespace) -> dict[str, Any]:
    token = _resolve_token(args.token, args.token_env)
    page_id = _safe_string(args.page_id)
    if not page_id:
        raise ValueError("--page-id is required")
    base = _safe_string(args.base_url).rstrip("/")
    url = f"{base}/v1/pages/{urllib.parse.quote(page_id)}"
    payload = _http_get_json(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Notion-Version": _safe_string(args.notion_version) or "2022-06-28",
            "Content-Type": "application/json",
        },
        timeout_s=float(args.timeout_s),
    )
    if not isinstance(payload, Mapping):
        raise RuntimeError("Notion response was not an object.")
    out = {
        "ok": True,
        "provider": "notion",
        "page_id": _safe_string(payload.get("id")) or page_id,
        "object": _safe_string(payload.get("object")),
        "url": _safe_string(payload.get("url")),
        "last_edited_time": _safe_string(payload.get("last_edited_time")),
        "title": _extract_notion_title(payload),
    }
    _write_optional_json(_safe_string(args.output), out)
    return out


def figma_pull_file(args: argparse.Namespace) -> dict[str, Any]:
    token = _resolve_token(args.token, args.token_env)
    file_key = _safe_string(args.file_key)
    if not file_key:
        raise ValueError("--file-key is required")
    base = _safe_string(args.base_url).rstrip("/")
    query = ""
    node_id = _safe_string(args.node_id)
    if node_id:
        query = f"?ids={urllib.parse.quote(node_id)}"
    url = f"{base}/v1/files/{urllib.parse.quote(file_key)}{query}"
    payload = _http_get_json(
        url,
        headers={
            "X-Figma-Token": token,
            "Content-Type": "application/json",
        },
        timeout_s=float(args.timeout_s),
    )
    if not isinstance(payload, Mapping):
        raise RuntimeError("Figma response was not an object.")
    document = payload.get("document")
    children = document.get("children") if isinstance(document, Mapping) else []
    node_count = len(children) if isinstance(children, list) else 0
    out = {
        "ok": True,
        "provider": "figma",
        "file_key": file_key,
        "name": _safe_string(payload.get("name")),
        "last_modified": _safe_string(payload.get("lastModified")),
        "version": _safe_string(payload.get("version")),
        "role": _safe_string(payload.get("role")),
        "branch_key": _safe_string(payload.get("branchKey")),
        "top_level_node_count": int(node_count),
        "node_id": node_id,
    }
    _write_optional_json(_safe_string(args.output), out)
    return out


def github_issue_to_task(args: argparse.Namespace) -> dict[str, Any]:
    token = _resolve_token(args.token, args.token_env)
    repo = _safe_string(args.repo)
    issue_number = int(args.issue_number)
    if not repo:
        raise ValueError("--repo is required")
    if issue_number <= 0:
        raise ValueError("--issue-number must be > 0")

    issue = fetch_issue(
        base_url=_safe_string(args.base_url) or "https://api.github.com",
        repo=repo,
        issue_number=issue_number,
        token=token,
        timeout_s=float(args.timeout_s),
    )
    task = normalize_issue_to_task(issue)
    out = {"ok": True, "provider": "github", "repo": repo, "issue_number": issue_number, "task": task}
    _write_optional_json(_safe_string(args.output), out)
    return out


def github_pr_risk_scan(args: argparse.Namespace) -> dict[str, Any]:
    token = _resolve_token(args.token, args.token_env)
    repo = _safe_string(args.repo)
    pr_number = int(args.pr_number)
    if not repo:
        raise ValueError("--repo is required")
    if pr_number <= 0:
        raise ValueError("--pr-number must be > 0")

    base_url = _safe_string(args.base_url) or "https://api.github.com"
    pr = fetch_pull_request(
        base_url=base_url,
        repo=repo,
        pr_number=pr_number,
        token=token,
        timeout_s=float(args.timeout_s),
    )
    files = fetch_pull_request_files(
        base_url=base_url,
        repo=repo,
        pr_number=pr_number,
        token=token,
        timeout_s=float(args.timeout_s),
    )
    risk = summarize_pr_risk(pr, files)
    out = {
        "ok": True,
        "provider": "github",
        "repo": repo,
        "pr_number": pr_number,
        "pull_request": {
            "title": _safe_string(pr.get("title")),
            "state": _safe_string(pr.get("state")),
            "draft": bool(pr.get("draft", False)),
            "html_url": _safe_string(pr.get("html_url")),
            "user": _safe_string((pr.get("user") or {}).get("login")) if isinstance(pr.get("user"), Mapping) else "",
        },
        "risk": risk.to_dict(),
    }
    _write_optional_json(_safe_string(args.output), out)
    return out


def _parse_workflow(workflow_json: str, workflow_file: str) -> dict[str, Any]:
    inline = _safe_string(workflow_json)
    file_path = _safe_string(workflow_file)
    if inline:
        try:
            payload = json.loads(inline)
        except Exception as exc:
            raise ValueError(f"--workflow-json must be valid JSON: {exc}") from exc
        if not isinstance(payload, Mapping):
            raise ValueError("--workflow-json must decode to an object")
        return dict(payload)
    if file_path:
        path = Path(file_path).expanduser().resolve()
        if not path.exists():
            raise ValueError(f"workflow file not found: {path}")
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise ValueError(f"--workflow-file is not valid JSON: {exc}") from exc
        if not isinstance(payload, Mapping):
            raise ValueError("--workflow-file must decode to an object")
        return dict(payload)
    raise ValueError("workflow_json or workflow_file is required")


def comfyui_queue_prompt(args: argparse.Namespace) -> dict[str, Any]:
    server_url = _safe_string(args.server_url).rstrip("/") or "http://127.0.0.1:8188"
    workflow = _parse_workflow(_safe_string(args.workflow_json), _safe_string(args.workflow_file))
    client_id = _safe_string(args.client_id) or str(uuid.uuid4())
    payload = _http_request_json(
        f"{server_url}/prompt",
        method="POST",
        headers={"Content-Type": "application/json"},
        timeout_s=float(args.timeout_s),
        body={"prompt": workflow, "client_id": client_id},
    )
    if not isinstance(payload, Mapping):
        raise RuntimeError("ComfyUI /prompt response was not an object.")
    out = {
        "ok": True,
        "provider": "comfyui",
        "server_url": server_url,
        "client_id": client_id,
        "prompt_id": _safe_string(payload.get("prompt_id")),
        "number": payload.get("number"),
        "node_errors": payload.get("node_errors"),
        "raw": dict(payload),
    }
    _write_optional_json(_safe_string(args.output), out)
    return out


def comfyui_get_history(args: argparse.Namespace) -> dict[str, Any]:
    server_url = _safe_string(args.server_url).rstrip("/") or "http://127.0.0.1:8188"
    prompt_id = _safe_string(args.prompt_id)
    if not prompt_id:
        raise ValueError("--prompt-id is required")
    payload = _http_get_json(
        f"{server_url}/history/{urllib.parse.quote(prompt_id)}",
        headers={"Content-Type": "application/json"},
        timeout_s=float(args.timeout_s),
    )
    history_row = payload.get(prompt_id) if isinstance(payload, Mapping) else None
    if isinstance(history_row, Mapping):
        outputs = history_row.get("outputs")
        output_nodes = len(outputs) if isinstance(outputs, Mapping) else 0
        status = history_row.get("status")
        out = {
            "ok": True,
            "provider": "comfyui",
            "server_url": server_url,
            "prompt_id": prompt_id,
            "status": status,
            "output_nodes": int(output_nodes),
            "history": dict(history_row),
        }
    else:
        out = {
            "ok": True,
            "provider": "comfyui",
            "server_url": server_url,
            "prompt_id": prompt_id,
            "status": "unknown",
            "output_nodes": 0,
            "history": {},
        }
    _write_optional_json(_safe_string(args.output), out)
    return out


def otio_validate_timeline(args: argparse.Namespace) -> dict[str, Any]:
    input_path = Path(_safe_string(args.input_path)).expanduser().resolve()
    if not input_path.exists():
        raise ValueError(f"--input-path not found: {input_path}")

    parser_used = "json_fallback"
    schema = ""
    track_count = 0
    clip_count = 0

    try:
        import opentimelineio as otio  # type: ignore[import-not-found]

        timeline = otio.adapters.read_from_file(str(input_path))
        parser_used = "opentimelineio"
        schema = _safe_string(getattr(timeline, "schema_name", lambda: "")())
        tracks = getattr(timeline, "tracks", None)
        if tracks is not None:
            try:
                iterable = list(tracks)
            except Exception:
                iterable = []
            track_count = len(iterable)
            for track in iterable:
                try:
                    clip_count += len(list(track))
                except Exception:
                    continue
    except Exception:
        payload = json.loads(input_path.read_text(encoding="utf-8"))
        if not isinstance(payload, Mapping):
            raise RuntimeError("Timeline JSON must be an object")
        schema = _safe_string(payload.get("OTIO_SCHEMA"))
        tracks_obj = payload.get("tracks")
        if isinstance(tracks_obj, Mapping):
            children = tracks_obj.get("children")
            if isinstance(children, list):
                track_count = len(children)
                for track in children:
                    if isinstance(track, Mapping):
                        clips = track.get("children")
                        if isinstance(clips, list):
                            clip_count += len(clips)

    out = {
        "ok": True,
        "provider": "opentimelineio",
        "input_path": str(input_path),
        "exists": True,
        "schema": schema,
        "track_count": int(track_count),
        "clip_count": int(clip_count),
        "parser": parser_used,
    }
    _write_optional_json(_safe_string(args.output), out)
    return out


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m thomas.asset_studio.connector_shims", add_help=True)
    sub = parser.add_subparsers(dest="command")

    notion = sub.add_parser("notion_pull_page")
    notion.add_argument("--page-id", required=True)
    notion.add_argument("--token", default="")
    notion.add_argument("--token-env", default="NOTION_TOKEN")
    notion.add_argument("--base-url", default="https://api.notion.com")
    notion.add_argument("--notion-version", default="2022-06-28")
    notion.add_argument("--timeout-s", type=float, default=20.0)
    notion.add_argument("--output", default="")

    figma = sub.add_parser("figma_pull_file")
    figma.add_argument("--file-key", required=True)
    figma.add_argument("--node-id", default="")
    figma.add_argument("--token", default="")
    figma.add_argument("--token-env", default="FIGMA_TOKEN")
    figma.add_argument("--base-url", default="https://api.figma.com")
    figma.add_argument("--timeout-s", type=float, default=20.0)
    figma.add_argument("--output", default="")

    issue = sub.add_parser("github_issue_to_task")
    issue.add_argument("--repo", required=True)
    issue.add_argument("--issue-number", type=int, required=True)
    issue.add_argument("--token", default="")
    issue.add_argument("--token-env", default="GITHUB_TOKEN")
    issue.add_argument("--base-url", default="https://api.github.com")
    issue.add_argument("--timeout-s", type=float, default=20.0)
    issue.add_argument("--output", default="")

    pr = sub.add_parser("github_pr_risk_scan")
    pr.add_argument("--repo", required=True)
    pr.add_argument("--pr-number", type=int, required=True)
    pr.add_argument("--token", default="")
    pr.add_argument("--token-env", default="GITHUB_TOKEN")
    pr.add_argument("--base-url", default="https://api.github.com")
    pr.add_argument("--timeout-s", type=float, default=20.0)
    pr.add_argument("--output", default="")

    comfy_queue = sub.add_parser("comfyui_queue_prompt")
    comfy_queue.add_argument("--server-url", default="http://127.0.0.1:8188")
    comfy_queue.add_argument("--workflow-json", default="")
    comfy_queue.add_argument("--workflow-file", default="")
    comfy_queue.add_argument("--client-id", default="")
    comfy_queue.add_argument("--timeout-s", type=float, default=30.0)
    comfy_queue.add_argument("--output", default="")

    comfy_history = sub.add_parser("comfyui_get_history")
    comfy_history.add_argument("--server-url", default="http://127.0.0.1:8188")
    comfy_history.add_argument("--prompt-id", required=True)
    comfy_history.add_argument("--timeout-s", type=float, default=20.0)
    comfy_history.add_argument("--output", default="")

    otio_validate = sub.add_parser("otio_validate_timeline")
    otio_validate.add_argument("--input-path", required=True)
    otio_validate.add_argument("--output", default="")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    ns = parser.parse_args(argv)
    command = _safe_string(getattr(ns, "command", ""))
    try:
        if command == "notion_pull_page":
            payload = notion_pull_page(ns)
        elif command == "figma_pull_file":
            payload = figma_pull_file(ns)
        elif command == "github_issue_to_task":
            payload = github_issue_to_task(ns)
        elif command == "github_pr_risk_scan":
            payload = github_pr_risk_scan(ns)
        elif command == "comfyui_queue_prompt":
            payload = comfyui_queue_prompt(ns)
        elif command == "comfyui_get_history":
            payload = comfyui_get_history(ns)
        elif command == "otio_validate_timeline":
            payload = otio_validate_timeline(ns)
        else:
            parser.print_help()
            return 2
        print(json.dumps(payload, ensure_ascii=False))
        return 0
    except Exception as exc:
        err = {"ok": False, "error": f"{type(exc).__name__}: {exc}", "command": command}
        print(json.dumps(err, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
