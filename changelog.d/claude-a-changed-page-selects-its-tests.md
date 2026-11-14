### Fixed

- **The check before your card now runs the tests that read a changed page.** The check ran the tests that import a changed Python module. A page, script or style sheet has no importers: tests read it by name. A web-size change moved markup out of `index.html` and broke a test that reads that file, yet the card said "no failure this change causes", because the check never ran the test. Tests that name a changed file that isn't Python are now run too, after every real importer. For that change, the check picks the broken test among the 118 it runs, where it used to run 3.
