from __future__ import annotations

"""Integration entrypoint.

Call `install(app)` after creating your FastAPI instance.
"""

from fastapi import Depends

from .deps import enforce_workspace
from .router import router as workspace_router
from .scoping import register_workspace_scoping


def install(app) -> None:
    register_workspace_scoping()
    # Workspace endpoints themselves are workspace-enforced for safety.
    app.include_router(workspace_router, prefix="/api", dependencies=[Depends(enforce_workspace)])
