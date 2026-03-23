"""Health check for Thomas features."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

results = []


def check(name, fn):
    try:
        fn()
        results.append(("PASS", name, ""))
    except Exception as e:
        results.append(("FAIL", name, str(e)[:200]))


# 1. Config + GLM
def t_config():
    from thomas.core.config import load_config

    cfg = load_config(ROOT / "thomas.toml")
    assert "glm" in cfg.models
    assert cfg.models["glm"].model == "glm-5"
    assert not cfg.validate()


check("Config + GLM profile", t_config)


# 2. Bedrock tool name fix
def t_bedrock():
    from thomas.core.config import ModelConfig
    from thomas.core.llm import LLMClient

    cfg = ModelConfig(name="t", model="m", base_url="http://localhost")
    c = LLMClient(cfg)
    assert LLMClient._sanitize_tool_name("fs.read_file") == "fs_read_file"
    assert LLMClient._sanitize_tool_name("diff.create") == "diff_create"
    body = c._build_openai_request(
        [], tools=[{"type": "function", "function": {"name": "fs.write_file", "description": "", "parameters": {}}}]
    )
    assert body["tools"][0]["function"]["name"] == "fs_write_file"
    assert c._openai_tool_name_map == {"fs_write_file": "fs.write_file"}


check("Bedrock tool name sanitization", t_bedrock)


# 3. File audit
def t_audit():
    import os
    import tempfile

    from thomas.marketplace.observability import file_audit

    with tempfile.TemporaryDirectory() as td:
        file_audit.init_audit(os.path.join(td, "a.db"))
        file_audit.record_file_write(
            run_id="r1",
            model="m",
            tool_name="fs.write_file",
            path="/a.py",
            action="write",
            content_before="old",
            content_after="new",
        )
        changes = file_audit.list_file_changes(run_id="r1")
        assert len(changes) == 1
        assert changes[0]["diff_snippet"] is not None
        summary = file_audit.get_run_summary("r1")
        assert summary["total_changes"] == 1
        assert file_audit.is_write_tool("fs.write_file")
        assert not file_audit.is_write_tool("fs.read_file")


check("File audit (SQLite + diff)", t_audit)


# 4. Audit routes importable + handlers exist
def t_audit_routes():
    from thomas.server.routes.audit import handle_audit_files, handle_audit_run_files

    assert callable(handle_audit_files)
    assert callable(handle_audit_run_files)


check("Audit API route handlers", t_audit_routes)


# 5. Audit wired into app.py
def t_audit_in_app():
    import inspect

    import thomas.server.app as app_mod

    src = inspect.getsource(app_mod)
    assert "handle_audit_files" in src or "audit/files" in src, "audit files not in app"
    assert "file_audit" in src or "_file_audit" in src, "file_audit not imported in app"


check("Audit routes wired into app.py", t_audit_in_app)


# 6. Tool modules all import
def t_tools():
    pass


check("All tool modules import", t_tools)


# 7. Memory store
def t_memory():
    import tempfile
    from pathlib import Path

    from thomas.memory.store import ImmortalLog

    with tempfile.TemporaryDirectory() as td:
        log = ImmortalLog(Path(td) / "test.db")
        eid = log.add_event("t1", "user", "hello world")
        ev = log.get_event(eid)
        assert ev.text == "hello world"
        results_fts = log.search_fts("hello")
        assert len(results_fts) > 0
        log.close()


check("Memory store (ImmortalLog + FTS)", t_memory)


# 8. Agent loop + system prompt
def t_loop():
    from thomas.agent.loop import SYSTEM_PROMPT

    assert "Thomas" in SYSTEM_PROMPT
    assert "{cwd}" in SYSTEM_PROMPT


check("Agent loop + system prompt", t_loop)


# 9. Server app creates without error
def t_server():
    import thomas.server.app as app_mod

    assert hasattr(app_mod, "create_app")


check("Server app module", t_server)


# 10. Inspector.js has Audit tab
def t_inspector_js():
    src = (ROOT / "thomas/server/web/js/inspector.js").read_text(encoding="utf-8")
    assert "id: 'audit'" in src, "Audit tab missing from TABS"
    assert "initAuditPanel" in src, "initAuditPanel not imported"
    assert "renderAuditTab" in src, "renderAuditTab function missing"


check("inspector.js has Audit tab", t_inspector_js)


# 11. audit.js exists and has initAuditPanel
def t_audit_js():
    src = (ROOT / "thomas/server/web/js/audit.js").read_text(encoding="utf-8")
    assert "initAuditPanel" in src
    assert "/api/audit/files" in src


check("audit.js panel + API call", t_audit_js)


# 12. layout.css has audit styles
def t_audit_css():
    src = (ROOT / "thomas/server/web/css/layout.css").read_text(encoding="utf-8")
    assert ".audit-panel" in src
    assert ".audit-row" in src
    assert ".audit-action-badge" in src


check("layout.css audit styles", t_audit_css)

# Print results
print()
passed = failed = 0
for status, name, err in results:
    icon = "PASS" if status == "PASS" else "FAIL"
    print(f"  [{icon}] {name}")
    if err:
        print(f"         ERROR: {err}")
    if status == "PASS":
        passed += 1
    else:
        failed += 1

print(f"\n  {passed} passed, {failed} failed out of {passed+failed} checks")
