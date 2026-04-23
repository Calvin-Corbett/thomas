"""Manifest file for tracking SSTable state and compaction progress."""

import json
import os
from pathlib import Path

from thomas.marketplace.kvstore._exceptions import ManifestError


class Manifest:
    """Tracks SSTable organization across levels.

    Format: JSON file with:
    - Version
    - Current sequence number
    - Level structure: {level: [file1, file2, ...]}
    - Compaction state
    """

    def __init__(self, dir_path: str):
        """Initialize manifest.

        Args:
            dir_path: Directory for manifest file
        """
        self.dir_path = Path(dir_path)
        self.dir_path.mkdir(parents=True, exist_ok=True)
        self.manifest_path = self.dir_path / "MANIFEST.json"

        # Load or create
        if self.manifest_path.exists():
            self._load()
        else:
            self._create()

    def _create(self) -> None:
        """Create new manifest."""
        self.version = 1
        self.sequence = 0
        self.levels: dict[int, list[str]] = {0: []}
        self.compacting_levels: set = set()
        self._write()

    def _load(self) -> None:
        """Load manifest from disk."""
        try:
            with open(self.manifest_path) as f:
                data = json.load(f)

            self.version = data.get("version", 1)
            self.sequence = data.get("sequence", 0)
            self.compacting_levels = set(data.get("compacting_levels", []))

            # Convert string keys to ints
            self.levels = {int(k): v for k, v in data.get("levels", {}).items()}
        except Exception as e:
            raise ManifestError(f"Failed to load manifest: {e}")

    def _write(self) -> None:
        """Write manifest to disk atomically."""
        try:
            # Write to temp file first
            temp_path = self.manifest_path.with_suffix(".tmp")
            with open(temp_path, "w") as f:
                data = {
                    "version": self.version,
                    "sequence": self.sequence,
                    "levels": {str(k): v for k, v in self.levels.items()},
                    "compacting_levels": list(self.compacting_levels),
                }
                json.dump(data, f, indent=2)

            # Atomic rename
            if os.name == "nt":  # Windows
                if self.manifest_path.exists():
                    self.manifest_path.unlink()
            os.rename(temp_path, self.manifest_path)

        except Exception as e:
            raise ManifestError(f"Failed to write manifest: {e}")

    def _refresh(self) -> None:
        """Refresh in-memory state from disk when manifest exists."""
        if self.manifest_path.exists():
            self._load()

    def next_sequence(self) -> int:
        """Get and increment sequence number.

        Returns:
            Next sequence number
        """
        seq = self.sequence
        self.sequence += 1
        self._write()
        return seq

    def add_sstable(self, level: int, filename: str) -> None:
        """Add SSTable to a level.

        Args:
            level: Level number (0 = L0, etc.)
            filename: SSTable filename

        Raises:
            ValueError: If level is invalid
        """
        if level < 0:
            raise ValueError("Level must be >= 0")

        if level not in self.levels:
            self.levels[level] = []

        self.levels[level].append(filename)
        self._write()

    def remove_sstable(self, level: int, filename: str) -> None:
        """Remove SSTable from a level.

        Args:
            level: Level number
            filename: SSTable filename

        Raises:
            ValueError: If file not found
        """
        if level not in self.levels or filename not in self.levels[level]:
            raise ValueError(f"SSTable {filename} not found at level {level}")

        self.levels[level].remove(filename)
        self._write()

    def get_level_files(self, level: int) -> list[str]:
        """Get all SSTables at a level.

        Args:
            level: Level number

        Returns:
            List of filenames
        """
        self._refresh()
        return list(self.levels.get(level, []))

    def set_level_files(self, level: int, files: list[str]) -> None:
        """Set the complete file list for a level.

        Args:
            level: Level number
            files: List of filenames
        """
        self.levels[level] = files
        self._write()

    def mark_compacting(self, level: int) -> None:
        """Mark a level as compacting.

        Args:
            level: Level number
        """
        self.compacting_levels.add(level)
        self._write()

    def unmark_compacting(self, level: int) -> None:
        """Unmark a level as compacting.

        Args:
            level: Level number
        """
        self.compacting_levels.discard(level)
        self._write()

    def is_compacting(self, level: int) -> bool:
        """Check if level is being compacted.

        Args:
            level: Level number

        Returns:
            True if currently compacting
        """
        self._refresh()
        return level in self.compacting_levels

    def get_all_files(self) -> list[str]:
        """Get all SSTable files across all levels.

        Returns:
            List of filenames
        """
        self._refresh()
        result = []
        for files in self.levels.values():
            result.extend(files)
        return result

    def clear_level(self, level: int) -> None:
        """Clear all files from a level.

        Args:
            level: Level number
        """
        if level in self.levels:
            self.levels[level] = []
            self._write()

    def max_level(self) -> int:
        """Get highest level in use.

        Returns:
            Maximum level number, or -1 if no levels
        """
        self._refresh()
        if not self.levels:
            return -1
        return max(self.levels.keys())
