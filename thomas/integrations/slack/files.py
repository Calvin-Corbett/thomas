"""File operations for Slack integration."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import aiohttp

from .integration import SlackAPIError, SlackConnectionError, SlackIntegration

log = logging.getLogger(__name__)


class SlackFiles:
    """Handle file operations in Slack."""

    def __init__(self, integration: SlackIntegration) -> None:
        """Initialize file operations.

        Args:
            integration: SlackIntegration instance
        """
        self._integration = integration

    async def upload_file(
        self,
        channels: list[str],
        file_path: str,
        title: str | None = None,
        initial_comment: str | None = None,
    ) -> dict[str, Any]:
        """Upload file to channels.

        Args:
            channels: List of channel IDs to share file to
            file_path: Path to local file to upload
            title: Optional file title (defaults to filename)
            initial_comment: Optional message to include with file

        Returns:
            File object with id, name, etc.

        Raises:
            SlackAPIError: On API errors
            ValueError: If file not found
        """
        if not channels:
            raise ValueError("At least one channel is required")

        path = Path(file_path)
        if not path.exists():
            raise ValueError(f"File not found: {file_path}")

        if not path.is_file():
            raise ValueError(f"Path is not a file: {file_path}")

        data = aiohttp.FormData()
        data.add_field("channels", ",".join(str(c).strip() for c in channels))

        if title:
            data.add_field("title", str(title).strip())
        else:
            data.add_field("title", path.name)

        if initial_comment:
            data.add_field("initial_comment", str(initial_comment).strip())

        with open(path, "rb") as f:
            data.add_field("file", f, filename=path.name)
            token = self._integration.get_token()
            if not token or not token.bot_token:
                raise SlackAPIError("Not authenticated")

            await self._integration._ensure_connected()
            headers = {"Authorization": f"Bearer {token.bot_token}"}

            try:
                async with self._integration._session.post(
                    "https://slack.com/api/files.upload",
                    data=data,
                    headers=headers,
                ) as resp:
                    result = await resp.json()

                    if not result.get("ok"):
                        error = result.get("error", "unknown error")
                        raise SlackAPIError(f"File upload failed: {error}")

                    log.info("File uploaded to %d channels", len(channels))
                    return result

            except aiohttp.ClientError as e:
                raise SlackConnectionError(f"Failed to upload file: {e}") from e

    async def list_files(
        self,
        channel: str | None = None,
        types: str | None = None,
        count: int = 100,
        page: int = 1,
    ) -> dict[str, Any]:
        """List files in channel or workspace.

        Args:
            channel: Channel ID to list files from (workspace if not specified)
            types: File types to include (e.g., 'images', 'pdfs', 'docs')
            count: Files per page
            page: Page number (1-indexed)

        Returns:
            Response with files array

        Raises:
            SlackAPIError: On API errors
        """
        params = {
            "count": max(1, min(1000, int(count))),
            "page": max(1, int(page)),
        }

        if channel:
            params["channel"] = str(channel).strip()

        if types:
            params["types"] = str(types).strip()

        result = await self._integration.execute("GET", "files.list", params=params)
        log.debug("Listed %d files", len(result.get("files", [])))
        return result

    async def get_file_info(self, file_id: str) -> dict[str, Any]:
        """Get file metadata.

        Args:
            file_id: Slack file ID

        Returns:
            File object with metadata

        Raises:
            SlackAPIError: On API errors
        """
        params = {"file": str(file_id).strip()}
        result = await self._integration.execute("GET", "files.info", params=params)
        log.debug("Got info for file %s", file_id)
        return result

    async def download_file(
        self,
        file_url: str,
        output_path: str,
    ) -> None:
        """Download file from Slack.

        Args:
            file_url: File URL from Slack API response
            output_path: Local path to save file

        Raises:
            SlackConnectionError: On download error
            ValueError: If path is invalid
        """
        if not str(file_url).strip():
            raise ValueError("file_url is required")

        out_path = Path(output_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)

        token = self._integration.get_token()
        if not token or not token.bot_token:
            raise SlackAPIError("Not authenticated")

        await self._integration._ensure_connected()
        headers = {"Authorization": f"Bearer {token.bot_token}"}

        try:
            async with self._integration._session.get(
                str(file_url).strip(),
                headers=headers,
            ) as resp:
                if resp.status != 200:
                    raise SlackConnectionError(f"Download failed with status {resp.status}")

                content = await resp.read()
                with open(out_path, "wb") as f:
                    f.write(content)

                log.info("File downloaded to %s", output_path)

        except aiohttp.ClientError as e:
            raise SlackConnectionError(f"Failed to download file: {e}") from e

    async def delete_file(self, file_id: str) -> dict[str, Any]:
        """Delete a file.

        Args:
            file_id: Slack file ID

        Returns:
            API response

        Raises:
            SlackAPIError: On API errors
        """
        data = {"file": str(file_id).strip()}
        result = await self._integration.execute("POST", "files.delete", data=data)
        log.info("Deleted file %s", file_id)
        return result

    async def get_file_url(self, file_id: str) -> str:
        """Get permanent file URL.

        Args:
            file_id: Slack file ID

        Returns:
            File URL

        Raises:
            SlackAPIError: If file not found
        """
        file_info = await self.get_file_info(file_id)
        file_obj = file_info.get("file", {})
        permalink = file_obj.get("permalink")
        if not permalink:
            raise SlackAPIError(f"Could not get URL for file {file_id}")
        return str(permalink)

    def get_file_name(self, file_obj: dict[str, Any]) -> str:
        """Get filename from file object.

        Args:
            file_obj: File object from API

        Returns:
            Filename
        """
        return str(file_obj.get("name", "unknown"))

    def get_file_size(self, file_obj: dict[str, Any]) -> int:
        """Get file size in bytes from file object.

        Args:
            file_obj: File object from API

        Returns:
            File size in bytes
        """
        try:
            return int(file_obj.get("size", 0))
        except (ValueError, TypeError):
            return 0

    def get_file_type(self, file_obj: dict[str, Any]) -> str:
        """Get file MIME type from file object.

        Args:
            file_obj: File object from API

        Returns:
            MIME type
        """
        return str(file_obj.get("mimetype", "application/octet-stream"))

    def get_file_preview(self, file_obj: dict[str, Any], max_lines: int = 10) -> str | None:
        """Get file preview text from file object.

        Args:
            file_obj: File object from API
            max_lines: Maximum preview lines to return

        Returns:
            Preview text or None if not available

        Raises:
            ValueError: If max_lines is invalid
        """
        if max_lines < 1:
            raise ValueError("max_lines must be >= 1")

        preview = file_obj.get("pretty_type", "")
        if not preview:
            preview = file_obj.get("preview")

        if isinstance(preview, str):
            lines = preview.split("\n")
            truncated = lines[:max_lines]
            return "\n".join(truncated)

        return None

    def is_image_file(self, file_obj: dict[str, Any]) -> bool:
        """Check if file is an image.

        Args:
            file_obj: File object from API

        Returns:
            True if file is image type
        """
        mimetype = self.get_file_type(file_obj)
        return mimetype.startswith("image/")

    def is_text_file(self, file_obj: dict[str, Any]) -> bool:
        """Check if file is text.

        Args:
            file_obj: File object from API

        Returns:
            True if file is text type
        """
        mimetype = self.get_file_type(file_obj)
        return mimetype.startswith("text/")

    def is_document_file(self, file_obj: dict[str, Any]) -> bool:
        """Check if file is a document (PDF, Word, etc).

        Args:
            file_obj: File object from API

        Returns:
            True if file is document type
        """
        mimetype = self.get_file_type(file_obj)
        doc_types = (
            "application/pdf",
            "application/msword",
            "application/vnd.openxmlformats-officedocument",
        )
        return any(mimetype.startswith(dt) for dt in doc_types)
