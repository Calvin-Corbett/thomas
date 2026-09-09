"""Job-bound Google Drive tools for Thomas Work."""

from __future__ import annotations

from typing import Any

from thomas.tools.base import Tool, ToolResult

_WORK_ONLY_ERROR = "Google Drive tools require a Work job with a bound Google Drive account."


class _WorkGoogleDriveTool(Tool):
    category = "google_drive"

    def __init__(
        self,
        name: str,
        description: str,
        properties: dict[str, Any],
        required: tuple[str, ...] = (),
    ) -> None:
        self.name = name
        self.description = description
        self.parameters = {
            "type": "object",
            "properties": {
                **properties,
                "work_account_id": {
                    "type": "string",
                    "description": "Bound Work account id; required when multiple Drive accounts match.",
                },
            },
            "required": list(required),
            "additionalProperties": False,
        }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        return ToolResult(ok=False, error=_WORK_ONLY_ERROR)


def get_tools() -> list[Tool]:
    text = {"type": "string"}
    maximum = {"type": "integer", "minimum": 1, "maximum": 100}
    return [
        _WorkGoogleDriveTool(
            "drive.list",
            "List files in the selected job-bound Google Drive account.",
            {"query": text, "folder_id": text, "max_results": maximum},
        ),
        _WorkGoogleDriveTool(
            "drive.get",
            "Read metadata for one file in the selected job-bound Google Drive account.",
            {"file_id": text},
            ("file_id",),
        ),
        _WorkGoogleDriveTool(
            "drive.search",
            "Search files in the selected job-bound Google Drive account.",
            {"query": text, "max_results": maximum},
            ("query",),
        ),
        _WorkGoogleDriveTool(
            "drive.create_folder",
            "Create a folder in the selected job-bound Google Drive account.",
            {"name": text, "parent_id": text},
            ("name",),
        ),
        _WorkGoogleDriveTool(
            "drive.share",
            "Share a Drive file from the selected job-bound Google Drive account.",
            {
                "file_id": text,
                "email": text,
                "role": {"type": "string", "enum": ["reader", "commenter", "writer"]},
            },
            ("file_id", "email"),
        ),
    ]


__all__ = ["get_tools"]
