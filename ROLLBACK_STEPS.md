# ROLLBACK_STEPS

1) Roll back the feature pack changes:

```powershell
cd path\to\extracted\thomas_feature_run_replay_debugger
python .\rollback_feature_pack.py --repo "F:\DevHub\Thomas"
```

2) (Optional) Delete backups:

```powershell
Remove-Item -Recurse -Force "F:\DevHub\Thomas\.feature_backups\observability.run_replay_debugger"
```
