### Fixed
- **Configuration and database imports work again.** Since 27 February 2026, configuration management stopped importing because its annotations used the built-in `callable` as a type, and database commands stopped importing because their password-hiding helper was missing from `database_safety.py`. Both modules now import, and your four database tools can be built again.
- **Chat configuration tools still need a separate fix.** Your `config_mgmt.*` calls still answer with an error because `core_manager.py` imports names that `playbook.py` does not define.
