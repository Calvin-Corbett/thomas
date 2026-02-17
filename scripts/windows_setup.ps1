python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e .
# Optional:
# pip install -e ".[browser,train]"
Write-Host "Example:"
Write-Host "python -m agent_vf.cli chat --root ./runtime --text \"hello\""
