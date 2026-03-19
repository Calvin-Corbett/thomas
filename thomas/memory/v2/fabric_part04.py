class MemoryFabricCompat:
    """Compatibility shim for older Thomas memory call sites."""

    def __init__(self, fabric: MemoryFabricV2):
        self.fabric = fabric

    @classmethod
    def from_root_path(cls, root_path: str) -> MemoryFabricCompat:
        return cls(MemoryFabricV2(root_path=root_path))

    def ingest_message(
        self, thread_id: str, role: str, content: str, ts_ms: int | None = None, base_salience: float = 1.0
    ) -> int:
        return self.fabric.ingest_episode(
            thread_id=thread_id, role=role, content=content, ts_ms=ts_ms, base_salience=base_salience
        )

    def build_memory_pack(self, thread_id: str, query: str, budget_tokens: int = 800) -> tuple[str, str]:
        res = self.fabric.retrieve(thread_id=thread_id, query=query, budget_tokens=budget_tokens)
        return res.pack_text, res.trace_id
