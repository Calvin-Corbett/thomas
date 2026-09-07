/* Drives browser_shell_search.js's address grammar and row rendering without
 * a browser. The module is a classic script that hangs itself off `window`,
 * so it runs in a vm context with a stub window and prints a JSON report for
 * tests/test_a_search_result_cannot_smuggle_a_script.py to assert on.
 */
import { readFileSync } from "node:fs";
import vm from "node:vm";

const source = readFileSync(process.argv[2], "utf-8");
const sandbox = { window: {}, URL, console };
vm.createContext(sandbox);
vm.runInContext(source, sandbox, { filename: "browser_shell_search.js" });

const S = sandbox.window.ThomasBrowserSearch;
if (!S) {
  console.error("browser_shell_search.js did not export ThomasBrowserSearch");
  process.exit(1);
}

// A title and a snippet are written by whoever ranks for the query.
const HOSTILE_TITLE = '</a><script>window.pwned=1</script><a href="x">';
const HOSTILE_SNIPPET = '" onmouseover="window.pwned=2" x="';

const report = {
  // Address grammar: a question becomes our own page, an address stays one.
  search_url: S.toUrl("electron webcontentsview"),
  bare_host: S.toUrl("example.com"),
  full_url: S.toUrl("https://example.com/a?b=c"),
  is_search: S.isSearchUrl(S.toUrl("who owns the moon")),
  is_search_for_site: S.isSearchUrl(S.toUrl("example.com")),
  // A query survives the round trip through the address unchanged.
  round_trip: S.queryOf(S.toUrl('a & b #c "d" 100%')),

  // Schemes: only the two that name a web page get through.
  scheme_javascript: S.webUrl("javascript:alert(1)"),
  scheme_data: S.webUrl("data:text/html,<script>alert(1)</script>"),
  scheme_file: S.webUrl("file:///C:/Windows/System32/config"),
  scheme_vbscript: S.webUrl("vbscript:msgbox(1)"),
  scheme_mixed_case: S.webUrl("JaVaScRiPt:alert(1)"),
  scheme_http: S.webUrl("http://example.com/a"),
  scheme_https: S.webUrl("https://example.com/a"),
  scheme_garbage: S.webUrl("not a url at all"),

  // Rendering: hostile text is inert, and the row still says what it is.
  row_hostile_title: S.rowHTML({ title: HOSTILE_TITLE, url: "https://example.com/a", snippet: "ok" }, 0),
  row_hostile_snippet: S.rowHTML({ title: "Fine", url: "https://example.com/a", snippet: HOSTILE_SNIPPET }, 1),
  row_plain: S.rowHTML({ title: "WebContentsView | Electron", url: "https://www.electronjs.org/docs/latest/api/web-contents-view", snippet: "A View that displays a WebContents." }, 2),
  row_no_snippet: S.rowHTML({ title: "Bare", url: "https://example.com/b", snippet: "" }, 3),
};

process.stdout.write(JSON.stringify(report));
