### Changed

- **The git analysis and project stats tools now live in their own file.** `thomas/tools/engineering.py` was over the size limit; `eng.git_analysis` and `eng.project_stats` moved to `thomas/tools/engineering_commands.py` with the same names, arguments and results, so nothing you use changes.
