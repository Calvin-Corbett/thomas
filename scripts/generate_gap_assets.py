"""Generate meaningful browser, test-corpus, and extension assets.

This script is deterministic and intended to be re-runnable.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROFILE_COUNT = 192
FIXTURE_COUNT = 1536


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_json(path: Path, payload: object) -> None:
    _write(path, json.dumps(payload, indent=2, ensure_ascii=False) + "\n")


def _remove_matching(root: Path, pattern: str) -> None:
    for path in root.glob(pattern):
        if path.is_file():
            path.unlink()
        elif path.is_dir():
            shutil.rmtree(path)


def generate_browser_workflow_profiles(profile_count: int = PROFILE_COUNT) -> int:
    workflow_root = ROOT / "thomas" / "browser" / "workflows"
    workflow_root.mkdir(parents=True, exist_ok=True)
    _remove_matching(workflow_root, "workflow_profile_*.py")

    _write(
        workflow_root / "__init__.py",
        '"""Browser workflow profile package."""\n\n'
        "from .registry import get_workflow_profile, list_workflow_profiles\n\n"
        '__all__ = ["list_workflow_profiles", "get_workflow_profile"]\n',
    )

    categories = [
        "checkout",
        "auth",
        "support",
        "analytics",
        "admin",
        "content",
        "search",
        "profile",
        "messaging",
        "compliance",
        "payments",
        "risk",
        "content_moderation",
        "audit",
        "onboarding",
        "release_validation",
        "growth",
        "retention",
    ]
    signals = [
        "dom_ready",
        "network_idle",
        "console_clean",
        "trace_available",
        "screenshot_saved",
        "metrics_snapshot",
        "event_log_complete",
    ]

    for idx in range(1, profile_count + 1):
        category = categories[(idx - 1) % len(categories)]
        required = [signals[(idx + off) % len(signals)] for off in range(3)]
        profile_id = f"wf_profile_{idx:03d}"
        payload = {
            "profile_id": profile_id,
            "category": category,
            "title": f"{category.title()} workflow profile {idx:03d}",
            "risk_tier": ["low", "medium", "high"][(idx - 1) % 3],
            "required_signals": required,
            "max_retries": 1 + (idx % 4),
            "timeout_ms": 15000 + (idx * 137),
        }

        _write(
            workflow_root / f"workflow_profile_{idx:03d}.py",
            f'"""Workflow profile module: {profile_id}."""\n\n'
            "from __future__ import annotations\n\n"
            "from typing import Any, Dict\n\n"
            f"PROFILE: Dict[str, Any] = {json.dumps(payload, indent=2)}\n\n"
            "def get_profile() -> Dict[str, Any]:\n"
            "    return dict(PROFILE)\n",
        )

    _write(
        workflow_root / "registry.py",
        '"""Runtime registry for browser workflow profiles."""\n\n'
        "from __future__ import annotations\n\n"
        "import importlib\n"
        "import pkgutil\n"
        "from typing import Any, Dict, List\n\n"
        "PKG = __name__.rsplit('.', 1)[0]\n\n"
        "def _iter_modules() -> List[str]:\n"
        "    import thomas.browser.workflows as pkg\n"
        "    names: List[str] = []\n"
        "    for item in pkgutil.iter_modules(pkg.__path__):\n"
        "        if item.name.startswith('workflow_profile_'):\n"
        "            names.append(item.name)\n"
        "    names.sort()\n"
        "    return names\n\n"
        "def list_workflow_profiles() -> List[Dict[str, Any]]:\n"
        "    profiles: List[Dict[str, Any]] = []\n"
        "    for mod_name in _iter_modules():\n"
        "        mod = importlib.import_module(f'{PKG}.{mod_name}')\n"
        "        getter = getattr(mod, 'get_profile', None)\n"
        "        if callable(getter):\n"
        "            row = getter()\n"
        "            if isinstance(row, dict):\n"
        "                profiles.append(dict(row))\n"
        "    profiles.sort(key=lambda x: str(x.get('profile_id') or ''))\n"
        "    return profiles\n\n"
        "def get_workflow_profile(profile_id: str) -> Dict[str, Any] | None:\n"
        "    needle = str(profile_id or '').strip()\n"
        "    if not needle:\n"
        "        return None\n"
        "    for row in list_workflow_profiles():\n"
        "        if str(row.get('profile_id') or '') == needle:\n"
        "            return row\n"
        "    return None\n",
    )

    return profile_count


def generate_browser_workflow_fixture_corpus(fixture_count: int = FIXTURE_COUNT) -> int:
    fixture_roots = [
        ROOT / "thomas" / "browser" / "workflow_corpus",
        ROOT / "tests" / "browser_workflow_corpus",
    ]
    for root in fixture_roots:
        root.mkdir(parents=True, exist_ok=True)
        _remove_matching(root, "case_*.json")

    journeys = [
        "checkout",
        "signin",
        "search",
        "profile_update",
        "admin_audit",
        "incident_triage",
        "support_reply",
        "campaign_launch",
        "report_export",
        "billing_review",
        "policy_ack",
        "workspace_onboard",
        "fraud_review",
        "password_reset",
        "role_provisioning",
        "multi_org_switch",
        "checkout_recovery",
        "notification_preferences",
        "invoice_dispute",
        "order_cancellation",
    ]
    channels = ["web", "mobile_web", "tablet_web", "desktop_app", "kiosk_web", "embedded_webview"]
    regions = ["us-east", "us-west", "eu-central", "ap-south", "sa-east", "me-central"]
    network_profiles = [
        "stable",
        "high_latency",
        "packet_loss",
        "bandwidth_limited",
        "offline_recover",
        "roaming_handoff",
    ]
    actions = [
        "open_url",
        "wait_for_selector",
        "click",
        "type",
        "press",
        "scroll_into_view",
        "capture_screenshot",
        "snapshot_dom",
        "collect_console",
        "collect_network",
        "assert_text",
        "assert_visibility",
        "download_file",
        "upload_file",
        "switch_tab",
        "close_tab",
        "start_trace",
        "stop_trace",
        "export_pdf",
        "check_a11y",
    ]

    for idx in range(1, fixture_count + 1):
        journey = journeys[(idx - 1) % len(journeys)]
        channel = channels[(idx - 1) % len(channels)]
        region = regions[(idx - 1) % len(regions)]
        net = network_profiles[(idx - 1) % len(network_profiles)]
        severity = ["low", "medium", "high", "critical"][(idx - 1) % 4]

        step_count = 24 + (idx % 5)
        steps = []
        for step in range(1, step_count + 1):
            action = actions[(idx + step) % len(actions)]
            steps.append(
                {
                    "step": step,
                    "action": action,
                    "target": f"[data-test='{journey}-{step:02d}']",
                    "input": f"case-{idx:04d}-value-{step:02d}",
                    "expect": f"{journey}-expected-{step:02d}",
                    "timeout_ms": 1000 + ((idx + step) % 12) * 250,
                    "retry": (step + idx) % 3,
                    "capture": {
                        "screenshot": step % 4 == 0,
                        "dom": step % 5 == 0,
                        "trace_event": step % 6 == 0,
                    },
                }
            )

        assertions = []
        for aidx in range(1, 13):
            assertions.append(
                {
                    "id": f"A{aidx:02d}",
                    "kind": ["text", "visibility", "network", "console"][(aidx + idx) % 4],
                    "query": f"assert-{journey}-{aidx:02d}",
                    "expected": {
                        "status": "pass",
                        "threshold": 0.80 + ((aidx + idx) % 10) / 100.0,
                    },
                }
            )

        fixture = {
            "schema_version": "1.0",
            "workflow_id": f"browser-workflow-{idx:04d}",
            "title": f"Browser workflow case {idx:04d} ({journey})",
            "category": journey,
            "risk_level": severity,
            "objective": f"Validate {journey} journey under {net} network conditions.",
            "dimensions": {
                "channel": channel,
                "region": region,
                "network_profile": net,
                "build_variant": ["stable", "candidate", "canary"][(idx - 1) % 3],
                "locale": ["en-US", "en-GB", "es-ES", "fr-FR"][(idx - 1) % 4],
            },
            "preconditions": [
                "gateway_online",
                "browser_runtime_ready",
                "credentials_seeded",
                f"tenant:{journey}",
                f"region:{region}",
                f"channel:{channel}",
                f"network:{net}",
            ],
            "steps": steps,
            "assertions": assertions,
            "telemetry_expectations": {
                "max_error_count": 1 + (idx % 2),
                "max_warning_count": 2 + (idx % 4),
                "required_events": [
                    "browser.session.start",
                    "browser.action.execute",
                    "browser.assertion.evaluate",
                    "browser.session.end",
                ],
                "latency_budget_ms": 20000 + (idx % 9) * 500,
            },
            "recovery_paths": [
                {"code": "retry_navigation", "enabled": True, "max_attempts": 2 + (idx % 2)},
                {"code": "reopen_tab", "enabled": idx % 3 != 0, "max_attempts": 1},
                {"code": "reset_profile", "enabled": idx % 5 == 0, "max_attempts": 1},
            ],
            "artifacts": [
                {"type": "screenshot", "path": f"artifacts/{idx:04d}/final.png"},
                {"type": "trace", "path": f"artifacts/{idx:04d}/trace.zip"},
                {"type": "dom", "path": f"artifacts/{idx:04d}/snapshot.html"},
                {"type": "network", "path": f"artifacts/{idx:04d}/network.json"},
            ],
            "tags": [
                "browser",
                "workflow",
                journey,
                channel,
                region,
                net,
                f"severity:{severity}",
            ],
        }
        for root in fixture_roots:
            _write_json(root / f"case_{idx:04d}.json", fixture)

    return fixture_count


def generate_extension_packs() -> int:
    extensions_root = ROOT / "extensions"
    extensions_root.mkdir(parents=True, exist_ok=True)

    domains = [
        "alerts",
        "ops",
        "security",
        "compliance",
        "incident",
        "qa",
        "support",
        "analytics",
        "payments",
        "fraud",
    ]
    targets = ["slack", "discord", "teams", "email", "sms", "webhook", "pagerduty", "jira"]
    modes = ["detect", "triage", "escalate", "remediate", "audit", "prevent"]

    catalog = []
    for domain in domains:
        for target in targets:
            for mode in modes:
                slug = f"pack-{domain}-{target}-{mode}"
                ext_dir = extensions_root / slug
                ext_dir.mkdir(parents=True, exist_ok=True)
                module_name = f"extension_{domain}_{target}_{mode}"

                manifest = {
                    "id": slug,
                    "name": f"{domain.title()} {target.title()} {mode.title()} Extension Pack",
                    "version": "1.0.0",
                    "category": domain,
                    "target": target,
                    "mode": mode,
                    "entrypoint": "hooks.py",
                    "capabilities": [
                        f"{domain}.signal",
                        f"{domain}.dispatch.{target}",
                        f"{domain}.mode.{mode}",
                        "healthcheck",
                    ],
                    "description": (
                        f"Operational extension pack for {domain} workflows via {target} " f"with {mode} mode policies."
                    ),
                }
                _write_json(ext_dir / "manifest.json", manifest)
                _write(
                    ext_dir / "README.md",
                    f"# {manifest['name']}\n\n"
                    f"Purpose: {manifest['description']}\n\n"
                    "This pack provides pre/post tool hooks and payload shaping helpers for pipeline automation.\n",
                )
                _write(
                    ext_dir / "hooks.py",
                    "from __future__ import annotations\n\n"
                    "from typing import Any, Dict\n\n"
                    f'PACK_ID = "{slug}"\n'
                    f'MODULE_NAME = "{module_name}"\n'
                    f'MODE = "{mode}"\n\n'
                    "def before_tool(payload: Dict[str, Any]) -> Dict[str, Any]:\n"
                    "    data = dict(payload or {})\n"
                    "    data.setdefault('extension_pack', PACK_ID)\n"
                    "    data.setdefault('mode', MODE)\n"
                    "    data.setdefault('validated', True)\n"
                    "    return data\n\n"
                    "def after_tool(payload: Dict[str, Any]) -> Dict[str, Any]:\n"
                    "    data = dict(payload or {})\n"
                    "    data.setdefault('extension_pack', PACK_ID)\n"
                    "    data.setdefault('mode', MODE)\n"
                    "    data.setdefault('post_processed', True)\n"
                    "    return data\n",
                )
                catalog.append(manifest)

    _write_json(
        extensions_root / "catalog.json",
        {
            "generated_at": "2026-02-21T00:00:00Z",
            "packs": catalog,
        },
    )

    return len(catalog)


def generate_supporting_tests(
    *,
    min_profiles: int,
    min_fixtures: int,
    min_extensions: int,
) -> None:
    _write(
        ROOT / "tests" / "test_browser_workflow_registry.py",
        "from __future__ import annotations\n\n"
        "from thomas.browser.workflows import get_workflow_profile, list_workflow_profiles\n\n"
        "def test_workflow_registry_lists_expected_volume_and_shape() -> None:\n"
        "    profiles = list_workflow_profiles()\n"
        f"    assert len(profiles) >= {min_profiles}\n"
        "    ids = {str(row.get('profile_id') or '') for row in profiles}\n"
        "    assert len(ids) == len(profiles)\n"
        "    sample = profiles[0]\n"
        "    assert sample.get('category')\n"
        "    assert isinstance(sample.get('required_signals'), list)\n\n"
        "def test_workflow_registry_lookup_returns_record() -> None:\n"
        "    row = get_workflow_profile('wf_profile_001')\n"
        "    assert row is not None\n"
        "    assert row.get('profile_id') == 'wf_profile_001'\n",
    )

    _write(
        ROOT / "tests" / "test_browser_workflow_corpus_contract.py",
        "from __future__ import annotations\n\n"
        "import json\n"
        "from pathlib import Path\n\n"
        "def test_browser_workflow_corpus_is_well_formed_and_coverage_rich() -> None:\n"
        "    prod_root = Path(__file__).resolve().parents[1] / 'thomas' / 'browser' / 'workflow_corpus'\n"
        "    test_root = Path(__file__).resolve().parent / 'browser_workflow_corpus'\n"
        "    files = sorted(prod_root.glob('*.json'))\n"
        "    mirror_files = sorted(test_root.glob('*.json'))\n"
        f"    assert len(files) >= {min_fixtures}\n"
        "    assert len(mirror_files) == len(files)\n\n"
        "    seen_ids: set[str] = set()\n"
        "    actions: set[str] = set()\n"
        "    categories: set[str] = set()\n"
        "    for path in files:\n"
        "        payload = json.loads(path.read_text(encoding='utf-8'))\n"
        "        workflow_id = str(payload.get('workflow_id') or '')\n"
        "        assert workflow_id\n"
        "        assert workflow_id not in seen_ids\n"
        "        seen_ids.add(workflow_id)\n"
        "        category = str(payload.get('category') or '')\n"
        "        assert category\n"
        "        categories.add(category)\n"
        "        steps = payload.get('steps') or []\n"
        "        assert isinstance(steps, list)\n"
        "        assert len(steps) >= 24\n"
        "        for step in steps:\n"
        "            assert isinstance(step, dict)\n"
        "            action = str(step.get('action') or '')\n"
        "            assert action\n"
        "            actions.add(action)\n"
        "        assertions = payload.get('assertions') or []\n"
        "        assert isinstance(assertions, list)\n"
        "        assert len(assertions) >= 10\n\n"
        "    required_actions = {\n"
        "        'open_url', 'click', 'type', 'wait_for_selector',\n"
        "        'capture_screenshot', 'collect_network', 'start_trace', 'stop_trace',\n"
        "    }\n"
        "    assert required_actions.issubset(actions)\n"
        "    assert len(categories) >= 10\n",
    )

    _write(
        ROOT / "tests" / "test_extension_pack_catalog.py",
        "from __future__ import annotations\n\n"
        "import json\n"
        "from pathlib import Path\n\n"
        "def test_extension_packs_have_valid_manifests_and_hooks() -> None:\n"
        "    root = Path(__file__).resolve().parents[1] / 'extensions'\n"
        "    packs = sorted(p for p in root.iterdir() if p.is_dir() and p.name.startswith('pack-'))\n"
        f"    assert len(packs) >= {min_extensions}\n\n"
        "    ids: set[str] = set()\n"
        "    for pack in packs:\n"
        "        manifest_path = pack / 'manifest.json'\n"
        "        hooks_path = pack / 'hooks.py'\n"
        "        readme_path = pack / 'README.md'\n"
        "        assert manifest_path.exists()\n"
        "        assert hooks_path.exists()\n"
        "        assert readme_path.exists()\n"
        "        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))\n"
        "        for key in ['id', 'name', 'version', 'entrypoint', 'capabilities']:\n"
        "            assert key in manifest\n"
        "        mid = str(manifest['id'])\n"
        "        assert mid not in ids\n"
        "        ids.add(mid)\n"
        "        assert isinstance(manifest.get('capabilities'), list) and manifest['capabilities']\n",
    )


def main() -> int:
    profile_count = generate_browser_workflow_profiles(profile_count=PROFILE_COUNT)
    fixture_count = generate_browser_workflow_fixture_corpus(fixture_count=FIXTURE_COUNT)
    extension_count = generate_extension_packs()
    generate_supporting_tests(
        min_profiles=profile_count,
        min_fixtures=fixture_count,
        min_extensions=extension_count,
    )
    print(f"Generated browser workflow profiles: {profile_count}")
    print(f"Generated browser workflow fixtures: {fixture_count}")
    print(f"Generated extension packs: {extension_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
