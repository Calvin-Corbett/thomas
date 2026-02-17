# Windows Service Install (Broker)

Goal: run the broker outside your interactive user session.

## Option A: LocalService (built-in)
1) Use a DB path accessible to the service:
   C:\ProgramData\ThomasVault\vault.db

2) In Admin PowerShell:
```powershell
$Node = (Get-Command node).Source
$Repo = "C:\path\to\thomas-vault-fortress"
$Db = "C:\ProgramData\ThomasVault\vault.db"
sc.exe create ThomasVaultBroker binPath= "\"$Node\" \"$Repo\dist\broker\main.js\" --db \"$Db\"" start= auto obj= "NT AUTHORITY\LocalService"
sc.exe description ThomasVaultBroker "Thomas Vault Broker (IPC only)"
sc.exe start ThomasVaultBroker
```

3) UI runs as you and connects via named pipe.
