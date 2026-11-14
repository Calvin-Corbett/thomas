### Fixed

- Aligned `tests/test_new_safety_gates.py` with f810377f: a module name only inside a string is not an import, while `importlib.import_module("thomas.x")` remains covered as an import.
