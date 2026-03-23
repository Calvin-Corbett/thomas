"""Temporary test file for exception handler gate."""


def bad_function():
    try:
        do_something()
    except Exception:
        pass  # silently swallow - should be caught
