import json, re, subprocess, pathlib
from collections import OrderedDict

BASE_T = pathlib.Path(r'F:/DevHub/Thomas')
BASE_O = pathlib.Path(r'F:/DevHub/_tmp_openclaw_count_1771454552')


def run(cmd, cwd):
    proc = subprocess.run(cmd, cwd=str(cwd), shell=True, capture_output=True, text=False)
    out = proc.stdout + proc.stderr
    for enc in ("utf-8", "utf-16", "utf-16-le", "utf-16-be", "latin-1"):
        try:
            return out.decode(enc, errors="ignore")
        except Exception:
            pass
    return out.decode('utf-8', errors='ignore')


def parse_children(txt):
    lines = txt.splitlines()
    section = False
    children = []
    for line in lines:
        if line.strip().startswith("Commands:"):
            section = True
            continue
        if not section:
            continue
        if line.strip().startswith("Examples:"):
            break
        if line.strip().startswith("Hint:"):
            continue
        if line.startswith("  "):
            s = line.strip()
            if not s:
                continue
            if s.startswith("--"):
                continue
            m = re.match(r'(?P<name>[^\s]+)(\s*\*)?', s)
            if m:
                name = m.group('name')
                if name and name not in ("Help", "Examples:"):
                    children.append(name)
        elif line and not line.startswith("    ") and line.strip():
            if section:
                break
    return children


def parse_top(txt):
    cmds = []
    sec = False
    for line in txt.splitlines():
        if line.strip().startswith("Commands:"):
            sec = True
            continue
        if not sec:
            continue
        if line.strip().startswith("Hint:"):
            continue
        if line.strip().startswith("Examples:"):
            break
        if line.startswith('  '):
            s = line.strip()
            if not s:
                continue
            m = re.match(r'(?P<name>[^\s]+)(\s*\*)?', s)
            if m:
                cmds.append(m.group('name').strip())
        elif sec and line.strip():
            break
    return cmds

th_help = run('python -m thomas --help', BASE_T)
oc_help = run('node openclaw.mjs --help', BASE_O)
th_cmds = parse_top(th_help)
oc_cmds = parse_top(oc_help)

families = sorted(set(th_cmds) | set(oc_cmds))
report = OrderedDict()

for cmd in families:
    if cmd in ("help",):
        continue
    cmd_th = cmd in th_cmds
    cmd_oc = cmd in oc_cmds
    th_children = parse_children(run(f'python -m thomas {cmd} --help', BASE_T)) if cmd_th else []
    oc_children = parse_children(run(f'node openclaw.mjs {cmd} --help', BASE_O)) if cmd_oc else []
    report[cmd] = {
        'thomas_present': cmd_th,
        'openclaw_present': cmd_oc,
        'thomas_children': th_children,
        'openclaw_children': oc_children,
        'thomas_depth': len(th_children),
        'openclaw_depth': len(oc_children),
    }

for cmd, data in report.items():
    if data['thomas_present'] and data['openclaw_present']:
        if data['thomas_depth'] != data['openclaw_depth']:
            print(f"{cmd}: thomas {data['thomas_depth']} vs openclaw {data['openclaw_depth']}")
            th_only = sorted(set(data['thomas_children']) - set(data['openclaw_children']))
            oc_only = sorted(set(data['openclaw_children']) - set(data['thomas_children']))
            if th_only:
                print('  thomas-only:', th_only)
            if oc_only:
                print('  openclaw-only:', oc_only)

out = BASE_T / 'thomas_vs_openclaw_subcommands.json'
with out.open('w', encoding='utf-8') as f:
    json.dump(report, f, indent=2)
print('saved', out)
