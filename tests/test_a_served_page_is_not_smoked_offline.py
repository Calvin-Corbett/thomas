"""The offline smoke only runs on pages it could ever load (2026-09-06).

A Build run that edited Thomas's own chat shell was smoked like a generated
artifact: chat.html was opened from disk under the fake smoke host, its
``/static/...`` scripts and styles were denied (they live under
thomas/server/web and only exist at that path when the server mounts them),
and the check reported 14 missing resources. The run then spent hours adding
"smoke-mode" branches to the product so the page would boot with its modules
missing, which is the verifier bending the work.

A page whose root-absolute asset links resolve to nothing under the project
root is a served page, not a standalone artifact: the offline smoke can never
load it for reasons unrelated to the change. Such pages are left out of the
smoke, and the live-server playtest remains the check for them. A page whose
links do resolve on disk is still smoked, root-absolute or relative.
"""

from __future__ import annotations

from pathlib import Path

from thomas.tools.web_preflight import browser_smoke_files


def _write(root: Path, name: str, text: str) -> None:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_a_page_whose_root_absolute_links_resolve_nowhere_is_left_out(tmp_path: Path) -> None:
    _write(
        tmp_path, "app/chat.html", '<html><head><script src="/static/js/app.js"></script></head><body>x</body></html>'
    )
    _write(tmp_path, "app/js/app.js", "console.log('served only');")
    _write(tmp_path, "site/index.html", '<html><head><script src="./main.js"></script></head><body>y</body></html>')
    _write(tmp_path, "site/main.js", "console.log('artifact');")
    picked = browser_smoke_files(tmp_path, ["app/chat.html", "site/index.html"])
    names = {Path(p).name for p in picked}
    assert names == {"index.html"}, picked


def test_a_page_whose_root_absolute_links_resolve_on_disk_is_still_smoked(tmp_path: Path) -> None:
    _write(tmp_path, "index.html", '<html><head><script src="/js/app.js"></script></head><body>z</body></html>')
    _write(tmp_path, "js/app.js", "console.log('ok');")
    picked = browser_smoke_files(tmp_path, ["index.html"])
    assert {Path(p).name for p in picked} == {"index.html"}


def test_a_served_page_is_not_pulled_in_through_a_changed_asset_either(tmp_path: Path) -> None:
    # Only the asset changed; discovery finds chat.html links it by a
    # root-absolute path that resolves nowhere, so the page stays out.
    _write(
        tmp_path, "app/chat.html", '<html><head><script src="/static/js/app.js"></script></head><body>x</body></html>'
    )
    _write(tmp_path, "app/js/app.js", "console.log('changed');")
    picked = browser_smoke_files(tmp_path, ["app/js/app.js"])
    assert picked == [], picked
