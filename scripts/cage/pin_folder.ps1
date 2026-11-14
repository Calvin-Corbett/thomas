# Dot-sourced by the pin scripts. One folder holds every pin (the cage posture,
# the card catalogue's hash), and it has to be a folder an unelevated process can
# neither write into nor empty.
#
# Why its own folder, measured 2026-09-22: pins used to sit in
# C:\ProgramData\ThomasCage, where the owner's account holds FullControl so it can
# run the cage channels. FullControl on a folder includes delete-child, which
# removes any file inside regardless of that file's own permissions -- a plain
# [IO.File]::Delete from an unelevated shell removed an Administrators-only pin.
# (PowerShell's Remove-Item -Force reported "access denied" first, because it
# tries to clear attributes before deleting; that false negative nearly passed as
# proof it was safe.) C:\ProgramData lets ordinary users create folders, never
# remove one someone else owns, so a folder created and owned here, by an elevated
# script, is one the owner's unelevated processes cannot empty or rename.

$script:PinTrustedSids = @('S-1-5-18', 'S-1-5-32-544')  # SYSTEM, Administrators

function Set-PinFolderAcl {
    param([Parameter(Mandatory = $true)][string]$PinRoot)
    # The folder only. This once ran with /T, which pushed the folder's rights
    # onto every pin already inside: each file lost its inherited access, the
    # folder-style (OI)(CI) grants do not apply to a file, and /C /Q swallowed
    # the errors -- so the second pin written left the first readable by no one
    # (measured 2026-09-22; tests/test_a_second_pin_keeps_the_first_readable.py).
    # Exit codes decide, not stderr: under Stop, Windows PowerShell turns a native
    # tool's first stderr line into a terminating error when output is redirected.
    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        & icacls $PinRoot /inheritance:r /grant:r "*S-1-5-18:(OI)(CI)F" "*S-1-5-32-544:(OI)(CI)F" "*S-1-5-32-545:(OI)(CI)RX" /Q 2>$null | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "icacls returned $LASTEXITCODE for $PinRoot" }
        # Existing pins take the folder's permissions by inheriting them. A pin
        # whose permissions were emptied cannot be reset even elevated until
        # ownership is taken back (measured 2026-09-22), so take it first; unelevated
        # (the test) takeown fails harmlessly and the owner's own reset still works.
        foreach ($pin in Get-ChildItem -LiteralPath $PinRoot -File -Force) {
            & takeown /F $pin.FullName /A 2>$null | Out-Null
            & icacls $pin.FullName /reset /Q 2>$null | Out-Null
            if ($LASTEXITCODE -ne 0) { throw "icacls /reset returned $LASTEXITCODE for $($pin.FullName)" }
        }
    }
    finally {
        $ErrorActionPreference = $previous
    }
}

function Initialize-PinFolder {
    param([Parameter(Mandatory = $true)][string]$PinRoot)

    if (-not (Test-Path -LiteralPath $PinRoot)) {
        New-Item -ItemType Directory -Path $PinRoot -Force | Out-Null
    }
    # Ownership first: an owner can always rewrite permissions, so a folder that
    # someone else created before this ran (squatting) is taken back before
    # anything is trusted about it. Well-known SIDs, not names, so this does not
    # depend on the system language.
    # takeown first: /setowner cannot reach a pin whose permissions were emptied.
    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        & takeown /F $PinRoot /A /R /D Y 2>$null | Out-Null
        & icacls $PinRoot /setowner "*S-1-5-32-544" /T /C /Q 2>$null | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "icacls /setowner returned $LASTEXITCODE for $PinRoot" }
    }
    finally {
        $ErrorActionPreference = $previous
    }
    Set-PinFolderAcl -PinRoot $PinRoot

    # Then prove it rather than trust the commands that set it.
    $acl = Get-Acl -LiteralPath $PinRoot
    $owner = $acl.GetOwner([Security.Principal.SecurityIdentifier]).Value
    if ($owner -notin $script:PinTrustedSids) { throw "pin folder is owned by $owner, not Administrators" }
    $bad = $acl.Access | Where-Object {
        $_.AccessControlType -eq 'Allow' -and
        ($_.FileSystemRights.ToString() -match 'Write|Modify|FullControl|Delete|ChangePermissions|TakeOwnership') -and
        ($_.IdentityReference.Translate([Security.Principal.SecurityIdentifier]).Value -notin $script:PinTrustedSids)
    }
    if ($bad) {
        throw ("pin folder has unexpected writers: " + (($bad | ForEach-Object { $_.IdentityReference.Value }) -join ', '))
    }
}

function Get-NormalizedSha256 {
    param([Parameter(Mandatory = $true)][string]$Path)
    # Byte for byte what thomas/tools/trusted_card.py computes: every CR directly
    # followed by LF is dropped, nothing else changes. Computed here, by the
    # elevated script, never by asking the file about itself -- a tampered
    # catalogue could report any hash it liked about its own contents.
    $bytes = [System.IO.File]::ReadAllBytes($Path)
    $normalized = New-Object System.IO.MemoryStream
    for ($i = 0; $i -lt $bytes.Length; $i++) {
        if ($bytes[$i] -eq 13 -and ($i + 1) -lt $bytes.Length -and $bytes[$i + 1] -eq 10) { continue }
        $normalized.WriteByte($bytes[$i])
    }
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try { $hash = $sha.ComputeHash($normalized.ToArray()) } finally { $sha.Dispose() }
    return (($hash | ForEach-Object { $_.ToString('x2') }) -join '')
}

function Write-PinFile {
    param(
        [Parameter(Mandatory = $true)][string]$PinRoot,
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$Value
    )
    $path = Join-Path $PinRoot $Name
    # No BOM: readers strip whitespace, and a BOM is not whitespace. Windows
    # PowerShell's -Encoding utf8 writes one, so .NET writes the file instead.
    [System.IO.File]::WriteAllText($path, $Value, (New-Object System.Text.UTF8Encoding($false)))
    # Inherit the locked folder's permissions, whatever the file had before.
    & icacls $path /reset /C /Q | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "icacls /reset returned $LASTEXITCODE for $path" }
    return $path
}
