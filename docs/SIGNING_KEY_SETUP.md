# Signing-Key Setup (the product owner's runbook)

This is the runbook the product owner runs on his dev machine to enable signed
commits — layers 2 and 3 of the safety architecture
(see [SAFETY_ARCHITECTURE.md](SAFETY_ARCHITECTURE.md)).

**Time**: ~15 minutes for the recommended path, ~5 minutes for the simpler
path. One-time setup; never has to be re-done unless you reformat or
migrate machines.

**What this does**: Configures git so every commit you make is
cryptographically signed. The signing key is held by the OS (Windows
Credential Manager / OpenSSH Agent), and accessing it requires either a
passphrase (simple path) or Windows Hello biometric/PIN (recommended
path).

**Why this matters**: After this runs, even if an AI agent executes
`git commit --no-verify`, the resulting commit will be **unsigned**.
GitHub branch protection rejects unsigned commits to `dev` and `main`,
so the agent's commit cannot land. See
[BRANCH_PROTECTION_SETUP.md](BRANCH_PROTECTION_SETUP.md) for the
GitHub-side configuration that completes the loop.

Local note: Thomas also installs a `prepare-commit-msg` guard through
`scripts/install_commit_breakglass_hooks.py`. Because Git does not skip
that hook with `--no-verify`, a local no-verify commit now requires the
Windows credential-dialog breakglass flow unless pre-commit already
passed for the exact staged tree.

---

## Pick a path

### Path A — SSH signing with Windows Hello (RECOMMENDED)

- Signing key lives in OpenSSH Agent backed by Windows Credential Manager.
- Each signing operation pops a Windows Hello PIN/biometric prompt.
- Hardware-bound to your machine + your physical presence (PIN/biometric).
- Best security; what the PROBLEM.md architecture targets.

### Path B — SSH signing with passphrase (SIMPLER)

- Signing key is an SSH key file on disk, encrypted with a passphrase.
- Each signing operation requires typing your passphrase.
- No biometric integration; passphrase-only is software-recoverable.
- Use this if Path A's Windows Hello integration won't cooperate.

**Honest tradeoff**: Path A is hardware-bound. Path B is "something you
know" only. Both make `--no-verify` ineffective for agents, but Path A
also defeats a scenario where someone copies your SSH key off your disk.

Both paths use SSH signing (not GPG). SSH signing landed in Git 2.34 and
is simpler than GPG on Windows.

---

## Prerequisites (both paths)

Open PowerShell as your normal user (NOT admin).

```powershell
# 1) Verify Git version is 2.34+ (SSH signing support)
git --version
# Expected: git version 2.34 or higher (Windows binaries are typically 2.40+)

# 2) Verify OpenSSH is installed (it's built into Win 10/11)
ssh -V
# Expected: OpenSSH_for_Windows_8.x or 9.x (or newer)
```

If either is missing, install Git for Windows (https://git-scm.com/download/win)
and enable the OpenSSH client via Windows Settings → Apps → Optional
Features → "OpenSSH Client".

---

## Path A — SSH signing with Windows Hello

### Step 1. Start the OpenSSH Authentication Agent service

```powershell
# Set to start automatically + start now
Set-Service ssh-agent -StartupType Automatic
Start-Service ssh-agent
Get-Service ssh-agent
# Expected: Status=Running, StartType=Automatic
```

### Step 2. Generate an SSH key (ed25519, no passphrase — Win Hello will gate it)

```powershell
# Use a dedicated key for signing (separate from your GitHub auth key
# if you want; you can also reuse the same key for both).
$signingKey = "$env:USERPROFILE\.ssh\id_ed25519_signing"

# -t ed25519: modern, fast, short keys
# -C: comment (shows in commit signature; use your email)
# -N "": no passphrase — Windows Hello will gate access instead
ssh-keygen -t ed25519 -f "$signingKey" -C "your-email@example.com" -N '""'
# Expected: creates id_ed25519_signing (private) + id_ed25519_signing.pub (public)
```

### Step 3. Add the key to the OpenSSH agent

```powershell
ssh-add "$signingKey"
# Expected: "Identity added: <path>"
```

### Step 4. Bind Windows Hello to the agent's key access

This is the key biometric-binding step. Microsoft's docs:
https://docs.microsoft.com/en-us/windows-server/administration/openssh/openssh_keymanagement#bind-the-key

```powershell
# Configure the agent to require user presence (Windows Hello) for
# each signing operation. This uses Windows Credential Manager as the
# protected store.
#
# Note: this step's exact mechanism varies by Windows build. The
# verification step below confirms it's working.
```

If your Windows build doesn't pop Win Hello on `ssh-add`, you'll
fall back to Path B passphrase. The Step 8 verification will tell you
which mode you're in.

### Step 5. Configure git to sign commits with this key

```powershell
git config --global gpg.format ssh
git config --global user.signingkey "$env:USERPROFILE\.ssh\id_ed25519_signing.pub"
git config --global commit.gpgsign true
git config --global tag.gpgsign true

# Verify:
git config --global --get-regexp '^(commit|tag|gpg|user)\.' | Sort-Object
# Expected:
#   commit.gpgsign true
#   gpg.format ssh
#   tag.gpgsign true
#   user.signingkey C:\Users\corbe\.ssh\id_ed25519_signing.pub
```

### Step 6. Configure the allowed-signers file (for local verification)

```powershell
# Tells `git log --show-signature` who to trust.
$allowedSigners = "$env:USERPROFILE\.ssh\allowed_signers"
$pubKey = Get-Content "$env:USERPROFILE\.ssh\id_ed25519_signing.pub"
"your-email@example.com $pubKey" | Out-File -Encoding utf8 -NoNewline $allowedSigners
git config --global gpg.ssh.allowedSignersFile "$allowedSigners"
```

### Step 7. Upload the public key to GitHub as a "Signing Key"

1. Copy the public key to your clipboard:
   ```powershell
   Get-Content "$env:USERPROFILE\.ssh\id_ed25519_signing.pub" | Set-Clipboard
   ```
2. Open https://github.com/settings/keys
3. Click "New SSH key"
4. Title: `Thomas dev signing key (Windows Hello)`
5. Key type: select **Signing Key** (NOT Authentication Key)
6. Paste the key. Click "Add SSH key".

GitHub uses this to mark commits as "Verified" in the UI and to
enforce the "Require signed commits" branch protection rule.

### Step 8. Verify with a test commit

```powershell
cd C:\Users\corbe\Thomas

# Make an empty test commit
git commit --allow-empty -m "test: signing setup verification"
```

**Expected**:
- A Windows Hello PIN/biometric prompt pops up (Path A success!)
- OR you're prompted for an SSH passphrase (Path B fallback)
- OR the commit completes silently and is unsigned (signing not active)

Then check the signature:

```powershell
git log --show-signature -1
```

**Expected**:
```
commit <sha>
Good "ssh-ed25519:..." signature for your-email@example.com
...
```

If you see "Good ... signature", **signing works**. Move to
BRANCH_PROTECTION_SETUP.md.

If you see "No signature" or an error, see Troubleshooting below.

### Step 9. Clean up the test commit (don't push it)

```powershell
# Soft reset removes the test commit but keeps no changes (it was empty).
git reset --soft HEAD~1
```

---

## Path B — SSH signing with passphrase (simpler fallback)

Same as Path A but skip Step 4 (no Win Hello binding) and replace
Step 2's `-N '""'` with a passphrase:

```powershell
$signingKey = "$env:USERPROFILE\.ssh\id_ed25519_signing"
ssh-keygen -t ed25519 -f "$signingKey" -C "your-email@example.com"
# It will prompt for a passphrase. Use something memorable but long
# (12+ chars). You'll type it each commit unless you `ssh-add` it
# into the agent for the session.
```

Then continue with Steps 3, 5, 6, 7, 8, 9 of Path A — they're the same.

When you commit, you'll be prompted for the passphrase (or `ssh-add`
once per session to cache it in the OpenSSH agent).

---

## Troubleshooting

### "git commit" doesn't pop any prompt, commits silently

`commit.gpgsign` may not be set, or `gpg.format` isn't `ssh`. Re-run
Step 5's verification command.

### "error: cannot run gpg: No such file or directory"

`gpg.format` is still `openpgp` (the default). Re-run Step 5.

### "No principal matched" when verifying

The allowed-signers file is missing or doesn't include your email +
your public key. Re-run Step 6.

### Win Hello prompt doesn't appear (you wanted Path A, got Path B)

Path A's Windows Hello binding (Step 4) is build-dependent. On Windows
11 with recent updates, OpenSSH supports this via the "Microsoft SSH
Agent" service that integrates with WCM. If it's not firing:

- Check `Get-Service ssh-agent` is running.
- Check there's no passphrase on the key (Path A requires unset passphrase).
- As a workaround, use Path B with passphrase. The architecture still
  works; passphrase-protected SSH keys are not agent-accessible.
- For the strongest hardware-binding, use a YubiKey:
  ```powershell
  ssh-keygen -t ed25519-sk -O resident -O verify-required -f ~/.ssh/id_yubikey_signing
  ```
  This stores the private key on the YubiKey itself; each signing
  requires you to physically touch the YubiKey.

### "remote: error: ... commit must be signed"

Branch protection is working — GitHub is rejecting your unsigned
commit. Either configure signing per this doc, or for legitimate
unsigned commits (e.g., merge commits from upstream), branch
protection has to be updated by the product owner.

### Test commit pushed to remote by accident

```powershell
# If you pushed:
git push --delete origin <branch-or-tag-name>
# Or revert the commit:
git revert HEAD --no-edit
git push
```

---

## What this enables

After this runs successfully on the product owner's machine:

- Every `git commit` the product owner makes is signed.
- `git commit --no-verify` from any agent or compromised credential
  on the product owner's machine that doesn't have signing configured produces
  an unsigned commit.
- Unsigned commits to `dev` or `main` (after branch protection is
  enabled per BRANCH_PROTECTION_SETUP.md) get rejected at push time
  by GitHub.
- The path "agent runs `git commit --no-verify`" stops working.

This closes the bypass demonstrated on 2026-05-26 (PROBLEM.md
"Concrete proof the current state isn't safety").

---

## Next step

After this, run [BRANCH_PROTECTION_SETUP.md](BRANCH_PROTECTION_SETUP.md)
to wire the GitHub side: branch protection rules + "Require signed
commits" + the `gates-required` status check.
