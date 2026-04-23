import os
import zipfile
from pathlib import Path

zips = [
    "thomas_feature_pack_watcher_ULTIMATE.zip",
    "thomas_plugin_loader_feature_pack_best.zip",
    "thomas_memory_fabric_v2_patch_revB.zip",
]

ROOT = Path(__file__).resolve().parent
_inbox_dir = ROOT / "Inbox"
if not _inbox_dir.is_dir():
    _inbox_dir = ROOT / "inbox"
base = str(_inbox_dir)

for z in zips:
    path = os.path.join(base, z)
    print(f"\n--- {z} ---")
    try:
        with zipfile.ZipFile(path, "r") as zf:
            for n in zf.namelist()[:10]:
                print(n)
    except Exception as e:
        print(f"Error: {e}")
