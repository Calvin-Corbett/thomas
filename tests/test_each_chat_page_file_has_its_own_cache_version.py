"""A change to one front-end file must change that file's URL and no other, and every file must still be covered."""

from __future__ import annotations

import json
import re
from pathlib import Path

from thomas.server import asset_stamps
from thomas.server.asset_stamps import CHROME_FILES, chrome_stamps, file_stamp, stamp_each_asset

WEB = Path(__file__).resolve().parents[1] / "thomas" / "server" / "web"


def site(tmp_path: Path) -> Path:
    (tmp_path / "js").mkdir()
    (tmp_path / "css").mkdir()
    (tmp_path / "js" / "a.js").write_text("one", encoding="utf-8")
    (tmp_path / "js" / "b.js").write_text("two", encoding="utf-8")
    (tmp_path / "css" / "c.css").write_text("three", encoding="utf-8")
    return tmp_path


def test_editing_one_file_changes_only_its_own_stamp(tmp_path):
    web = site(tmp_path)
    before = {rel: file_stamp(web, rel) for rel in ("js/a.js", "js/b.js", "css/c.css")}
    (web / "js" / "a.js").write_text("one, edited", encoding="utf-8")
    after = {rel: file_stamp(web, rel) for rel in before}
    assert after["js/a.js"] != before["js/a.js"]
    assert after["js/b.js"] == before["js/b.js"] and after["css/c.css"] == before["css/c.css"]


def test_the_same_bytes_keep_the_same_stamp_even_when_the_file_is_touched(tmp_path):
    web = site(tmp_path)
    first = file_stamp(web, "js/a.js")
    (web / "js" / "a.js").write_text("one", encoding="utf-8")  # same bytes, newer modified time
    asset_stamps._seen.clear()
    assert file_stamp(web, "js/a.js") == first


def test_every_static_asset_url_gets_its_own_stamp_and_unreadable_ones_keep_the_page_stamp(tmp_path):
    web = site(tmp_path)
    html = '<script src="/static/js/a.js?v=PAGE"></script><link href="/static/css/c.css?v=PAGE"><script src="/static/js/gone.js?v=PAGE"></script><img src="/static/x.png?v=PAGE">'
    out = stamp_each_asset(html, web, "PAGE")
    assert f"/static/js/a.js?v={file_stamp(web, 'js/a.js')}" in out
    assert f"/static/css/c.css?v={file_stamp(web, 'css/c.css')}" in out
    assert "/static/js/gone.js?v=PAGE" in out and "/static/x.png?v=PAGE" in out  # not ours to change


def test_the_real_chat_page_has_no_asset_left_on_the_shared_stamp():
    html = (WEB / "chat.html").read_text(encoding="utf-8")
    html = html.replace("__THOMAS_ASSET_STAMPS__", json.dumps(chrome_stamps(WEB))).replace(
        "__THOMAS_WEB_BUILD__", "SHARED"
    )
    out = stamp_each_asset(html, WEB, "SHARED")
    stamps = re.findall(r"/static/(?:js|css)/[A-Za-z0-9_./-]+\?v=([A-Za-z0-9]+)", out)
    assert len(stamps) > 90 and "SHARED" not in stamps
    assert all(re.fullmatch(r"[0-9a-f]{12}", stamp) for stamp in stamps)


def test_the_chrome_files_the_page_stamps_are_the_ones_workspace_shell_loads():
    shell = (WEB / "js" / "workspace_shell.js").read_text(encoding="utf-8")
    chain = re.findall(r'"/static/js/(browser_shell[a-z_]*\.js)"', shell[shell.index("const chain = [") :])
    assert chain and {f"js/{name}" for name in chain} | {"css/browser_shell.css"} == set(CHROME_FILES)
    assert "versionOf(chain[i])" in shell  # it reads the page's per-file versions, not one copied from a link
    html = (WEB / "chat.html").read_text(encoding="utf-8")
    names = re.search(r'forEach\(function\(n\)\{a\("preload","script","js/browser_shell_"\+n\+"\.js"\);\}\)', html)
    listed = re.search(r'\[("panel"[^\]]*)\]\.forEach', html)
    assert names and listed  # the preload builds its URLs from the same names, and the same version map
    preloaded = {f"js/browser_shell_{n.strip(chr(34))}.js" for n in listed.group(1).split(",")} | {
        "js/browser_shell.js"
    }
    assert preloaded | {"css/browser_shell.css"} == set(CHROME_FILES)
