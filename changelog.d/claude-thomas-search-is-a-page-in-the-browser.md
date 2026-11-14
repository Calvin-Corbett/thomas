### Fixed

- **Searching in the browser now shows results instead of a blank frame.** You
  asked to "make one fix thre browser and have a full nice looking browser ui
  when your on thomas search". Typing a question in the omnibox built a
  `duckduckgo.com` address and loaded it into the tab's iframe; DuckDuckGo
  sends `X-Frame-Options`, so the frame stayed empty and a search went
  nowhere. Search is now a page Thomas serves on his own origin —
  `thomas://search?q=…`, rendered from `/api/search/web` — so no other site
  gets to decide whether your results appear.
- **Back returns to the results you came from.** Opening a result turned the
  tab into a web tab, which lights the Back button, but the step was handed to
  a history holding one cross-origin entry: the button was lit and did
  nothing. The tab that was opened for a result now owes the way back to the
  results, in the browser and in the desktop app, while any page with real
  history of its own still keeps it. If you carried on from that result to an
  address you typed, Back returns to the result first and reaches the results
  on the step after — never skipping a page you were just looking at.
- **Forward now undoes Back, including back to a result.** Forward was lit on
  every web page and handed the step to that same one-entry history, so going
  back was a one-way door: the result you had been reading was gone. Every
  page Back steps off is now a page Forward returns to, the results page can
  go forward to the result you left, and where there is nowhere to go the
  button is dark rather than lit and inert.
- **Searching again keeps the search you came from.** Refining a query from
  the results page replaced the results with no way back to them: Back was
  dark on the one page this browser renders most often, so the earlier
  results were gone. Results pages are now part of a tab's history like any
  other page — Back returns to the query you refined away from, Forward
  returns to the refinement.
- **In the desktop app, Back and Forward go dark at the ends of a page's
  history.** A web tab there is a native view whose history the browser chrome
  cannot read, so both buttons stayed lit on every page and simply did nothing
  once you reached the end. The app now reports after each navigation which way
  that view can move, and the buttons follow it. Reaching the end of that view
  is no longer the end of the tab, either: searching from a page and pressing
  Back to it used to leave both buttons dark with the results gone, because
  the view you landed in was made after them. The pages Thomas opened for you
  are still there on the step after.
- **A tab opened from the + page no longer offers a Back that goes nowhere.**
  Opening a site from the new-tab page, a bookmark or the address bar puts it
  in a frame made for that one address, and a page on another site does not let
  Thomas step through its history — so both buttons lit up and did nothing
  until you had been somewhere else in that tab. In the browser the pages
  Thomas opened for you are the tab's history: the buttons are lit when one of
  them is waiting for you and dark when there is nowhere to go.

### Added

- **A results page with an overview, and honest states when there is nothing
  to show.** Rows carry the site, the headline and the description, with a
  Thomas overview beside them on a wide window and above them on a narrow one;
  links appear as soon as they arrive and never wait on the model. An empty
  search says so, a failed one says why and offers Try again, and an overview
  that cannot be written says that rather than leaving a blank card.
- **A check that opens the page and looks at it.**
  `tests/test_the_search_page_answers_in_every_state.py` drives the shipped
  Search module in a browser at desktop and phone widths and walks the four
  endings a search has — results, nothing found, a provider that failed and
  its Try again, and a slow answer overtaken by a newer query, which must
  never replace it. It leaves screenshots of each in `.thomas/playtest/`.
- **Touching a browser fixture no longer reports the run that passed as a
  failure.** The Search checks are driven by fixture files that are not Python
  tests, and a verification run hands pytest every changed file under `tests/`
  — which used to end the whole run with "found no collectors" before one test
  started, so a green change read as a broken one. Those fixture paths are now
  accepted and contribute no tests of their own, and
  `tests/test_a_browser_harness_does_not_break_a_changed_files_run.py` keeps it
  that way.
- **Checks for the two ways a result can turn hostile.** Every field on the
  page is written by whoever ranks for the query, so
  `tests/test_a_search_result_cannot_smuggle_a_script.py` drives the shipped
  module: markup in a headline or description renders as text, and a link
  whose scheme is not `http`/`https` is refused — `javascript:` survives
  escaping intact and would otherwise run in the page holding the desktop
  bridge.
