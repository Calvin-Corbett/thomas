try:
    from .api import router  # noqa: F401
except ImportError:
    # FastAPI is optional
    pass
