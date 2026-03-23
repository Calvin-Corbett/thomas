"""Compaction logic for LSM-tree management."""

from pathlib import Path

from thomas.marketplace.kvstore._exceptions import CompactionError
from thomas.marketplace.kvstore._types import CompactionStrategy
from thomas.marketplace.kvstore.iterators import MergeIterator
from thomas.marketplace.kvstore.manifest import Manifest
from thomas.marketplace.kvstore.sstable import SSTable, SSTableWriter


class Compactor:
    """Handles compaction of SSTables across levels."""

    def __init__(
        self, data_dir: str, strategy: CompactionStrategy = CompactionStrategy.LEVELED, level_multiplier: int = 10
    ):
        """Initialize compactor.

        Args:
            data_dir: Directory containing SSTables
            strategy: Compaction strategy to use
            level_multiplier: Multiplier for leveled strategy
        """
        self.data_dir = Path(data_dir)
        self.strategy = strategy
        self.level_multiplier = level_multiplier
        self.manifest = Manifest(str(self.data_dir))

    def should_compact_level0(self, l0_file_count: int, threshold: int) -> bool:
        """Check if L0 should be compacted.

        Args:
            l0_file_count: Number of files in L0
            threshold: Threshold for compaction

        Returns:
            True if compaction should occur
        """
        return l0_file_count >= threshold

    def should_compact_level(self, level: int, target_size_mb: int) -> bool:
        """Check if a level should be compacted.

        Args:
            level: Level number
            target_size_mb: Target size in MB

        Returns:
            True if compaction should occur
        """
        if level == 0:
            return False

        files = self.manifest.get_level_files(level)
        if not files:
            return False

        # Calculate total size
        total_size = 0
        for filename in files:
            file_path = self.data_dir / filename
            if file_path.exists():
                total_size += file_path.stat().st_size

        target_bytes = target_size_mb * 1024 * 1024
        return total_size > target_bytes

    def compact_level0(self) -> str | None:
        """Compact L0 into L1.

        Returns:
            Output SSTable filename, or None if nothing to do

        Raises:
            CompactionError: If compaction fails
        """
        try:
            l0_files = self.manifest.get_level_files(0)
            if len(l0_files) < 1:
                return None

            # Mark as compacting
            self.manifest.mark_compacting(0)

            # Merge all L0 files
            input_files = [self.data_dir / f for f in l0_files]
            output_file = self._get_next_sstable_name(1)

            self._merge_sstables(input_files, output_file)

            # Update manifest
            self.manifest.clear_level(0)
            self.manifest.add_sstable(1, output_file.name)

            # Delete input files
            for f in input_files:
                if f.exists():
                    f.unlink()

            self.manifest.unmark_compacting(0)
            return output_file.name

        except Exception as e:
            self.manifest.unmark_compacting(0)
            raise CompactionError(f"L0 compaction failed: {e}")

    def compact_level(self, level: int) -> str | None:
        """Compact a level (move overflowing files to next level).

        Args:
            level: Level number

        Returns:
            Output SSTable filename

        Raises:
            CompactionError: If compaction fails
        """
        if level == 0:
            return self.compact_level0()

        try:
            self.manifest.mark_compacting(level)

            files = self.manifest.get_level_files(level)
            if not files:
                self.manifest.unmark_compacting(level)
                return None

            # Calculate target size for this level
            if self.strategy == CompactionStrategy.LEVELED:
                # Each level is multiplier * previous level
                target_size_mb = 10 * (self.level_multiplier**level)
            else:  # SIZE_TIERED
                # Keep same target size across levels
                target_size_mb = 10 * self.level_multiplier

            if not self.should_compact_level(level, target_size_mb):
                self.manifest.unmark_compacting(level)
                return None

            # Merge all files at this level to next level
            input_files = [self.data_dir / f for f in files]
            output_file = self._get_next_sstable_name(level + 1)

            self._merge_sstables(input_files, output_file)

            # Update manifest
            self.manifest.clear_level(level)
            self.manifest.add_sstable(level + 1, output_file.name)

            # Delete input files
            for f in input_files:
                if f.exists():
                    f.unlink()

            self.manifest.unmark_compacting(level)
            return output_file.name

        except Exception as e:
            self.manifest.unmark_compacting(level)
            raise CompactionError(f"Level {level} compaction failed: {e}")

    def _merge_sstables(self, input_files: list[Path], output_file: Path) -> None:
        """Merge multiple SSTables into one.

        Deduplicates keys and removes tombstones.

        Args:
            input_files: Input SSTable paths
            output_file: Output SSTable path
        """
        # Open input SSTables
        sstables = [SSTable(str(f)) for f in input_files]

        # Create merge iterator
        iterators = [
            ((entry.key, entry.value, entry.sequence) for entry in sstable.iter_entries()) for sstable in sstables
        ]

        merger = MergeIterator(iterators, skip_tombstones=True)

        # Write output SSTable
        with SSTableWriter(str(output_file)) as writer:
            for key, value in merger:
                writer.add(key, value)

    def _get_next_sstable_name(self, level: int) -> Path:
        """Generate next SSTable filename for a level.

        Args:
            level: Level number

        Returns:
            Path for new SSTable
        """
        seq = self.manifest.next_sequence()
        filename = f"sstable_L{level}_{seq}.db"
        return self.data_dir / filename

    def compact_all(self) -> None:
        """Compact all levels as needed.

        Useful for cleanup and optimization.
        """
        # Start from L0 and work up
        level = 0
        while True:
            files = self.manifest.get_level_files(level)
            if not files:
                break

            if level == 0:
                self.compact_level0()
            else:
                self.compact_level(level)

            level += 1

    def get_level_sizes(self) -> dict:
        """Get size of each level.

        Returns:
            {level: size_bytes}
        """
        sizes = {}
        for level in range(self.manifest.max_level() + 1):
            files = self.manifest.get_level_files(level)
            total = 0
            for filename in files:
                f = self.data_dir / filename
                if f.exists():
                    total += f.stat().st_size
            sizes[level] = total
        return sizes

    def estimate_compaction_work(self) -> float:
        """Estimate work needed for all pending compactions.

        Returns:
            Estimated work in units of MB to compact
        """
        sizes = self.get_level_sizes()
        total = sum(sizes.values())
        return total / (1024 * 1024)


class SizeTieredCompactor(Compactor):
    """Size-tiered compaction strategy."""

    def should_trigger_compaction(self, level: int) -> bool:
        """Check if compaction should be triggered.

        Args:
            level: Level number

        Returns:
            True if compaction should start
        """
        # Size-tiered: compact when a level has multiple files of similar size
        files = self.manifest.get_level_files(level)

        if level == 0:
            # L0: compact when reaching threshold
            return len(files) >= 4
        else:
            # Higher levels: less frequent compaction
            return len(files) >= 8


class LeveledCompactor(Compactor):
    """Leveled compaction strategy."""

    def should_trigger_compaction(self, level: int) -> bool:
        """Check if compaction should be triggered.

        Args:
            level: Level number

        Returns:
            True if compaction should start
        """
        # Leveled: compile when level exceeds target size
        target_size_mb = 10 * (self.level_multiplier**level)
        return self.should_compact_level(level, target_size_mb)
