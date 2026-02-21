import zipfile
import os

zips = [
    "thomas_feature_pack_watcher_ULTIMATE.zip",
    "thomas_plugin_loader_feature_pack_best.zip",
    "thomas_memory_fabric_v2_patch_revB.zip"
]

base = r"F:\DevHub\Thomas\Inbox"

for z in zips:
    path = os.path.join(base, z)
    print(f"\n--- {z} ---")
    try:
        with zipfile.ZipFile(path, 'r') as zf:
            for n in zf.namelist()[:10]:
                print(n)
    except Exception as e:
        print(f"Error: {e}")
