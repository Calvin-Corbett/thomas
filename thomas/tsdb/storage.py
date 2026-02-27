"""Time-series storage engine for the Thomas TSDB.

Implements chunk-based storage with columnar layout, delta encoding,
compression, and disk persistence.
"""

import json
import struct
from dataclasses import asdict, dataclass
from pathlib import Path

from ._types import DataPoint
from .compression import DeltaOfDeltaEncoder, XORFloatCompressor


@dataclass
class ChunkMetadata:
    """Metadata for a chunk."""

    chunk_id: int
    metric_name: str
    start_time: int
    end_time: int
    point_count: int
    compressed_size: int
    original_size: int
    tags: dict[str, str]


class Chunk:
    """Represents a time chunk with columnar storage.

    Stores timestamps in one column and values in another,
    using delta encoding and compression.
    """

    def __init__(
        self,
        chunk_id: int,
        metric_name: str,
        start_time: int,
        end_time: int,
        tags: dict[str, str] = None,
        compression_enabled: bool = True,
    ) -> None:
        """Initialize a chunk.

        Args:
            chunk_id: Unique chunk identifier
            metric_name: Name of the metric
            start_time: Start time in milliseconds
            end_time: End time in milliseconds
            tags: Optional tags
            compression_enabled: Whether to compress data
        """
        self.chunk_id = chunk_id
        self.metric_name = metric_name
        self.start_time = start_time
        self.end_time = end_time
        self.tags = tags or {}
        self.compression_enabled = compression_enabled

        self.timestamps: list[int] = []
        self.values: list[float] = []

        self.compressed_data: bytes | None = None
        self.metadata: ChunkMetadata | None = None

    def add_point(self, point: DataPoint) -> None:
        """Add a data point to the chunk.

        Args:
            point: DataPoint to add

        Raises:
            ValueError: If point is outside time range
        """
        if not (self.start_time <= point.timestamp < self.end_time):
            raise ValueError(
                f"Point timestamp {point.timestamp} outside chunk range " f"[{self.start_time}, {self.end_time})"
            )

        self.timestamps.append(point.timestamp)
        self.values.append(float(point.value))

    def add_points(self, points: list[DataPoint]) -> None:
        """Add multiple data points to the chunk.

        Args:
            points: List of DataPoints
        """
        for point in points:
            self.add_point(point)

    def compress(self) -> None:
        """Compress chunk data using delta encoding and XOR compression."""
        if not self.compression_enabled or not self.timestamps:
            return

        # Get original size before compression
        original_size = len(self.timestamps) * 16  # 8 bytes timestamp + 8 bytes value

        # Compress timestamps with delta-of-delta
        compressed_ts = DeltaOfDeltaEncoder.encode(self.timestamps)

        # Compress values with XOR compression
        compressed_vals = XORFloatCompressor.encode(self.values)

        # Store header with sizes
        header = struct.pack(">HH", len(compressed_ts), len(compressed_vals))

        self.compressed_data = header + compressed_ts + compressed_vals

        # Create metadata
        self.metadata = ChunkMetadata(
            chunk_id=self.chunk_id,
            metric_name=self.metric_name,
            start_time=self.start_time,
            end_time=self.end_time,
            point_count=len(self.timestamps),
            compressed_size=len(self.compressed_data),
            original_size=original_size,
            tags=self.tags,
        )

    def decompress(self) -> None:
        """Decompress chunk data."""
        if not self.compressed_data:
            return

        offset = 0

        # Read header
        ts_size, vals_size = struct.unpack(">HH", self.compressed_data[offset : offset + 4])
        offset += 4

        # Decompress timestamps
        compressed_ts = self.compressed_data[offset : offset + ts_size]
        self.timestamps = DeltaOfDeltaEncoder.decode(compressed_ts)
        offset += ts_size

        # Decompress values
        compressed_vals = self.compressed_data[offset : offset + vals_size]
        self.values = XORFloatCompressor.decode(compressed_vals)

    def get_points(self) -> list[DataPoint]:
        """Get all points from the chunk.

        Returns:
            List of DataPoints
        """
        if self.compressed_data and not self.timestamps:
            self.decompress()

        points = []
        for ts, val in zip(self.timestamps, self.values):
            points.append(DataPoint(timestamp=ts, value=val, tags=self.tags.copy()))

        return points

    @property
    def point_count(self) -> int:
        """Get number of points in chunk."""
        return len(self.timestamps)

    @property
    def compression_ratio(self) -> float:
        """Get compression ratio if compressed."""
        if not self.metadata or self.metadata.original_size == 0:
            return 1.0
        return self.metadata.compressed_size / self.metadata.original_size


class StorageManager:
    """Manages chunk storage and retrieval from disk.

    Handles writing chunks to disk and loading them back.
    """

    def __init__(self, storage_path: str) -> None:
        """Initialize the storage manager.

        Args:
            storage_path: Root path for storage
        """
        self.storage_path = Path(storage_path)
        self.storage_path.mkdir(parents=True, exist_ok=True)
        self.chunks_dir = self.storage_path / "chunks"
        self.chunks_dir.mkdir(exist_ok=True)
        self.index_file = self.storage_path / "chunk_index.json"

    def save_chunk(self, chunk: Chunk) -> None:
        """Save a chunk to disk.

        Args:
            chunk: Chunk to save

        Raises:
            ValueError: If chunk not compressed
        """
        if chunk.compressed_data is None:
            raise ValueError("Chunk must be compressed before saving")

        # Prepare chunk data
        chunk_file = self.chunks_dir / f"chunk_{chunk.chunk_id}.bin"

        # Write header: metric_name length, metric_name, metadata as JSON, compressed data
        metric_name = chunk.metric_name.encode("utf-8")
        header = struct.pack(">H", len(metric_name)) + metric_name

        # Write metadata
        metadata_json = json.dumps(asdict(chunk.metadata)).encode("utf-8")
        header += struct.pack(">I", len(metadata_json)) + metadata_json

        with open(chunk_file, "wb") as f:
            f.write(header)
            f.write(chunk.compressed_data)

        # Update index
        self._update_index(chunk)

    def load_chunk(self, chunk_id: int) -> Chunk | None:
        """Load a chunk from disk.

        Args:
            chunk_id: ID of chunk to load

        Returns:
            Loaded Chunk or None if not found
        """
        chunk_file = self.chunks_dir / f"chunk_{chunk_id}.bin"

        if not chunk_file.exists():
            return None

        with open(chunk_file, "rb") as f:
            # Read metric name
            metric_len = struct.unpack(">H", f.read(2))[0]
            metric_name = f.read(metric_len).decode("utf-8")

            # Read metadata
            metadata_len = struct.unpack(">I", f.read(4))[0]
            metadata_json = f.read(metadata_len).decode("utf-8")
            metadata_dict = json.loads(metadata_json)

            # Read compressed data
            compressed_data = f.read()

        # Reconstruct chunk
        chunk = Chunk(
            chunk_id=chunk_id,
            metric_name=metric_name,
            start_time=metadata_dict["start_time"],
            end_time=metadata_dict["end_time"],
            tags=metadata_dict["tags"],
            compression_enabled=True,
        )
        chunk.compressed_data = compressed_data

        return chunk

    def delete_chunk(self, chunk_id: int) -> None:
        """Delete a chunk from disk.

        Args:
            chunk_id: ID of chunk to delete
        """
        chunk_file = self.chunks_dir / f"chunk_{chunk_id}.bin"
        if chunk_file.exists():
            chunk_file.unlink()

        # Update index
        self._remove_from_index(chunk_id)

    def list_chunks(self) -> list[int]:
        """List all chunk IDs.

        Returns:
            List of chunk IDs
        """
        chunk_ids = []
        for chunk_file in self.chunks_dir.glob("chunk_*.bin"):
            chunk_id = int(chunk_file.stem.split("_")[1])
            chunk_ids.append(chunk_id)
        return sorted(chunk_ids)

    def _update_index(self, chunk: Chunk) -> None:
        """Update the chunk index file.

        Args:
            chunk: Chunk to index
        """
        index = {}
        if self.index_file.exists():
            with open(self.index_file) as f:
                index = json.load(f)

        if chunk.metadata:
            index[str(chunk.chunk_id)] = {
                "metric_name": chunk.metric_name,
                "start_time": chunk.start_time,
                "end_time": chunk.end_time,
                "point_count": chunk.metadata.point_count,
            }

            with open(self.index_file, "w") as f:
                json.dump(index, f)

    def _remove_from_index(self, chunk_id: int) -> None:
        """Remove chunk from index.

        Args:
            chunk_id: ID to remove
        """
        if not self.index_file.exists():
            return

        with open(self.index_file) as f:
            index = json.load(f)

        if str(chunk_id) in index:
            del index[str(chunk_id)]

            with open(self.index_file, "w") as f:
                json.dump(index, f)


class MemoryBuffer:
    """In-memory buffer for recent data points.

    Holds data before flushing to disk.
    """

    def __init__(self, max_size_bytes: int) -> None:
        """Initialize memory buffer.

        Args:
            max_size_bytes: Maximum buffer size in bytes
        """
        self.max_size_bytes = max_size_bytes
        self.current_size_bytes = 0
        self.data: dict[str, dict[int, list[DataPoint]]] = {}  # metric -> series_id -> points

    def add_point(self, metric_name: str, series_id: int, point: DataPoint) -> None:
        """Add a point to the buffer.

        Args:
            metric_name: Name of metric
            series_id: Series ID
            point: DataPoint to add
        """
        if metric_name not in self.data:
            self.data[metric_name] = {}

        if series_id not in self.data[metric_name]:
            self.data[metric_name][series_id] = []

        self.data[metric_name][series_id].append(point)
        self.current_size_bytes += 16  # Approximate size of one point

    def is_full(self) -> bool:
        """Check if buffer is full.

        Returns:
            True if buffer exceeds max size
        """
        return self.current_size_bytes >= self.max_size_bytes

    def clear(self) -> None:
        """Clear the buffer."""
        self.data.clear()
        self.current_size_bytes = 0

    def get_points(self, metric_name: str, series_id: int) -> list[DataPoint]:
        """Get points for a series.

        Args:
            metric_name: Name of metric
            series_id: Series ID

        Returns:
            List of points, or empty list
        """
        if metric_name not in self.data or series_id not in self.data[metric_name]:
            return []
        return self.data[metric_name][series_id]

    def get_all_points(self) -> dict[str, dict[int, list[DataPoint]]]:
        """Get all buffered points.

        Returns:
            Dictionary of all points
        """
        return self.data.copy()

    @property
    def point_count(self) -> int:
        """Get total number of points in buffer."""
        count = 0
        for metric_data in self.data.values():
            for points in metric_data.values():
                count += len(points)
        return count
