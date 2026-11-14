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

/* recordStep writes on the tab it is given, so each case gets its own and the
 * two lists it maintains are read back out. */
const A = "thomas://search?q=a";
const B = "thomas://search?q=b";
function rec(tab, url, step, native) {
  S.recordStep(tab, url, step, native);
  return { trail: tab.trail || [], ahead: tab.ahead || [] };
}

const report = {
  // Address grammar: a question becomes our own page, an address stays one.
  search_url: S.toUrl("electron webcontentsview"),
  bare_host: S.toUrl("example.com"),
  full_url: S.toUrl("https://example.com/a?b=c"),
  uppercase_url: S.toUrl("HTTPS://example.com/a"),
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
  row_hostile_host: S.rowHTML({ title: "Fine", url: "https://example.com%22%20onmouseover%3Dalert(1).test/a", snippet: "" }, 4),

  // Back: who owes the step. In the browser the page sits in a frame on
  // somebody else's origin, whose history this document may not touch, so the
  // record this chrome kept is the only one there is.
  back_frame_from_search: S.backStep({ kind: "web", searchOrigin: "thomas://search?q=a" }),
  back_frame_plain: S.backStep({ kind: "web" }),
  back_on_results_page: S.backStep({ kind: "search", searchOrigin: "thomas://search?q=a" }),
  back_on_new_tab: S.backStep({ kind: "ntp" }),
  back_no_tab: S.backStep(null),
  back_view_asks_first: S.backStep({ kind: "web", desktop: true, searchOrigin: "thomas://search?q=a" }),
  back_view_did_not_move: S.backStep({ kind: "web", desktop: true, searchOrigin: "thomas://search?q=a" }, false),
  back_view_moved: S.backStep({ kind: "web", desktop: true, searchOrigin: "thomas://search?q=a" }, true),
  back_view_stuck_without_search: S.backStep({ kind: "web", desktop: true }, false),
  // A page this chrome navigated to itself comes back before the results do.
  back_trail_before_search: S.backStep({ kind: "web", searchOrigin: "thomas://search?q=a", trail: ["https://example.com/a"] }),
  back_trail_spent: S.backStep({ kind: "web", searchOrigin: "thomas://search?q=a", trail: [] }),
  back_trail_without_search: S.backStep({ kind: "web", trail: ["https://example.com/a"] }),
  back_trail_ignored_on_desktop: S.backStep({ kind: "web", desktop: true, trail: ["https://example.com/a"] }),
  // A desktop view that has reported an empty history is answered before the
  // click, so the button can be dark instead of lit and inert.
  back_view_reported_empty: S.backStep({ kind: "web", desktop: true, canBack: false }),
  back_view_reported_empty_from_search: S.backStep({ kind: "web", desktop: true, canBack: false, searchOrigin: "thomas://search?q=a" }),
  back_view_reported_history: S.backStep({ kind: "web", desktop: true, canBack: true }),
  back_view_never_reported: S.backStep({ kind: "web", desktop: true, canBack: undefined }),
  // A view holds only the pages opened since it was made, and a results page
  // closes one. Its end is not the end of the tab: what this chrome recorded
  // is asked next, exactly as it is in the plain browser.
  back_view_empty_falls_back_to_trail: S.backStep({ kind: "web", desktop: true, canBack: false, trail: [A] }),
  back_stuck_view_falls_back_to_trail: S.backStep({ kind: "web", desktop: true, trail: [A] }, false),
  back_moving_view_leaves_the_trail_alone: S.backStep({ kind: "web", desktop: true, trail: [A] }, true),

  // Forward: the twin of Back. Every page Back stepped off is a page Forward
  // owes, and the results page is the one page here you arrive at backwards.
  fwd_ahead_from_results: S.forwardStep({ kind: "search", ahead: ["https://example.com/a"] }),
  fwd_results_with_nothing_ahead: S.forwardStep({ kind: "search" }),
  fwd_web_with_ahead: S.forwardStep({ kind: "web", ahead: ["https://example.com/a"] }),
  fwd_web_ahead_spent: S.forwardStep({ kind: "web", ahead: [] }),
  fwd_web_plain: S.forwardStep({ kind: "web" }),
  fwd_view_asks_first: S.forwardStep({ kind: "web", desktop: true }),
  fwd_view_answered: S.forwardStep({ kind: "web", desktop: true }, true),
  fwd_on_new_tab: S.forwardStep({ kind: "ntp", ahead: ["https://example.com/a"] }),
  fwd_no_tab: S.forwardStep(null),
  fwd_view_reported_nothing_ahead: S.forwardStep({ kind: "web", desktop: true, canFwd: false }),
  fwd_view_reported_something_ahead: S.forwardStep({ kind: "web", desktop: true, canFwd: true }),
  fwd_view_never_reported: S.forwardStep({ kind: "web", desktop: true, canFwd: undefined }),
  // Search from a page, press Back to that page: the results are ahead of a
  // view made after them, so the view has nothing and the record has it all.
  fwd_view_empty_falls_back_to_ahead: S.forwardStep({ kind: "web", desktop: true, canFwd: false, ahead: [A] }),
  fwd_stuck_view_falls_back_to_ahead: S.forwardStep({ kind: "web", desktop: true, ahead: [A] }, false),
  fwd_moving_view_leaves_the_record_alone: S.forwardStep({ kind: "web", desktop: true, ahead: [A] }, true),
  // A results page is rendered by this chrome on every surface. A tab that
  // asked the desktop app for a view and searched again before it arrived is
  // still marked desktop, and must not be answered as if it had one.
  fwd_on_desktop_results_page: S.forwardStep({ kind: "search", desktop: true, ahead: ["https://example.com/a"] }),
  fwd_on_desktop_results_page_with_nothing_ahead: S.forwardStep({ kind: "search", desktop: true }),
  fwd_on_desktop_results_page_stale_report: S.forwardStep({ kind: "search", desktop: true, canFwd: true }),
  back_on_desktop_results_page: S.backStep({ kind: "search", desktop: true, canBack: true, trail: [A] }),

  // A results page is a page: refine the query and the results you refined
  // away from are behind you, reachable by Back like anything else.
  back_on_results_with_trail: S.backStep({ kind: "search", trail: [A] }),
  back_on_results_trail_spent: S.backStep({ kind: "search", trail: [] }),
  back_on_results_ignores_origin: S.backStep({ kind: "search", searchOrigin: A, trail: [] }),

  // Recording a step: where the page being left ends up.
  record_fresh: rec({ kind: "search", url: A, ahead: ["https://example.com/a"] }, B),
  record_second_search_from_a_result: rec({ kind: "web", url: "https://example.com/a", trail: [A] }, B),
  record_back: rec({ kind: "web", url: "https://example.com/b", trail: ["https://example.com/a"] }, "https://example.com/a", "back"),
  record_forward: rec({ kind: "search", url: A, ahead: ["https://example.com/a"] }, "https://example.com/a", "forward"),
  record_reload: rec({ kind: "search", url: A, trail: [B], ahead: ["https://example.com/a"] }, A),
  record_new_tab: rec({ kind: "ntp", url: "thomas://new-tab" }, A),
  record_native: rec({ kind: "search", url: A }, "https://example.com/a", undefined, true),
  record_native_still_ends_the_way_ahead: rec({ kind: "web", url: "https://example.com/a", ahead: [B] }, "https://example.com/b", undefined, true),
};

process.stdout.write(JSON.stringify(report));
