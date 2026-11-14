"""Where rows live: one file for each thing a running Thomas can turn off and on.

A row is an entry in ``default.toml``, in this folder, that names a ``plugin`` in a file here. A server started with a row
off never imports it, so the file holds the row and nothing else, and the code the row turns on stays where it is:

    class _Search:
        name = "search"
        inject = ("web",)
        imports = ("thomas.server.routes.search",)

        def apply(self, ctx, config):
            from thomas.server.routes.search import register_search_routes

            service = ctx["web"]
            register_search_routes(service.view(ctx), require_api_access=service.require_api_access)


    plugin = _Search()

- The registrar is imported inside ``apply``. At the top of the file it would load along with the entry. Nor can its own
  module be the entry: tests replace those modules with fakes that have no ``plugin``, and an import inside ``apply``
  reaches the fake.
- ``imports`` names what ``apply`` goes on to load. Turning a row on imports those in a thread, not on the event loop,
  and they are what must stay unloaded on a server started with it off.
- Never promise an unload. Off on a running server takes the routes and runs the stop steps, and the row's modules stay
  loaded until the next restart, with whatever they hold at the top level. The words say what stops, not what goes.
- A row provides no named call. ``late.require`` stops the server when a provider is missing, and a row may be off.
  A row marked ``required = true`` in ``default.toml`` has no off switch, so it may be named like a plugin that provides
  calls (``chat_offers.py``, ``evolve_agent_stop.py``). Those calls stay provided at import, whether or not any row loads.
  Never move a ``late.provide`` into a row's ``apply`` for that reason.
- ``apply`` runs while the app is still being built, so a key written later is read in a request or in ``ctx.on_ready``.
- A row joins the table when its ``on_startup`` hooks end, and reads ``loading`` until then, at the server's own start as
  on a server already running. So a handler may lean on what they set up. The server's start does not wait for them.
- A row may not claim a method and path the server already answers, or another row holds, nor a pattern wide enough to
  answer one the server claims exactly: ``/api/things/{id}`` beside ``/api/things/stats`` left in the shell. It fails with
  the reason.
- Background work starts with ``ctx.task``, never ``asyncio.create_task``. A stop knows only the first kind, so only that
  kind cannot hold Thomas open if it ignores being cancelled.
- A row stops whatever else it starts, such as a thread, and no proof sees it if it does not. A helper that takes ``app``
  gets ``service.view(ctx)``, and its ``on_cleanup`` hook runs when the row stops. Otherwise add a step with
  ``ctx.on_stopped(step)``, where ``step`` is an async function of no arguments. It runs once running requests have ended.
  Never hand a helper ``service.app``: that app is frozen on a running server, so pressing on fails, and a hook on it
  waits for the server to shut down, not for off. A stop step does not run for a row whose ``apply`` raised, or for one
  thrown away at startup, so what keeps running starts through ``ctx.on_ready``, which runs only for a row that was
  accepted, and never straight in ``apply``.
- ``apply`` has no ``try``. A family in the shell logs a failure and the server boots without it. A row that does that
  reads active with no routes, and one that raises reads failed with the reason. Where a test pins the family's log line,
  log it and then raise.

``tests/test_every_row_keeps_its_promises.py`` holds every row to this, and refuses a row for what stays in the shell.
``docs/superpowers/plans/2026-10-31-moving-a-feature-into-a-row.md`` is how a family in the shell becomes a row.

Spec: docs/superpowers/specs/2026-10-31-cordis-foundation-design.md
"""
