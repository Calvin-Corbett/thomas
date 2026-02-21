# APPLY_STEPS

1) Extract the ZIP somewhere (not inside the repo).

2) Apply into the repo (Windows PowerShell example):

```powershell
cd path\to\extracted\thomas_feature_run_replay_debugger
python .\apply_feature_pack.py --repo "F:\DevHub\Thomas" --pack ".\pack"
```

This will:
- Copy new files into your repo.
- Patch the aiohttp server startup to:
  - register replay routes (`replay_debugger.setup(app)`)
  - add the observability middleware (`replay_observability_middleware`)
- Append the feature entry into `docs/FEATURE_CATALOG.md` if missing.
- Create backups for any modified files under:
  - `F:\DevHub\Thomas\.feature_backups\observability.run_replay_debugger\`

3) Run tests:

```powershell
cd "F:\DevHub\Thomas"
python -m pytest -q
```

4) Run the server and open the UI:

- UI:
  - `/replay_debugger.html?run_id=<RUN_ID>`

- APIs:
  - `GET /api/runs/{run_id}/events`
  - `POST /api/runs/{run_id}/replay/seek`
  - `POST /api/runs/{run_id}/replay/step`
  - `GET /api/runs/{run_id}/replay_stream?from=&speed=`
  - `GET /api/runs/{run_id}/export.json`

Notes:
- If auto patching fails, the apply script prints the exact manual lines to add.
