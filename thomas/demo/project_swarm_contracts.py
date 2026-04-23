"""Contracts and project files for the Thomas project-swarm benchmark."""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROLE_NAMES = (
    "maze topology",
    "pellet economy",
    "player controls",
    "ghost pursuit",
    "ghost ambush",
    "ghost patrol",
    "ghost randomizer",
    "power mode",
    "collision rules",
    "score HUD",
    "lives system",
    "level pacing",
    "audio feedback",
    "mobile input",
    "pause overlay",
    "win screen",
    "loss screen",
    "accessibility",
    "color theme",
    "animation polish",
    "telemetry",
    "test checklist",
    "copywriting",
    "performance budget",
    "integration QA",
)


@dataclass(frozen=True)
class ProjectLane:
    lane: int
    key: str
    title: str
    agent: str
    scope: str
    path: Path


def project_lanes(root: Path, repo_root: Path, count: int) -> list[ProjectLane]:
    modules_dir = root / "product" / "src" / "modules"
    lanes: list[ProjectLane] = []
    for lane in range(1, count + 1):
        role = ROLE_NAMES[(lane - 1) % len(ROLE_NAMES)]
        path = modules_dir / f"lane-{lane:02d}.mjs"
        lanes.append(
            ProjectLane(
                lane=lane,
                key=role.replace(" ", "_"),
                title=role.title(),
                agent=f"thomas-project-swarm-worker-{lane:02d}",
                scope=str(path.resolve().relative_to(repo_root.resolve())),
                path=path,
            )
        )
    return lanes


def write_architecture(root: Path, lanes: list[ProjectLane]) -> None:
    (root / "product" / "src" / "modules").mkdir(parents=True, exist_ok=True)
    (root / "product" / "scripts").mkdir(parents=True, exist_ok=True)
    graph = {
        "project": "Pac-Man browser game",
        "contracts": [
            {"lane": lane.lane, "key": lane.key, "title": lane.title, "owns": lane.path.name}
            for lane in lanes
        ],
        "integration": "Integrator imports every lane module, builds registry, and wires the playable game.",
    }
    (root / "ARCHITECTURE.md").write_text(
        "# Pac-Man Project Swarm Architecture\n\n"
        "Architect lane splits the game into scoped modules. Workers return structured implementation intent. "
        "The integrator composes all modules into a playable browser Pac-Man variant.\n",
        encoding="utf-8",
    )
    (root / "task_graph.json").write_text(json.dumps(graph, indent=2) + "\n", encoding="utf-8")
    (root / "scopes.txt").write_text("\n".join(lane.scope for lane in lanes) + "\n", encoding="utf-8")


def mock_worker_payload(lane: ProjectLane) -> dict[str, Any]:
    return {
        "title": lane.title,
        "summary": f"{lane.title} implementation slice for the Pac-Man project.",
        "settings": {
            "weight": lane.lane,
            "enabled": True,
            "accent": f"#{(0x223344 + lane.lane * 45691) % 0xFFFFFF:06x}",
        },
        "acceptance": [
            f"{lane.title} is represented in the integration registry",
            "Module imports without side effects",
            "The final game keeps keyboard-playable Pac-Man behavior",
        ],
    }


def render_worker_module(lane: ProjectLane, payload: dict[str, Any]) -> str:
    title = str(payload.get("title") or lane.title).strip()[:120]
    summary = str(payload.get("summary") or f"{lane.title} slice").strip()[:240]
    acceptance = payload.get("acceptance")
    if not isinstance(acceptance, list):
        acceptance = []
    checks = [str(item).strip()[:180] for item in acceptance if str(item).strip()][:5]
    if len(checks) < 3:
        checks = mock_worker_payload(lane)["acceptance"]
    settings = payload.get("settings") if isinstance(payload.get("settings"), dict) else {}
    feature = {
        "laneId": f"lane-{lane.lane:02d}",
        "key": lane.key,
        "title": title or lane.title,
        "summary": summary or f"{lane.title} slice",
        "settings": settings,
        "acceptance": checks,
    }
    return f"export const moduleSpec = {json.dumps(feature, indent=2)};\n"


def write_worker_module(lane: ProjectLane, module_text: str) -> None:
    if lane.path.resolve().parent.name != "modules":
        raise ValueError(f"lane path escaped modules directory: {lane.path}")
    lane.path.write_text(module_text, encoding="utf-8")


def write_integrated_game(root: Path, lanes: list[ProjectLane]) -> None:
    product = root / "product"
    (product / "src").mkdir(parents=True, exist_ok=True)
    (product / "index.html").write_text(_index_html(), encoding="utf-8")
    (product / "src" / "styles.css").write_text(_styles_css(), encoding="utf-8")
    (product / "src" / "registry.mjs").write_text(_registry_js(lanes), encoding="utf-8")
    (product / "src" / "game.mjs").write_text(_game_js(), encoding="utf-8")
    (product / "scripts" / "evaluate.mjs").write_text(_evaluator_js(len(lanes)), encoding="utf-8")


def evaluate_project(root: Path) -> dict[str, Any]:
    proc = subprocess.run(
        ["node", str(root / "product" / "scripts" / "evaluate.mjs")],
        cwd=str(root / "product"),
        text=True,
        capture_output=True,
        check=False,
    )
    try:
        payload = json.loads(proc.stdout.strip() or "{}")
    except json.JSONDecodeError as exc:
        payload = {"passed": 0, "failed": 1, "parse_error": str(exc)}
    payload.update({"returncode": proc.returncode, "stdout": proc.stdout, "stderr": proc.stderr})
    return payload


def evaluate_baseline_product(root: Path) -> dict[str, Any]:
    required = ["index.html", "src/game.mjs", "src/styles.css"]
    missing = [rel for rel in required if not (root / rel).exists()]
    text = "\n".join((root / rel).read_text(encoding="utf-8", errors="replace") for rel in required if (root / rel).exists())
    checks = {
        "required_files": not missing,
        "canvas": "canvas" in text.lower(),
        "keyboard": "keydown" in text.lower() or "keyup" in text.lower(),
        "ghosts": "ghost" in text.lower(),
        "pellets": "pellet" in text.lower(),
        "power": "power" in text.lower(),
        "loop": "requestanimationframe" in text.lower(),
    }
    passed = sum(1 for ok in checks.values() if ok)
    return {"passed": passed, "failed": len(checks) - passed, "checks": checks, "missing": missing}


def count_lines(root: Path) -> dict[str, int]:
    total = 0
    nonblank = 0
    for path in root.rglob("*"):
        if not path.is_file() or ".git" in path.parts:
            continue
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        total += len(lines)
        nonblank += sum(1 for line in lines if line.strip())
    return {"total": total, "nonblank": nonblank}


def copy_tree(src: Path, dst: Path) -> None:
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns(".git"))


def _index_html() -> str:
    return (
        "<!doctype html><html><head><meta charset=\"utf-8\"><title>Thomas Pac-Man Swarm</title>"
        "<link rel=\"stylesheet\" href=\"./src/styles.css\"></head><body><main><h1>Thomas Pac-Man</h1>"
        "<canvas id=\"game\" width=\"608\" height=\"672\"></canvas><section id=\"hud\"></section>"
        "<p>Arrow keys move. Eat pellets, use power pellets, avoid ghosts.</p></main>"
        "<script type=\"module\" src=\"./src/game.mjs\"></script></body></html>\n"
    )


def _styles_css() -> str:
    return (
        "body{margin:0;background:#070914;color:#f6eec9;font-family:Verdana,sans-serif;display:grid;place-items:center}"
        "main{width:min(94vw,760px);text-align:center}canvas{background:#02040a;border:6px solid #173bff;"
        "box-shadow:0 0 40px #173bff55;max-width:100%;image-rendering:pixelated}#hud{display:flex;"
        "justify-content:center;gap:20px;margin:12px;color:#ffd447;font-weight:700}"
    )


def _registry_js(lanes: list[ProjectLane]) -> str:
    imports = "\n".join(
        f"import {{ moduleSpec as lane{i} }} from './modules/lane-{i:02d}.mjs';" for i in range(1, len(lanes) + 1)
    )
    rows = ", ".join(f"lane{i}" for i in range(1, len(lanes) + 1))
    return f"{imports}\n\nexport const swarmModules = [{rows}];\n"


def _game_js() -> str:
    return """
import { swarmModules } from './registry.mjs';
const canvas = document.querySelector('#game');
const hud = document.querySelector('#hud');
const ctx = canvas.getContext('2d');
const tile = 32;
const map = [
'###################','#........#........#','#.##.###.#.###.##.#','#o...............o#',
'#.##.#.#####.#.##.#','#....#...#...#....#','####.### # ###.####','   #.#       #.#   ',
'####.# ## ## #.####','#......#   #......#','####.# ##### #.####','   #.#       #.#   ',
'####.# ##### #.####','#........#........#','#.##.###.#.###.##.#','#o.#.....P.....#.o#',
'##.#.#.#####.#.#.##','#....#...#...#....#','#.######.#.######.#','#.................#','###################'];
let player = {x:9,y:15,dx:0,dy:0,nextX:0,nextY:0};
let ghosts = [{x:9,y:9,c:'#ff4b5c'},{x:8,y:9,c:'#ff9ff3'},{x:10,y:9,c:'#48dbfb'},{x:9,y:10,c:'#feca57'}];
let score = 0, lives = 3, powerTimer = 0, won = false;
const pellets = new Set();
map.forEach((row,y)=>[...row].forEach((cell,x)=>{ if(cell==='.'||cell==='o') pellets.add(`${x},${y}`); }));
function wall(x,y){ return (map[y]?.[x] || '#') === '#'; }
function key(e){ const dirs={ArrowLeft:[-1,0],ArrowRight:[1,0],ArrowUp:[0,-1],ArrowDown:[0,1]}; if(dirs[e.key]) [player.nextX,player.nextY]=dirs[e.key]; }
addEventListener('keydown', key);
function stepActor(a, chase=true){
  const choices=[[1,0],[-1,0],[0,1],[0,-1]].filter(([dx,dy])=>!wall(a.x+dx,a.y+dy));
  choices.sort((p,q)=>((a.x+p[0]-player.x)**2+(a.y+p[1]-player.y)**2)-((a.x+q[0]-player.x)**2+(a.y+q[1]-player.y)**2));
  const pick = chase && !powerTimer ? choices[0] : choices[Math.floor(Math.random()*choices.length)];
  if(pick){ a.x+=pick[0]; a.y+=pick[1]; }
}
function update(){
  if(won || lives<=0) return;
  if(!wall(player.x+player.nextX, player.y+player.nextY)){ player.dx=player.nextX; player.dy=player.nextY; }
  if(!wall(player.x+player.dx, player.y+player.dy)){ player.x+=player.dx; player.y+=player.dy; }
  const key=`${player.x},${player.y}`;
  if(pellets.delete(key)){ score += map[player.y][player.x] === 'o' ? 50 : 10; if(map[player.y][player.x] === 'o') powerTimer=35; }
  ghosts.forEach(g=>stepActor(g));
  ghosts.forEach(g=>{ if(g.x===player.x&&g.y===player.y){ if(powerTimer){ score+=200; g.x=9; g.y=9; } else { lives-=1; player.x=9; player.y=15; } } });
  if(powerTimer) powerTimer -= 1;
  won = pellets.size === 0;
}
function draw(){
  ctx.clearRect(0,0,canvas.width,canvas.height);
  map.forEach((row,y)=>[...row].forEach((cell,x)=>{ if(cell==='#'){ctx.fillStyle='#173bff';ctx.fillRect(x*tile,y*tile,tile,tile);} }));
  pellets.forEach(p=>{ const [x,y]=p.split(',').map(Number); ctx.fillStyle=map[y][x]==='o'?'#fff':'#ffd447'; ctx.beginPath(); ctx.arc(x*tile+16,y*tile+16,map[y][x]==='o'?7:3,0,7); ctx.fill(); });
  ctx.fillStyle='#ffe14d'; ctx.beginPath(); ctx.arc(player.x*tile+16,player.y*tile+16,13,0.25,6.0); ctx.lineTo(player.x*tile+16,player.y*tile+16); ctx.fill();
  ghosts.forEach(g=>{ctx.fillStyle=powerTimer?'#334dff':g.c;ctx.fillRect(g.x*tile+6,g.y*tile+6,20,20);});
  hud.textContent=`Score ${score} | Lives ${lives} | Modules ${swarmModules.length} | ${won?'YOU WIN':lives<=0?'GAME OVER':powerTimer?'POWER':''}`;
}
function loop(){ update(); draw(); requestAnimationFrame(loop); }
loop();
""".lstrip()


def _evaluator_js(expected_count: int) -> str:
    return f"""
import {{ swarmModules }} from '../src/registry.mjs';
import fs from 'node:fs';
const game = fs.readFileSync(new URL('../src/game.mjs', import.meta.url), 'utf8').toLowerCase();
const checks = {{
  module_count: swarmModules.length === {expected_count},
  unique_lanes: new Set(swarmModules.map((m) => m.laneId)).size === {expected_count},
  playable_canvas: game.includes('canvas') && game.includes('requestanimationframe'),
  pacman_rules: game.includes('pellets') && game.includes('ghosts') && game.includes('powertimer'),
  controls: game.includes('keydown') && game.includes('arrowleft'),
  integration: game.includes('swarmmodules.length'),
}};
const passed = Object.values(checks).filter(Boolean).length;
const failed = Object.values(checks).length - passed;
console.log(JSON.stringify({{ passed, failed, checks, module_count: swarmModules.length }}, null, 2));
process.exit(failed === 0 ? 0 : 1);
""".lstrip()
