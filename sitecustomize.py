import os
import sys

# Keep test and local helper runs from dirtying the repo with __pycache__ output.
os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")
sys.dont_write_bytecode = True
