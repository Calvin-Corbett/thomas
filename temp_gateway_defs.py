from pathlib import Path

for p in sorted(Path("thomas/server/routes/gateway").glob("p*.py")):
    txt = p.read_text(encoding="utf-8", errors="ignore")
    name = p.name
    defs = []
    for line in txt.splitlines():
        if line.startswith("def "):
            defs.append(line[4 : line.find("(")])
        if len(defs) >= 6:
            break
    print(name, "|", " | ".join(defs[:6]))
