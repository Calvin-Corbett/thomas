"""Serialize RAG status without owning its index or persistence lifecycle."""

from typing import Any


def index_status(self: Any, pe: Any, root: Any, exts: Any, count: int) -> dict[str, Any]:
    with self._cv:
        pending = len(self._pending_updates)
        build_req = self._build_requested is not None
        building = self._build_running

    return {
        "persist_dir": str(self.persist_dir),
        "collection": self.collection_name,
        "model": self.model_name,
        "root_dir": str(root),
        "extensions": str(exts),
        "vector_count": count,
        "manifest_files": int(len(self._manifest.get("files", {}))),
        "fts_enabled": bool(self._fts_enabled),
        "build_running": bool(building),
        "build_requested": bool(build_req),
        "pending_updates": int(pending),
        "last_build_ts": pe.get_fact("rag.last_build_ts"),
        "last_build_error": pe.get_fact("rag.last_build_error"),
        "last_update": pe.get_fact("rag.last_update"),
        "last_update_action": pe.get_fact("rag.last_update_action"),
        "last_update_ts": pe.get_fact("rag.last_update_ts"),
    }
