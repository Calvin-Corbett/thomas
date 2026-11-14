# Plugins that can be unplugged and replugged while Thomas runs

**Phase 3.5** · `plans/thomas/tasks/PRAXIS-PHASE3-KERNEL/PLAN.md` · 2026-09-24

## What you asked for

> "everything's a plug in, and that's Thomas"

and, for this phase:

> "Finish it: put those plugin systems on the kernel and make plugins
> hot-swappable, so a plugin can be unplugged and replugged while you are
> running without breaking anything else, and a self-edit to a plugin takes
> effect without restarting you. Prove it the way I would use it: swap one live
> and show it working."

## What was already there, and what was missing

Phase 3.2 built the kernel — contexts, reversible registration, an event bus
that hands back results, dependency gating. Phase 3.3 mounted the one plugin
system that actually dispatches hooks. Both of those happen **at boot**. Between
boot and shutdown nothing could change: `Fork.dispose()` removed a plugin and
forgot it, so "off for a moment" and "gone" were the same operation, and there
was no way back at all.

Underneath that sat a second problem, and it is the one that would have made a
self-edit look like it had no effect even after the first was fixed:

> `thomas/plugins/runtime.py` cached loaded plugin instances against the **mtime
> of `installed_plugins.json`**. Editing a plugin's own code does not touch that
> file. Every load after the first therefore returned the instance built from the
> code as it was when the process started — for the life of the process.

That is not a stale-process problem. Nothing in the cache key looked at the file
that changed.

And underneath *that* sat a third one, found by the check on this work rather
than by me, which is why it is written out here in full:

> Plugins were imported with `SourceFileLoader`, which runs the cached `.pyc`
> whenever the source's mtime **in whole seconds** and its size both match the
> cache header. A rewrite inside the same second whose length happens to match
> satisfies that exactly. The reload reports `reloaded` and the old code keeps
> answering — worse than not reloading, because the log says the edit landed.
> On the live app: `outcome: reloaded` thirteen times while the hook stamped
> `loop36` instead of `loop49`.

The suite could not see it: `tests/conftest.py` sets
`sys.dont_write_bytecode = True`, so no `.pyc` was ever written under pytest.
Every real launch writes them — `python -m thomas.server`, `thomas serve`, the
caged server's scheduled task.

## What now exists

| Piece | File | What it does |
|---|---|---|
| Swap primitives | `thomas/core/kernel/hotswap.py` | `unplug` returns a handle that can put a plugin back; `swap` replaces one atomically and restores the old one if the replacement fails |
| Source fingerprint | `thomas/plugins/source_fingerprint.py` | Hashes a plugin's `.py` files so "is this the same code?" is answered by content, and clears the submodules a previous load left in `sys.modules` |
| Source-only import | `thomas/plugins/source_loader.py` | A loader that never reads or writes `__pycache__`, and a `sys.meta_path` finder that extends that to a plugin package's own submodule imports |
| Cache fix | `thomas/plugins/runtime.py` | The instance cache is keyed on the fingerprint as well as the manifest; `enabled_plugin_paths` and `load_plugin_instance` expose the cheap half and the fresh-load half separately |
| Supervisor | `thomas/server/plugin_supervisor.py` | Holds every mount by name: `unplug`, `replug`, `reload`, `sync`, `status` |
| One plugin's record | `thomas/server/plugin_supervisor_entry.py` | `Supervised`: which fork a plugin is mounted under, the handle that can put it back, the fingerprint of the code answering, the last failure — and the status row, which imports nothing and runs no plugin code |
| The other three systems | `thomas/server/plugin_systems_kernel.py` | The extensions catalog and both installers mount as kernel services, resolvable and swappable |
| What those three *are* | `thomas/server/plugin_system_providers.py` | The default provider behind each service, and the `describe()` the status route prints — re-exported by the module above, so callers keep one import site |
| Live controls | `thomas/server/routes/plugin_kernel_routes.py` | `GET /api/plugins/kernel` and four loopback-only POSTs |
| Startup and stop | `thomas/server/plugin_startup.py` | The two mounts the server makes, one `try` each, and the cleanup that unwinds them in reverse — where the app keeps each handle is defined here, and the status route reads the key from here |
| The marketplace, split so it could move | `thomas/server/routes/marketplace_catalog_fields.py`, `_rows.py`, `_packs.py`, `_sync.py` | The 1,190-line catalog routes module broken into four by responsibility — fields, rows, packs, sync — which is what let the catalog read and the agent-plugin install go through kernel services |

## The four systems, and what "on the kernel" means for each

Phase 3.3 established that only one of the four dispatches hooks. That is still
true, and it changes *what* each contributes rather than whether it belongs.

| System | Contributes | Swappable live |
|---|---|---|
| `thomas/plugins` (p097–p123) | Hook subscriptions | Yes — supervised by name |
| `extensions/` catalog | The `extension_catalog` service | Yes — `plugin_systems_report`, the status route **and `/api/marketplace/plugins`** resolve it, so a swap changes what the marketplace shows on the next request |
| `desktop_plugins_*` | The `desktop_plugin_installer` service | Yes — `thomas/server/desktop_plugins` resolves it, which is the module the marketplace import route already imports from, so the live install path goes through the kernel with that route unchanged |
| `agent_plugins_*` | The `agent_plugin_installer` service | Yes — `_install_bundle_auto` resolves it and asks it both `accepts` and `install` |

That last row was the honest gap for most of this phase, and closing it is the
last thing this change did. The caller is `_install_bundle_auto` in
`thomas/server/routes/marketplace_catalog_aiohttp.py`; redirecting it is a
two-line change, and it was blocked by size rather than by design. That module
was 1,190 lines and is not in `docs/monolith_guard_baseline.json` under
`allowed_large_files`, and the guard enforces the 800-line soft limit on any file
a change touches (`unbaselined_soft_limit_lines`,
`enforce_soft_limit_changed_only`) — so the file could not be edited at all until
it was smaller. It is four modules now (`marketplace_catalog_fields`, `_rows`,
`_packs`, `_sync`, plus the routes themselves at 535 lines), the redirect landed,
and the status route's row carries `installs_through_the_service: true`.

The provider's own surface is exercised rather than assumed:
`AgentPluginInstaller.accepts` imported its detector from
`agent_plugins_adapter`, where that name has never lived, so every call raised
`ImportError` — a default provider that could not answer the first question a
caller would ask it. It resolves `agent_plugins_manifest` now and
`test_the_agent_installer_can_say_whether_a_bundle_is_its_own` calls it on three
bundle shapes. `install` reaches for its adapter function the same deferred way,
so `test_the_agent_installer_hands_a_bundle_to_the_adapter` calls it with that
function replaced via `monkeypatch.setattr`, which raises on an absent attribute
— the import name is checked rather than assumed, without unpacking a bundle
onto the disk.

What was deliberately *not* done: turning
`agent_plugins_adapter.install_agent_plugin_bytes` into a facade, which is the
shape the desktop installer has. `tests/test_install_transaction.py` reads that
function's source to check the install is transactional, so a facade there would
break a real check; the seam belongs at the call site instead.

**Swapping a system's provider is an in-process call, not a route.**
`MountedSystems.swap` is what does it, and its callers are
`tests/test_plugin_systems_kernel.py`,
`tests/test_plugin_kernel_routes.py::test_a_system_provider_swapped_live_shows_up_in_the_status`
and `tests/test_marketplace_kernel_swap.py`.
There is no HTTP endpoint for it, because a provider is an object rather than
something a request can name, and nothing asked for one. The method exists
because it is the only correct way to replace a provider — it keeps the handle
pointing at the fork that is answering, including after a refused swap, which a
caller reaching for the kernel's `swap` directly gets wrong.

## The proof

`tests/test_plugin_hot_swap.py::test_a_plugin_edited_on_disk_takes_effect_without_a_restart`
is the one to read. It does exactly what you would do:

1. Writes a real plugin package to disk and starts the supervisor on it.
2. Dispatches `before_tool` through `make_plugin_hook_runner` — the same runner a
   turn uses — and gets back `["v1"]`.
3. **Rewrites the plugin's `__init__.py`.** Same process, same kernel, same
   runner object; nothing is restarted and the test does not re-import anything
   itself.
4. Calls `supervisor.sync()`, which reports `reloaded: ["demo_stamp"]`.
5. Dispatches again and gets back `["v2"]`.

Over HTTP the same sequence is `POST /api/plugins/kernel/reload {"name": ...}`,
covered by `tests/test_plugin_kernel_routes.py`.

### The same proof with the bytecode cache in play

`tests/test_plugin_source_reload.py` runs the whole sequence again with
`sys.dont_write_bytecode` set to **False** — the way every real launch runs, and
the opposite of what `tests/conftest.py` sets. The stale cache is not waited for,
it is constructed: compile the current source, rewrite it with same-length text,
put the mtime back. That is exactly the condition `SourceFileLoader` treats as
"the cache is current".

- `test_the_stale_bytecode_trap_is_real` imports the trapped file with a stock
  loader and asserts it produces the **old** mark. It guards the tests below
  rather than the product: without it they could pass having exercised nothing.
- `test_a_reload_runs_the_new_source_even_when_the_pyc_looks_current` —
  `supervisor.reload` answers `reloaded` and the next dispatch stamps `loop49`.
- `test_sync_picks_up_the_edit_the_way_the_running_app_does` — the same through
  `sync`, which is the operation a self-edit goes through with nothing else asked.
- `test_an_edit_in_a_submodule_lands_even_when_its_bytecode_looks_current` — one
  level down, where `from . import rule` goes to `sys.meta_path` instead of to the
  loader that imported the package. No `force`: the content fingerprint sees a
  same-length edit at an unchanged mtime.
- `test_loading_a_plugin_leaves_no_bytecode_to_go_stale` — after a mount there is
  no `__pycache__` under the plugin at all, so there is nothing to go stale later.

The route half is its own file, `tests/test_plugin_reload_over_http.py`, sharing
the trap through `tests/plugin_bytecode_helpers.py`:

- `LiveReloadOverHttpTests::test_the_reload_route_runs_the_edit_and_not_the_cached_bytecode`
  — the same over `POST /api/plugins/kernel/reload`, which is the route that
  answered `reloaded` thirteen times on the live app. It stands up a real
  aiohttp app with the supervisor on it, so the bytes that answer the request
  are the bytes the running server would run.

### The same proof on the surface you would actually open

The tests above swap a *plugin*. `tests/test_marketplace_kernel_swap.py` swaps a
*system provider* and reads the result off the marketplace itself, with one
aiohttp app serving throughout and nothing restarted between the two requests:

- `test_the_default_providers_are_the_real_ones` — the swaps below start from
  `ExtensionCatalog` and `AgentPluginInstaller`, the providers a real boot
  mounts, not from a fixture.
- `test_a_catalog_swapped_live_changes_the_next_response` — `GET
  /api/marketplace/plugins` returns version `1.0.0`; the catalog provider is
  swapped; the same client asks again and gets `2.0.0`.
- `test_the_import_route_installs_through_the_agent_installer_provider` — a
  recording provider is swapped in, `POST /api/marketplace/import` hands it the
  bundle, and the test reads back the config, the bytes and the `source` dict it
  was given.
- `test_a_provider_that_refuses_the_bundle_leaves_the_signed_path_alone` — the
  other half of the contract: `accepts` returns False, the provider is asked and
  never installs, and the bundle goes to the signed desktop path.

Everything in that file mounts on the process-wide kernel — `mount_plugin_systems()`
with no argument, the same kernel `thomas/server/plugin_startup.py` mounts on at
boot — because that is the one the routes resolve against.

The rest of the suite pins the parts that make it safe rather than merely
impressive:

- **A broken edit does not take the plugin down.** `reload` returns `failed`, the
  previous version keeps answering, and fixing the file makes the next reload
  land. Asked twice about a file that is still broken it says `failed` twice,
  never `unchanged` — that word means "what is on disk is already running", and
  it must not be said about an edit that never got on the bus — which includes
  new code that imports cleanly and is then refused a mount.
  (`test_a_broken_edit_leaves_the_previous_version_answering`,
  `test_a_still_broken_edit_keeps_saying_failed`,
  `test_an_edit_that_imports_but_will_not_mount_is_still_retried`, and at the
  kernel level `test_a_failed_swap_leaves_the_previous_version_running`.)
- **A failed reload says why.** The reason on the status row is the plugin's own
  error — `ValueError: typo in my edit`, `SyntaxError`, `get_plugin() raised ...`
  — not "no recognizable plugin entrypoint on disk", which is what a loader that
  swallows import errors by design used to report about a file whose only problem
  was a typo. (`test_a_failed_reload_says_why_not_just_that_it_failed`, over two
  shapes of broken edit.)
- **Nothing else breaks.** Unplugging one plugin leaves its neighbours
  dispatching; swapping a plugin that *provides* a service unmounts and remounts
  the plugins depending on it, against the new value.
  (`test_unplugging_one_plugin_leaves_the_others_running`,
  `test_swapping_a_provider_reruns_its_dependants_against_the_new_value`.)
- **Two mounted plugins both speak.** Dispatch folds the payload through the
  subscribers in turn rather than broadcasting one payload and merging the
  answers; broadcast meant two plugins writing the same key both worked from the
  original and only the last survived, so mounting a second plugin quietly
  cancelled the first. (`test_fold_gives_each_handler_what_the_last_one_produced`
  in `tests/test_core_kernel_context.py`, and at the plugin level
  `test_reloading_one_plugin_by_name_swaps_just_that_one`.)
- **The off switch stays off.** `sync` does not remount something you unplugged,
  and unplugging the last plugin does not hand the hook lane back to the legacy
  per-call scan — which would have loaded the unplugged plugin straight off disk
  and run it again. (`test_sync_does_not_overrule_a_deliberate_unplug`,
  `test_unplugging_everything_does_not_hand_the_lane_back_to_the_scan`.)
- **Neither mount at startup can cost the other.** The supervisor and the three
  system services are two independent mounts and get a handler each. Sharing one
  meant a failure mounting the second dropped the first one's handle — a
  supervisor still on the bus that nothing could dispose at cleanup, and that
  `/api/plugins/kernel` would report as "not supervised in this process" while
  its plugins answered every hook. A kernel that cannot be reached is worse than
  one that was never mounted. Cleanup unwinds them in the reverse order and
  records what it has unwound in a set placed on the app at mount time, so running
  it twice unmounts nothing twice and a third-party `dispose` that raises does not
  leave the other half mounted — and nothing is written to the app at cleanup,
  because aiohttp freezes it before `on_cleanup` runs and writing to a frozen app
  is deprecated once per teardown.
  (`tests/test_plugin_startup_wiring.py`: each mount failing in turn, both
  failing, both succeeding, the disposal order, a raising `dispose`, a second
  cleanup, no `DeprecationWarning` on a frozen app — and that the server's own
  handlers are the callers.)
- **Unmounting leaves nothing behind on the kernel root.** A mount forks a child
  scope, and the parent holds `child.dispose` so the child cannot outlive it —
  but nothing removed that entry when the child disposed itself, so every reload,
  replug and swap added one permanently: about 410 bytes each, and the root's undo
  count rose 10 → 110 over 100 live mounts. A disposing scope drops its own entry
  now, and the count is published as `root_effects` in `seam_report`, which the
  status route returns. (`test_a_child_that_disposes_itself_stops_weighing_on_its_parent`,
  `test_a_hundred_mounts_and_unmounts_leave_the_root_where_it_started`.)
- **An edit inside a submodule reloads too.** Without clearing `sys.modules`, the
  reload succeeds and changes nothing — a worse failure than not reloading,
  because the log says it worked. (`test_an_edit_inside_a_submodule_reloads_too`.)
- **Identical bytes are not a change.** Fingerprinting content rather than
  timestamps means a rewrite of the same code is not a reload, and an edit made
  within the same second still is. (`test_identical_code_is_not_reloaded`.)

## Why it is atomic

`swap` and `unplug` contain no `await`. On the event loop that runs a turn, a
swap is therefore indivisible: no hook dispatch can land between the old
plugin's subscriptions going away and the new plugin's arriving. That shape is
pinned by `test_a_swap_does_not_await` so it cannot be lost quietly by someone
making the function a coroutine.

## Security

Every live route requires API access **and** loopback, the status route
included. A reload imports Python from the plugins directory into the running
process; reachable from another machine, that is arbitrary code execution rather
than a plugin toggle. `test_every_route_runs_both_guards` asserts both guards
run on all five routes.

## What this does not do

- It does not give the 533 bundled extension packs a runtime. They are still a
  catalog, `plugin_systems_report` still says so, and a test still pins it.
- It does not reload Thomas's own modules — only installed plugins. A change to
  `thomas/server/...` still needs a restart.
- It does not add a panel to the web UI. The control surface is the API above
  and the supervisor object; if you would rather unplug a plugin by clicking it,
  that is a UI change on top of this, and it now has something real to call.
- A plugin holding open state (a socket, a thread) loses it across a reload. The
  kernel unwinds what a plugin registered *through it*; anything a plugin does
  behind the kernel's back is its own to clean up in a teardown hook.
