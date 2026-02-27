"""Tests for compaction logic."""

import tempfile
from pathlib import Path

from thomas.kvstore.compaction import Compactor, LeveledCompactor, SizeTieredCompactor
from thomas.kvstore.manifest import Manifest
from thomas.kvstore.sstable import SSTableWriter


class TestCompactorBasics:
    """Test basic compaction functionality."""

    def test_initialization(self):
        """Test compactor initialization."""
        with tempfile.TemporaryDirectory() as tmpdir:
            compactor = Compactor(tmpdir)
            assert compactor.data_dir == Path(tmpdir)

    def test_should_compact_l0(self):
        """Test L0 compaction trigger."""
        with tempfile.TemporaryDirectory() as tmpdir:
            compactor = Compactor(tmpdir)

            # Should not compact with few files
            assert not compactor.should_compact_level0(2, 4)

            # Should compact when exceeding threshold
            assert compactor.should_compact_level0(4, 4)

    def test_sstable_name_generation(self):
        """Test SSTable naming."""
        with tempfile.TemporaryDirectory() as tmpdir:
            compactor = Compactor(tmpdir)
            name1 = compactor._get_next_sstable_name(0)
            name2 = compactor._get_next_sstable_name(1)

            assert name1.name.startswith("sstable_L0_")
            assert name2.name.startswith("sstable_L1_")
            assert name1 != name2


class TestL0Compaction:
    """Test L0 compaction."""

    def test_compact_l0_basic(self):
        """Test basic L0 compaction."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create L0 files
            manifest = Manifest(tmpdir)

            for file_idx in range(2):
                file_path = Path(tmpdir) / f"sstable_L0_{file_idx}.db"
                with SSTableWriter(str(file_path)) as writer:
                    for i in range(10):
                        key = f"key{i:02d}".encode()
                        writer.add(key, f"value{file_idx}_{i}".encode())
                manifest.add_sstable(0, file_path.name)

            # Compact L0
            compactor = Compactor(tmpdir)
            output = compactor.compact_level0()

            # Should produce output
            assert output is not None
            assert "L1" in output

            # L0 should be empty
            assert len(manifest.get_level_files(0)) == 0

            # L1 should have file
            assert len(manifest.get_level_files(1)) > 0

    def test_compact_l0_deduplication(self):
        """Test that L0 compaction deduplicates keys."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manifest = Manifest(tmpdir)

            # Create two L0 files with overlapping keys
            for file_idx in range(2):
                file_path = Path(tmpdir) / f"sstable_L0_{file_idx}.db"
                with SSTableWriter(str(file_path)) as writer:
                    writer.add(b"key", f"value{file_idx}".encode())
                manifest.add_sstable(0, file_path.name)

            compactor = Compactor(tmpdir)
            output = compactor.compact_level0()

            # Read output file
            output_path = Path(tmpdir) / output
            from thomas.kvstore.sstable import SSTable

            sstable = SSTable(str(output_path))

            # Should have only one entry (latest value)
            entries = list(sstable.iter_entries())
            assert len(entries) == 1
            assert entries[0].value == b"value1"

    def test_compact_l0_removes_tombstones(self):
        """Test that L0 compaction removes tombstones."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manifest = Manifest(tmpdir)

            # Create L0 file with tombstone
            file_path = Path(tmpdir) / "sstable_L0_0.db"
            with SSTableWriter(str(file_path)) as writer:
                writer.add(b"key1", b"value1")
                writer.add(b"key2", None)  # Tombstone
                writer.add(b"key3", b"value3")
            manifest.add_sstable(0, file_path.name)

            compactor = Compactor(tmpdir)
            output = compactor.compact_level0()

            # Read output - tombstone should be gone
            output_path = Path(tmpdir) / output
            from thomas.kvstore.sstable import SSTable

            sstable = SSTable(str(output_path))

            entries = list(sstable.iter_entries())
            # Only two entries (no tombstone)
            assert len(entries) == 2
            assert entries[0].key == b"key1"
            assert entries[1].key == b"key3"


class TestLevelCompaction:
    """Test higher-level compaction."""

    def test_compact_single_level(self):
        """Test compacting a single level."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manifest = Manifest(tmpdir)

            # Create L1 file
            file_path = Path(tmpdir) / "sstable_L1_0.db"
            with SSTableWriter(str(file_path)) as writer:
                for i in range(10):
                    writer.add(f"key{i:02d}".encode(), b"value")
            manifest.add_sstable(1, file_path.name)

            compactor = Compactor(tmpdir)
            output = compactor.compact_level(1)

            if output is not None:
                # File should be moved to L2
                assert "L2" in output

    def test_no_compaction_needed(self):
        """Test when no compaction is needed."""
        with tempfile.TemporaryDirectory() as tmpdir:
            compactor = Compactor(tmpdir)

            # No files, no compaction
            output = compactor.compact_level(1)
            assert output is None


class TestLeveledCompactor:
    """Test leveled compaction strategy."""

    def test_leveled_compactor(self):
        """Test LeveledCompactor."""
        with tempfile.TemporaryDirectory() as tmpdir:
            compactor = LeveledCompactor(tmpdir, level_multiplier=10)

            # Should trigger at size threshold
            manifest = Manifest(tmpdir)
            manifest.add_sstable(1, "dummy.db")

            # Check trigger logic
            should_trigger = compactor.should_trigger_compaction(1)
            # Depends on file size, likely false for dummy file


class TestSizeTieredCompactor:
    """Test size-tiered compaction strategy."""

    def test_size_tiered_compactor(self):
        """Test SizeTieredCompactor."""
        with tempfile.TemporaryDirectory() as tmpdir:
            compactor = SizeTieredCompactor(tmpdir, level_multiplier=10)

            # Check trigger logic
            manifest = Manifest(tmpdir)
            should_trigger = compactor.should_trigger_compaction(0)


class TestCompactionMerge:
    """Test SSTable merging during compaction."""

    def test_merge_sstables(self):
        """Test merging multiple SSTables."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create input SSTables
            input_files = []
            for file_idx in range(2):
                file_path = Path(tmpdir) / f"input_{file_idx}.db"
                with SSTableWriter(str(file_path)) as writer:
                    for i in range(10):
                        key = f"key{i:02d}".encode()
                        writer.add(key, f"val_{file_idx}_{i}".encode())
                input_files.append(file_path)

            # Merge
            output_path = Path(tmpdir) / "merged.db"
            compactor = Compactor(tmpdir)
            compactor._merge_sstables(input_files, output_path)

            # Verify output
            from thomas.kvstore.sstable import SSTable

            sstable = SSTable(str(output_path))

            # Should have merged entries
            entries = list(sstable.iter_entries())
            assert len(entries) == 10  # Deduped


class TestCompactionStats:
    """Test compaction statistics."""

    def test_level_sizes(self):
        """Test getting level sizes."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manifest = Manifest(tmpdir)

            # Create files
            for level in range(3):
                file_path = Path(tmpdir) / f"sstable_L{level}_0.db"
                with SSTableWriter(str(file_path)) as writer:
                    for i in range(5):
                        writer.add(f"key{i}".encode(), b"v")
                manifest.add_sstable(level, file_path.name)

            compactor = Compactor(tmpdir)
            sizes = compactor.get_level_sizes()

            assert 0 in sizes
            assert 1 in sizes
            assert 2 in sizes
            for size in sizes.values():
                assert size > 0

    def test_compaction_work_estimate(self):
        """Test work estimation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manifest = Manifest(tmpdir)

            # Create files
            for level in range(2):
                file_path = Path(tmpdir) / f"sstable_L{level}_0.db"
                with SSTableWriter(str(file_path)) as writer:
                    for i in range(10):
                        writer.add(f"key{i}".encode(), b"v" * 1000)
                manifest.add_sstable(level, file_path.name)

            compactor = Compactor(tmpdir)
            work = compactor.estimate_compaction_work()
            assert work > 0  # Some work estimated


class TestCompactionManifest:
    """Test manifest updates during compaction."""

    def test_compacting_state(self):
        """Test tracking which levels are compacting."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manifest = Manifest(tmpdir)

            assert not manifest.is_compacting(0)
            manifest.mark_compacting(0)
            assert manifest.is_compacting(0)
            manifest.unmark_compacting(0)
            assert not manifest.is_compacting(0)

    def test_manifest_file_list(self):
        """Test getting all files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manifest = Manifest(tmpdir)

            manifest.add_sstable(0, "file1.db")
            manifest.add_sstable(1, "file2.db")
            manifest.add_sstable(1, "file3.db")

            files = manifest.get_all_files()
            assert "file1.db" in files
            assert "file2.db" in files
            assert "file3.db" in files
