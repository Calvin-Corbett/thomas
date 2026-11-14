### Fixed

- Quickstart and setup no longer stop with "Could not save personality preferences" when your preferences file is empty, holds only spaces or comments, or says just null; they treat it as having no settings yet and save your personality into it, while a file that is broken YAML, or holds a list or a single value instead of settings, is still refused and left untouched.
