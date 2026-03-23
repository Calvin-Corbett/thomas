from __future__ import annotations

import argparse
from pathlib import Path

from .contracts import DesktopVmContext
from .helper_service import DesktopOperatorHelperServer
from .runtime import DesktopOperatorRuntime


def main() -> None:
    parser = argparse.ArgumentParser(description="Thomas desktop operator loopback helper")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--token", required=True)
    parser.add_argument("--artifact-dir", default="")
    parser.add_argument("--session-ttl-s", type=int, default=900)
    parser.add_argument("--vm-id", default="")
    parser.add_argument("--vm-provider", default="")
    parser.add_argument("--vm-mode", default="")
    parser.add_argument("--isolated", action="store_true")
    args = parser.parse_args()

    vm_context = DesktopVmContext(
        vm_id=str(args.vm_id or "").strip() or "local-helper",
        provider=str(args.vm_provider or "").strip() or ("dedicated_vm" if args.isolated else "host_session"),
        isolation_mode=str(args.vm_mode or "").strip() or ("dedicated_vm" if args.isolated else "shared_session"),
        isolated=bool(args.isolated),
    )
    runtime = DesktopOperatorRuntime(
        artifacts_dir=Path(args.artifact_dir).resolve() if str(args.artifact_dir or "").strip() else None,
        session_ttl_s=int(args.session_ttl_s),
        vm_context=vm_context,
    )
    server = DesktopOperatorHelperServer(
        host=str(args.host or "127.0.0.1"),
        port=int(args.port),
        bearer_token=str(args.token),
        runtime=runtime,
    )
    server.serve_forever()


if __name__ == "__main__":
    main()
