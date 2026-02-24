from __future__ import annotations

import asyncio
import contextlib
import re
import uuid
from typing import Any, Mapping

from .runtime_common import TERMINAL_STATES, _normalize_tags, _now_iso, _safe_int, _safe_string


class AssetStudioRuntimeTemplateMixin:
    async def create_template(
        self,
        *,
        name: str,
        connector_id: str,
        action_id: str,
        payload: Mapping[str, Any] | None = None,
        tags: list[str] | None = None,
        favorite: bool = False,
        pinned: bool = False,
        pin_index: int | None = None,
    ) -> dict[str, Any]:
        template_name = _safe_string(name)
        if not template_name:
            raise ValueError("name is required")
        connector = self.catalog.get(connector_id)
        if connector is None:
            raise KeyError(f"unknown connector '{connector_id}'")
        action = connector.action_by_id(action_id)
        if action is None:
            raise ValueError(f"unknown action '{action_id}' for connector '{connector_id}'")
        body = dict(payload or {})
        return await self.store.upsert_template(
            name=template_name,
            connector_id=connector.id,
            action_id=action.id,
            payload=body,
            tags=_normalize_tags(tags),
            favorite=bool(favorite),
            pinned=bool(pinned),
            pin_index=pin_index,
        )

    async def get_template_by_name(self, name: str) -> dict[str, Any] | None:
        return await self.store.get_template_by_name(name)

    async def get_template(self, template_id: str) -> dict[str, Any] | None:
        return await self.store.get_template(template_id)

    async def list_templates(
        self,
        *,
        limit: int = 100,
        favorites_only: bool = False,
        tag: str = "",
    ) -> list[dict[str, Any]]:
        return await self.store.list_templates(limit=limit, favorites_only=favorites_only, tag=tag)

    async def update_template_metadata(
        self,
        template_id: str,
        *,
        name: str | None = None,
        tags: list[str] | None = None,
        favorite: bool | None = None,
        pinned: bool | None = None,
        pin_index: int | None = None,
    ) -> dict[str, Any] | None:
        return await self.store.update_template_metadata(
            template_id,
            name=name,
            tags=_normalize_tags(tags) if tags is not None else None,
            favorite=favorite,
            pinned=pinned,
            pin_index=pin_index,
        )

    async def delete_template(self, template_id: str) -> bool:
        return await self.store.delete_template(template_id)

    async def clone_template(
        self,
        template_id: str,
        *,
        name: str = "",
    ) -> dict[str, Any] | None:
        source = await self.get_template(template_id)
        if source is None:
            return None
        desired_name = _safe_string(name)
        if not desired_name:
            base_name = _safe_string(source.get("name")) or "template"
            candidate = f"{base_name}-copy"
            if await self.get_template_by_name(candidate) is None:
                desired_name = candidate
            else:
                for idx in range(2, 101):
                    candidate = f"{base_name}-copy-{idx}"
                    if await self.get_template_by_name(candidate) is None:
                        desired_name = candidate
                        break
                if not desired_name:
                    desired_name = f"{base_name}-copy-{uuid.uuid4().hex[:6]}"
        return await self.create_template(
            name=desired_name,
            connector_id=_safe_string(source.get("connector_id")),
            action_id=_safe_string(source.get("action_id")),
            payload=source.get("payload") if isinstance(source.get("payload"), Mapping) else {},
            tags=source.get("tags") if isinstance(source.get("tags"), list) else [],
            favorite=False,
            pinned=False,
            pin_index=9999,
        )

    async def export_template_bundle(
        self,
        template_id: str,
        *,
        include_secret: bool = False,
    ) -> dict[str, Any] | None:
        template = await self.get_template(template_id)
        if template is None:
            return None
        bundle: dict[str, Any] = {
            "schema_version": 1,
            "exported_at": _now_iso(),
            "template": template,
        }
        webhook = await self.store.get_template_webhook_config(template_id)
        if isinstance(webhook, Mapping):
            webhook_payload: dict[str, Any] = {
                "url": _safe_string(webhook.get("url")),
                "enabled": bool(webhook.get("enabled")),
                "timeout_s": max(1, min(30, _safe_int(webhook.get("timeout_s"), 5))),
                "has_secret": bool(_safe_string(webhook.get("secret"))),
            }
            secret = _safe_string(webhook.get("secret"))
            if include_secret and secret:
                webhook_payload["secret"] = secret
            bundle["webhook"] = webhook_payload
        return bundle

    async def import_template_bundle(
        self,
        bundle: Mapping[str, Any],
        *,
        name_override: str = "",
    ) -> dict[str, Any]:
        source = bundle.get("template")
        if not isinstance(source, Mapping):
            raise ValueError("bundle.template must be a JSON object")

        name = _safe_string(name_override) or _safe_string(source.get("name"))
        if not name:
            raise ValueError("template.name is required")
        connector_id = _safe_string(source.get("connector_id"))
        action_id = _safe_string(source.get("action_id"))
        if not connector_id:
            raise ValueError("template.connector_id is required")
        if not action_id:
            raise ValueError("template.action_id is required")

        payload = source.get("payload")
        body = dict(payload) if isinstance(payload, Mapping) else {}
        tags = source.get("tags")
        favorite = bool(source.get("favorite"))
        pinned = bool(source.get("pinned"))
        pin_index = _safe_int(source.get("pin_index"), 9999)

        template = await self.create_template(
            name=name,
            connector_id=connector_id,
            action_id=action_id,
            payload=body,
            tags=tags if isinstance(tags, list) else [],
            favorite=favorite,
            pinned=pinned,
            pin_index=pin_index,
        )

        webhook_result: dict[str, Any] | None = None
        webhook = bundle.get("webhook")
        if isinstance(webhook, Mapping):
            endpoint = _safe_string(webhook.get("url"))
            if endpoint:
                webhook_result = await self.configure_template_webhook(
                    template_id=_safe_string(template.get("template_id")),
                    url=endpoint,
                    secret=_safe_string(webhook.get("secret")),
                    enabled=bool(webhook.get("enabled")) if "enabled" in webhook else True,
                    timeout_s=max(1, min(30, _safe_int(webhook.get("timeout_s"), 5))),
                )

        return {"template": template, "webhook": webhook_result}

    async def run_template(
        self,
        *,
        template_id: str,
        payload_override: Mapping[str, Any] | None = None,
        dry_run: bool = False,
    ) -> dict[str, Any] | None:
        template = await self.get_template(template_id)
        if template is None:
            return None

        base_payload = template.get("payload")
        merged_payload = dict(base_payload) if isinstance(base_payload, Mapping) else {}
        override_payload = payload_override
        if isinstance(override_payload, Mapping):
            merged_payload.update(dict(override_payload))

        connector_id = _safe_string(template.get("connector_id"))
        action_id = _safe_string(template.get("action_id"))
        validation = await self.validate_job_payload(
            connector_id=connector_id,
            action_id=action_id,
            payload=merged_payload,
        )

        submitted = False
        job: dict[str, Any] | None = None
        if not bool(dry_run) and bool(validation.get("can_submit")):
            job = await self.create_job(
                connector_id=connector_id,
                action_id=action_id,
                payload=merged_payload,
                template_id=template_id,
            )
            submitted = True

        return {
            "template": template,
            "payload": merged_payload,
            "validation": validation,
            "dry_run": bool(dry_run),
            "submitted": bool(submitted),
            "job": job,
        }

    async def run_template_by_name(
        self,
        *,
        name: str,
        payload_override: Mapping[str, Any] | None = None,
        dry_run: bool = False,
    ) -> dict[str, Any] | None:
        template = await self.get_template_by_name(name)
        if template is None:
            return None
        template_id = _safe_string(template.get("template_id"))
        if not template_id:
            return None
        return await self.run_template(
            template_id=template_id,
            payload_override=payload_override,
            dry_run=dry_run,
        )

    async def get_favorite_template(
        self,
        *,
        name: str = "",
        tag: str = "",
    ) -> dict[str, Any] | None:
        preferred_name = _safe_string(name)
        if preferred_name:
            template = await self.get_template_by_name(preferred_name)
            if template is None:
                return None
            if not bool(template.get("favorite")):
                return None
            return template
        rows = await self.list_templates(limit=500, favorites_only=True, tag=tag)
        return rows[0] if rows else None

    async def run_favorite_template(
        self,
        *,
        name: str = "",
        tag: str = "",
        payload_override: Mapping[str, Any] | None = None,
        dry_run: bool = False,
    ) -> dict[str, Any] | None:
        template = await self.get_favorite_template(name=name, tag=tag)
        if template is None:
            return None
        template_id = _safe_string(template.get("template_id"))
        if not template_id:
            return None
        return await self.run_template(
            template_id=template_id,
            payload_override=payload_override,
            dry_run=dry_run,
        )

    async def cancel_job(self, job_id: str) -> dict[str, Any] | None:
        job = await self.store.get_job(job_id)
        if not job:
            return None
        if _safe_string(job.get("status")) in TERMINAL_STATES:
            return job
        process = self._processes.get(job_id)
        if process is not None and process.returncode is None:
            process.terminate()
            await self.store.add_event(job_id=job_id, kind="cancel", message="Termination requested.", data={})
        task = self._tasks.get(job_id)
        if task is not None and not task.done():
            task.cancel()
        return await self.store.get_job(job_id)

    async def retry_job(self, job_id: str) -> dict[str, Any] | None:
        existing = await self.store.get_job(job_id)
        if not existing:
            return None
        connector_id = _safe_string(existing.get("connector_id"))
        action_id = _safe_string(existing.get("action_id"))
        template_id = _safe_string(existing.get("template_id"))
        payload = existing.get("payload")
        body = dict(payload) if isinstance(payload, Mapping) else {}
        job = await self.create_job(
            connector_id=connector_id,
            action_id=action_id,
            payload=body,
            template_id=template_id,
        )
        await self.store.add_event(
            job_id=str(job.get("job_id") or ""),
            kind="retried",
            message=f"Retried from {job_id}.",
            data={"retried_from": job_id},
        )
        return job

    async def health_snapshot(
        self,
        *,
        include_detection: bool = True,
        jobs_limit: int = 200,
    ) -> dict[str, Any]:
        connectors = await self.list_connectors(include_detection=include_detection)
        installed_count = 0
        missing_count = 0
        for row in connectors:
            detection = row.get("detection") if isinstance(row, Mapping) else None
            installed = bool((detection or {}).get("installed")) if isinstance(detection, Mapping) else False
            if installed:
                installed_count += 1
            else:
                missing_count += 1

        jobs = await self.list_jobs(limit=jobs_limit)
        status_counts: dict[str, int] = {}
        for job in jobs:
            status = _safe_string(job.get("status")).lower() or "unknown"
            status_counts[status] = int(status_counts.get(status, 0)) + 1

        async with self._task_guard:
            active_tasks = sum(1 for task in self._tasks.values() if not task.done())
        active_processes = sum(1 for proc in self._processes.values() if proc.returncode is None)

        return {
            "connectors": {
                "total": len(connectors),
                "installed": installed_count,
                "missing": missing_count,
            },
            "jobs": {
                "visible": len(jobs),
                "status_counts": status_counts,
            },
            "runtime": {
                "active_tasks": int(active_tasks),
                "active_processes": int(active_processes),
            },
            "store_path": str(self.store.path),
        }

    def _recommend_rule_candidates(self) -> list[dict[str, Any]]:
        return [
            {
                "connector_id": "notion",
                "action_id": "sync_page",
                "keywords": ("notion", "wiki", "page", "docs"),
                "reason": "Notion sync selected from doc/wiki keywords.",
            },
            {
                "connector_id": "figma",
                "action_id": "pull_file",
                "keywords": ("figma", "design", "ui", "prototype"),
                "reason": "Figma pull selected from design/UI keywords.",
            },
            {
                "connector_id": "github",
                "action_id": "issue_to_task",
                "keywords": ("issue", "bug", "ticket", "github issue"),
                "reason": "GitHub issue sync selected from issue/ticket keywords.",
            },
            {
                "connector_id": "github",
                "action_id": "pr_risk_scan",
                "keywords": ("pull request", "pr", "risk", "review"),
                "reason": "GitHub PR risk scan selected from PR/review keywords.",
            },
            {
                "connector_id": "unity",
                "action_id": "build_player",
                "keywords": ("unity", "build", "player", "game build"),
                "reason": "Unity build selected from game build keywords.",
            },
            {
                "connector_id": "godot",
                "action_id": "export_release",
                "keywords": ("godot", "export", "release", "game export"),
                "reason": "Godot export selected from game export keywords.",
            },
            {
                "connector_id": "comfyui",
                "action_id": "queue_prompt",
                "keywords": ("comfyui", "image gen", "generate image", "diffusion"),
                "reason": "ComfyUI queue selected from image generation keywords.",
            },
            {
                "connector_id": "ffmpeg",
                "action_id": "transcode",
                "keywords": ("transcode", "convert video", "convert audio", "ffmpeg"),
                "reason": "FFmpeg transcode selected from media conversion keywords.",
            },
            {
                "connector_id": "opentimelineio",
                "action_id": "validate_timeline",
                "keywords": ("timeline", "otio", "edit timeline", "validate edit"),
                "reason": "OpenTimelineIO validation selected from timeline keywords.",
            },
        ]

    @staticmethod
    def _keyword_score(text: str, keywords: tuple[str, ...]) -> int:
        score = 0
        normalized = str(text or "").strip().lower()
        if not normalized:
            return 0
        for keyword in keywords:
            key = str(keyword or "").strip().lower()
            if not key:
                continue
            if re.search(rf"\b{re.escape(key)}\b", normalized):
                score += 3
            elif key in normalized:
                score += 1
        return score

    @staticmethod
    def _required_fields_for_action(
        connector_id: str,
        action_id: str,
        payload: Mapping[str, Any],
    ) -> tuple[list[str], list[str]]:
        cid = _safe_string(connector_id).lower()
        aid = _safe_string(action_id).lower()
        body = dict(payload or {})

        required: list[str] = []
        missing: list[str] = []

        def _is_present(name: str) -> bool:
            return bool(_safe_string(body.get(name)))

        def _require(field_name: str) -> None:
            required.append(field_name)
            if not _is_present(field_name):
                missing.append(field_name)

        if cid == "notion" and aid == "sync_page":
            _require("page_id")
        elif cid == "figma" and aid == "pull_file":
            _require("file_key")
        elif cid == "github" and aid == "issue_to_task":
            _require("repo")
            _require("issue_number")
        elif cid == "github" and aid == "pr_risk_scan":
            _require("repo")
            _require("pr_number")
        elif cid == "unity" and aid == "build_player":
            _require("project_path")
        elif cid == "godot" and aid == "export_release":
            _require("project_path")
        elif cid == "comfyui" and aid == "queue_prompt":
            required.append("workflow_json|workflow_file")
            if not (_is_present("workflow_json") or _is_present("workflow_file")):
                missing.append("workflow_json|workflow_file")
        elif cid == "ffmpeg" and aid == "transcode":
            _require("input_path")
            _require("output_path")
        elif cid == "opentimelineio" and aid == "validate_timeline":
            _require("input_path")
        return required, missing

    @staticmethod
    def _confidence_for_score(score: int) -> str:
        if int(score) >= 4:
            return "high"
        if int(score) >= 2:
            return "medium"
        return "low"

    async def validate_job_payload(
        self,
        *,
        connector_id: str,
        action_id: str,
        payload: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        body = dict(payload or {})
        preview = await self.preview_job(connector_id=connector_id, action_id=action_id, payload=body)
        required_fields, missing_fields = self._required_fields_for_action(connector_id, action_id, body)
        return {
            "connector_id": _safe_string(preview.get("connector_id")),
            "action_id": _safe_string(preview.get("action_id")),
            "required_fields": required_fields,
            "missing_fields": missing_fields,
            "can_submit": len(missing_fields) == 0,
            "runtime_ready": bool(preview.get("can_run")),
            "preview": preview,
        }

    def _scored_recommend_rules(self, goal: str) -> list[tuple[int, dict[str, Any]]]:
        rules = self._recommend_rule_candidates()
        scored: list[tuple[int, dict[str, Any]]] = []
        for rule in rules:
            connector_id = _safe_string(rule.get("connector_id"))
            action_id = _safe_string(rule.get("action_id"))
            connector = self.catalog.get(connector_id)
            if connector is None:
                continue
            action = connector.action_by_id(action_id)
            if action is None:
                continue
            score = self._keyword_score(goal, tuple(rule.get("keywords") or ()))
            scored.append((score, rule))
        scored.sort(key=lambda item: int(item[0]), reverse=True)
        return scored

    async def recommend_jobs(
        self,
        *,
        goal: str,
        payload: Mapping[str, Any] | None = None,
        limit: int = 3,
    ) -> list[dict[str, Any]]:
        text = _safe_string(goal)
        body = dict(payload or {})
        if not text:
            raise ValueError("goal is required")

        max_rows = max(1, min(10, _safe_int(limit, 3)))
        scored = self._scored_recommend_rules(text)

        default_rule = {
            "connector_id": "ffmpeg",
            "action_id": "version_check",
            "reason": "Defaulted to FFmpeg version check due to low keyword confidence.",
            "keywords": ("ffmpeg",),
        }
        selections: list[tuple[int, dict[str, Any]]] = []
        if not scored:
            selections.append((0, default_rule))
        elif int(scored[0][0]) <= 0:
            selections.append((0, default_rule))
            selections.extend(scored[: max(0, max_rows - 1)])
        else:
            selections.extend(scored[:max_rows])

        recommendations: list[dict[str, Any]] = []
        for score, selected in selections[:max_rows]:
            connector_id = _safe_string(selected.get("connector_id"))
            action_id = _safe_string(selected.get("action_id"))
            validation = await self.validate_job_payload(
                connector_id=connector_id,
                action_id=action_id,
                payload=body,
            )
            recommendation = {
                "goal": text,
                "connector_id": connector_id,
                "action_id": action_id,
                "reason": _safe_string(selected.get("reason")),
                "score": int(score),
                "confidence": self._confidence_for_score(int(score)),
                "required_fields": list(validation.get("required_fields") or []),
                "missing_fields": list(validation.get("missing_fields") or []),
                "can_submit": bool(validation.get("can_submit")),
                "runtime_ready": bool(validation.get("runtime_ready")),
                "preview": validation.get("preview") or {},
            }
            recommendations.append(recommendation)
        return recommendations

    async def recommend_job(
        self,
        *,
        goal: str,
        payload: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        recommendations = await self.recommend_jobs(goal=goal, payload=payload, limit=1)
        return recommendations[0] if recommendations else {}

    async def auto_create_job(
        self,
        *,
        goal: str,
        payload: Mapping[str, Any] | None = None,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        recommendation = await self.recommend_job(goal=goal, payload=payload)
        missing_fields = list(recommendation.get("missing_fields") or [])
        if len(missing_fields) > 0:
            raise ValueError(
                f"missing or invalid fields for recommended action: {', '.join(missing_fields) or 'validation failed'}"
            )
        if bool(dry_run):
            return {"recommendation": recommendation, "job": None, "dry_run": True}
        job = await self.create_job(
            connector_id=_safe_string(recommendation.get("connector_id")),
            action_id=_safe_string(recommendation.get("action_id")),
            payload=dict(payload or {}),
        )
        return {"recommendation": recommendation, "job": job, "dry_run": False}

    async def shutdown(self) -> None:
        async with self._task_guard:
            tasks = list(self._tasks.values())
            self._tasks.clear()
        for process in list(self._processes.values()):
            if process.returncode is None:
                with contextlib.suppress(Exception):
                    process.terminate()
        self._processes.clear()
        if tasks:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
        self.store.close()
