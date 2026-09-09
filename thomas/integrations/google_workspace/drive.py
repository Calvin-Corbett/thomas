"""Google Drive API operations for Google Workspace integration.

Provides functions to list, search, upload, download, and manage files
through Google Drive API v3.
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)


class DriveError(Exception):
    """Raised when Google Drive API operations fail."""

    pass


class DriveAPI:
    """Wrapper for Google Drive API v3 operations using raw REST endpoints."""

    BASE_URL = "https://www.googleapis.com/drive/v3"

    def __init__(self, access_token: str) -> None:
        """Initialize Google Drive API client.

        Args:
            access_token: OAuth2 access token with Drive scope
        """
        self.access_token = access_token

    def _headers(self) -> dict[str, str]:
        """Get authorization headers for API requests."""
        return {
            "Authorization": f"Bearer {self.access_token}",
        }

    def _json_headers(self) -> dict[str, str]:
        """Get headers for JSON requests."""
        headers = self._headers()
        headers["Content-Type"] = "application/json"
        return headers

    async def list_files(
        self,
        session: Any,
        query: str = "",
        max_results: int = 50,
        folder_id: str | None = None,
        page_token: str | None = None,
    ) -> dict[str, Any]:
        """List files in Drive with optional query and folder filter.

        Args:
            session: aiohttp ClientSession
            query: Additional query string (e.g., "name contains 'report'")
            max_results: Maximum files to return (1-1000)
            folder_id: Filter to specific folder
            page_token: Token for paginated results

        Returns:
            Dict with files list and next page token
        """
        max_results = min(1000, max(1, max_results))
        q_parts = ["trashed=false"]

        if folder_id:
            q_parts.append(f"parents in '{folder_id}'")
        if query:
            q_parts.append(query)

        q = " and ".join(q_parts) if q_parts else ""

        params = {
            "q": q,
            "pageSize": max_results,
            "fields": "files(id,name,mimeType,size,createdTime,modifiedTime,webViewLink,parents),nextPageToken",
        }
        if page_token:
            params["pageToken"] = page_token

        url = f"{self.BASE_URL}/files"
        try:
            async with session.get(url, headers=self._headers(), params=params) as resp:
                if resp.status != 200:
                    error = await resp.text()
                    raise DriveError(f"List files failed: {resp.status} - {error}")
                data = await resp.json()
                return {
                    "files": [self._normalize_file(f) for f in data.get("files", [])],
                    "nextPageToken": data.get("nextPageToken"),
                }
        except DriveError:
            raise
        except Exception as e:
            raise DriveError(f"Failed to list files: {e}") from e

    async def get_file(
        self,
        session: Any,
        file_id: str,
    ) -> dict[str, Any]:
        """Get metadata for a specific file.

        Args:
            session: aiohttp ClientSession
            file_id: File ID

        Returns:
            Normalized file object
        """
        params = {
            "fields": "id,name,mimeType,size,createdTime,modifiedTime,webViewLink,owners,parents,description",
        }
        url = f"{self.BASE_URL}/files/{file_id}"
        try:
            async with session.get(url, headers=self._headers(), params=params) as resp:
                if resp.status != 200:
                    error = await resp.text()
                    raise DriveError(f"Get file failed: {resp.status} - {error}")
                data = await resp.json()
                return self._normalize_file(data)
        except DriveError:
            raise
        except Exception as e:
            raise DriveError(f"Failed to get file {file_id}: {e}") from e

    async def download_file(
        self,
        session: Any,
        file_id: str,
        output_path: str,
    ) -> dict[str, Any]:
        """Download file content to disk.

        Args:
            session: aiohttp ClientSession
            file_id: File ID
            output_path: Local path to save file

        Returns:
            Dict with download status and file info
        """
        # First get file metadata
        file_info = await self.get_file(session, file_id)

        # Download content
        url = f"{self.BASE_URL}/files/{file_id}?alt=media"
        try:
            async with session.get(url, headers=self._headers()) as resp:
                if resp.status != 200:
                    error = await resp.text()
                    raise DriveError(f"Download failed: {resp.status} - {error}")

                content = await resp.read()
                with open(output_path, "wb") as f:
                    f.write(content)

                return {
                    "success": True,
                    "fileId": file_id,
                    "filename": file_info.get("name"),
                    "path": output_path,
                    "size": len(content),
                }
        except DriveError:
            raise
        except Exception as e:
            raise DriveError(f"Failed to download file {file_id}: {e}") from e

    async def upload_file(
        self,
        session: Any,
        file_path: str,
        folder_id: str = "root",
        name: str | None = None,
    ) -> dict[str, Any]:
        """Upload a file to Drive.

        Args:
            session: aiohttp ClientSession
            file_path: Local file path
            folder_id: Destination folder ID (default "root")
            name: Custom name for uploaded file

        Returns:
            Uploaded file metadata
        """
        import os

        if not os.path.exists(file_path):
            raise DriveError(f"File not found: {file_path}")

        filename = name or os.path.basename(file_path)
        with open(file_path, "rb") as f:
            content = f.read()

        # Create multipart form data

        # Metadata
        metadata = {"name": filename, "parents": [folder_id]}
        import json

        metadata_json = json.dumps(metadata)

        # Build multipart body
        boundary = "===============boundary=="
        multipart_body = (
            f"--{boundary}\r\n"
            f"Content-Type: application/json; charset=UTF-8\r\n\r\n"
            f"{metadata_json}\r\n"
            f"--{boundary}\r\n"
            f"Content-Type: application/octet-stream\r\n\r\n"
        ).encode()
        multipart_body += content
        multipart_body += f"\r\n--{boundary}--\r\n".encode()

        headers = self._headers()
        headers["Content-Type"] = f"multipart/related; boundary={boundary}"

        url = f"{self.BASE_URL}/files?uploadType=multipart&fields=id,name,size,webViewLink"
        try:
            async with session.post(url, headers=headers, data=multipart_body) as resp:
                if resp.status not in (200, 201):
                    error = await resp.text()
                    raise DriveError(f"Upload failed: {resp.status} - {error}")
                data = await resp.json()
                return self._normalize_file(data)
        except DriveError:
            raise
        except Exception as e:
            raise DriveError(f"Failed to upload file: {e}") from e

    async def create_folder(
        self,
        session: Any,
        name: str,
        parent_id: str = "root",
    ) -> dict[str, Any]:
        """Create a new folder in Drive.

        Args:
            session: aiohttp ClientSession
            name: Folder name
            parent_id: Parent folder ID (default "root")

        Returns:
            Created folder metadata
        """
        payload = {
            "name": name,
            "mimeType": "application/vnd.google-apps.folder",
            "parents": [parent_id],
        }

        url = f"{self.BASE_URL}/files?fields=id,name,webViewLink"
        try:
            async with session.post(url, headers=self._json_headers(), json=payload) as resp:
                if resp.status != 201:
                    error = await resp.text()
                    raise DriveError(f"Create folder failed: {resp.status} - {error}")
                data = await resp.json()
                return self._normalize_file(data)
        except DriveError:
            raise
        except Exception as e:
            raise DriveError(f"Failed to create folder: {e}") from e

    async def share_file(
        self,
        session: Any,
        file_id: str,
        email: str,
        role: str = "reader",
    ) -> dict[str, Any]:
        """Share a file with another user.

        Args:
            session: aiohttp ClientSession
            file_id: File ID
            email: Email of person to share with
            role: Share role - "reader", "commenter", or "writer"

        Returns:
            Permission metadata
        """
        if role not in ("reader", "commenter", "writer"):
            raise DriveError(f"Invalid role: {role}. Must be reader, commenter, or writer")

        payload = {
            "role": role,
            "type": "user",
            "emailAddress": email,
        }

        url = f"{self.BASE_URL}/files/{file_id}/permissions?fields=id,emailAddress,role"
        try:
            async with session.post(url, headers=self._json_headers(), json=payload) as resp:
                if resp.status != 201:
                    error = await resp.text()
                    raise DriveError(f"Share file failed: {resp.status} - {error}")
                data = await resp.json()
                return {
                    "permissionId": data.get("id"),
                    "email": data.get("emailAddress"),
                    "role": data.get("role"),
                }
        except DriveError:
            raise
        except Exception as e:
            raise DriveError(f"Failed to share file {file_id}: {e}") from e

    async def search_files(
        self,
        session: Any,
        query: str,
        max_results: int = 50,
    ) -> dict[str, Any]:
        """Full-text search across Drive.

        Args:
            session: aiohttp ClientSession
            query: Search query (supports fullText and other operators)
            max_results: Maximum results to return

        Returns:
            Dict with matching files
        """
        search_query = f"fullText contains '{query}' and trashed=false"
        return await self.list_files(session, query=search_query, max_results=max_results)

    @staticmethod
    def _normalize_file(raw_file: dict[str, Any]) -> dict[str, Any]:
        """Normalize Google Drive API file response."""
        mime_type = raw_file.get("mimeType", "")
        is_folder = mime_type == "application/vnd.google-apps.folder"

        return {
            "fileId": raw_file.get("id"),
            "name": raw_file.get("name", ""),
            "mimeType": mime_type,
            "size": raw_file.get("size"),
            "isFolder": is_folder,
            "createdTime": raw_file.get("createdTime"),
            "modifiedTime": raw_file.get("modifiedTime"),
            "webViewLink": raw_file.get("webViewLink", ""),
            "parents": raw_file.get("parents", []),
            "owners": [o.get("emailAddress") for o in raw_file.get("owners", [])],
            "description": raw_file.get("description", ""),
        }
