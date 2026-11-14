"""The measured run limit, as a row: two routes that report on Thomas, and the sampler that watches Build runs' memory.

Off takes ``/api/machine/capacity`` and ``/api/metrics/steps`` away and ends the sampler, so what a Build run really uses
stops reaching ``record_run_peak``, which nothing else calls. The limit itself stays: ``machine_capacity.json`` holds it,
and Build, the checks and the cage runner go on reading that file. A start with this on writes that file at once. With
this off ``profile`` writes it for whoever asks first, so a new install has none until a run wants one, and until then the
cage runner uses its own default of 8. The step log goes on being written, and only the second route read it.

``thomas.core.machine_capacity`` cannot be in ``imports``, because Build loads it whatever this row does.
``thomas.core.step_report`` is the one module nothing but these routes loads. So a server started with this off has the
registrar loaded and has not run it.

``thomas/server/rows/__init__.py`` says how a row is written.
"""

from __future__ import annotations

from typing import Any


class _MachineCapacity:
    name = "machine_capacity"
    inject = ("web",)
    imports = ("thomas.core.step_report",)

    def apply(self, ctx: Any, config: Any) -> None:
        from thomas.core.machine_capacity import register_machine_capacity

        service = ctx["web"]
        if not callable(service.require_api_access):  # the registrar reads no guard as a route open to everyone
            raise RuntimeError("machine_capacity has no access guard to register with")
        register_machine_capacity(service.view(ctx), require_api_access=service.require_api_access, own_task=ctx.task)


plugin = _MachineCapacity()
