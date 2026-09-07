# PLAN for BROWSER-SEARCH-RESULTS

- Owner: unassigned
- Status: up_for_grabs
- Updated At: 2026-08-27T23:07:00+00:00
- Scope: thomas/server/routes,thomas/server/web/js,docs/DESKTOP.md

## Summary

Owner requirement 2026-08-27. Omnibox search must feel like a NORMAL search engine - real ranked results with titles, urls and snippets, PLUS a Thomas AI answer above them, the way Google shows an AI overview. What happens behind the scenes matters less as long as it feels normal, so a page that only lists the sources Thomas happened to cite is NOT acceptable. Verified groundwork. Thomas already has a registry tool web.search (DuckDuckGo backed) called via registry.execute with query and count, see thomas/marketplace/specialists/web_research.py collect_explicit_web_evidence. The chrome needs an HTTP endpoint to reach it, for example GET /api/browser/search returning title, url and snippet rows as JSON, after which browser_shell renders its own results page on our own origin so there is no X-Frame-Options problem, with the AI answer card above it from the existing /api/v2/chat pipeline. BLOCKER. New routes register in thomas/server/app_routes_init.py which is 1471 lines against a 1200 hard limit and unbaselined, so ANY commit touching it fails monolith_guard and no new endpoint can be added at all. Two ways forward. Decompose app_routes_init.py, which also unblocks every other future endpoint and is the right fix. Or host the handler inside an already registered module such as thomas/server/routes/observability.py at 260 lines whose register_observability_routes is called from app_routes_init line 1004, which needs no registration change but puts browser search in an unrelated module and should be treated as temporary

## Approach

- Document the intended implementation steps here.
