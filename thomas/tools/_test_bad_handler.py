"""Temporary test file for exception handler gate."""


def bad_function():
    try:
        do_something()  # noqa: F821  -- intentional undefined name; this file is a fixture for exception_handler_gate testing
    except Exception:
        pass  # silently swallow - should be caught
