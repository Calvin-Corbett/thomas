# Baseline: Clean Checkout Evidence

- Date: 2026-03-04
- Clean checkout path: `C:\Users\corbe\tmp\thomas_baseline_clean_wt_20260304`
- Purpose: capture pre-remediation behavior on a clean checkout before applying fixes.

## Summary

- `pytest --collect-only -q` failed during bootstrap with missing plugin module
  `tests.conftest_factories`.
- `pytest -q` failed at the same bootstrap stage; no tests executed.
- `python scripts/check_monolith_guard.py` failed on oversized unbaselined
  `thomas/cli/repl.py`.
- `python scripts/check_release_hygiene.py` failed due missing current-version
  changelog section and emitted import-time `THOMAS_SECRET_KEY` warning.
- `python scripts/security_audit.py` exited OK but reported warning count `1`
  (same import-time warning source).

## `pytest --collect-only -q`

- Exit code: 1
- Duration: 0.63s
- Output (tail):
```text
Traceback (most recent call last):
  File "C:\Users\corbe\AppData\Local\Programs\Python\Python312\Lib\site-packages\_pytest\config\__init__.py", line 879, in import_plugin
    __import__(importspec)
ModuleNotFoundError: No module named 'tests.conftest_factories'
System.Management.Automation.RemoteException
The above exception was the direct cause of the following exception:
System.Management.Automation.RemoteException
Traceback (most recent call last):
  File "<frozen runpy>", line 198, in _run_module_as_main
  File "<frozen runpy>", line 88, in _run_code
  File "C:\Users\corbe\AppData\Local\Programs\Python\Python312\Scripts\pytest.exe\__main__.py", line 5, in <module>
  File "C:\Users\corbe\AppData\Local\Programs\Python\Python312\Lib\site-packages\_pytest\config\__init__.py", line 223, in console_main
    code = main()
           ^^^^^^
  File "C:\Users\corbe\AppData\Local\Programs\Python\Python312\Lib\site-packages\_pytest\config\__init__.py", line 193, in main
    config = _prepareconfig(new_args, plugins)
             ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "C:\Users\corbe\AppData\Local\Programs\Python\Python312\Lib\site-packages\_pytest\config\__init__.py", line 361, in _prepareconfig
    config: Config = pluginmanager.hook.pytest_cmdline_parse(
                     ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "C:\Users\corbe\AppData\Local\Programs\Python\Python312\Lib\site-packages\pluggy\_hooks.py", line 512, in __call__
    return self._hookexec(self.name, self._hookimpls.copy(), kwargs, firstresult)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "C:\Users\corbe\AppData\Local\Programs\Python\Python312\Lib\site-packages\pluggy\_manager.py", line 120, in _hookexec
    return self._inner_hookexec(hook_name, methods, kwargs, firstresult)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "C:\Users\corbe\AppData\Local\Programs\Python\Python312\Lib\site-packages\pluggy\_callers.py", line 167, in _multicall
    raise exception
  File "C:\Users\corbe\AppData\Local\Programs\Python\Python312\Lib\site-packages\pluggy\_callers.py", line 139, in _multicall
    teardown.throw(exception)
  File "C:\Users\corbe\AppData\Local\Programs\Python\Python312\Lib\site-packages\_pytest\helpconfig.py", line 124, in pytest_cmdline_parse
    config = yield
             ^^^^^
  File "C:\Users\corbe\AppData\Local\Programs\Python\Python312\Lib\site-packages\pluggy\_callers.py", line 121, in _multicall
    res = hook_impl.function(*args)
          ^^^^^^^^^^^^^^^^^^^^^^^^^
  File "C:\Users\corbe\AppData\Local\Programs\Python\Python312\Lib\site-packages\_pytest\config\__init__.py", line 1186, in pytest_cmdline_parse
    self.parse(args)
  File "C:\Users\corbe\AppData\Local\Programs\Python\Python312\Lib\site-packages\_pytest\config\__init__.py", line 1556, in parse
    self.hook.pytest_load_initial_conftests(
  File "C:\Users\corbe\AppData\Local\Programs\Python\Python312\Lib\site-packages\pluggy\_hooks.py", line 512, in __call__
    return self._hookexec(self.name, self._hookimpls.copy(), kwargs, firstresult)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "C:\Users\corbe\AppData\Local\Programs\Python\Python312\Lib\site-packages\pluggy\_manager.py", line 120, in _hookexec
    return self._inner_hookexec(hook_name, methods, kwargs, firstresult)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "C:\Users\corbe\AppData\Local\Programs\Python\Python312\Lib\site-packages\pluggy\_callers.py", line 167, in _multicall
    raise exception
  File "C:\Users\corbe\AppData\Local\Programs\Python\Python312\Lib\site-packages\pluggy\_callers.py", line 139, in _multicall
    teardown.throw(exception)
  File "C:\Users\corbe\AppData\Local\Programs\Python\Python312\Lib\site-packages\_pytest\warnings.py", line 128, in pytest_load_initial_conftests
    return (yield)
            ^^^^^
  File "C:\Users\corbe\AppData\Local\Programs\Python\Python312\Lib\site-packages\pluggy\_callers.py", line 139, in _multicall
    teardown.throw(exception)
  File "C:\Users\corbe\AppData\Local\Programs\Python\Python312\Lib\site-packages\_pytest\capture.py", line 173, in pytest_load_initial_conftests
    yield
  File "C:\Users\corbe\AppData\Local\Programs\Python\Python312\Lib\site-packages\pluggy\_callers.py", line 121, in _multicall
    res = hook_impl.function(*args)
          ^^^^^^^^^^^^^^^^^^^^^^^^^
  File "C:\Users\corbe\AppData\Local\Programs\Python\Python312\Lib\site-packages\_pytest\config\__init__.py", line 1270, in pytest_load_initial_conftests
    self.pluginmanager._set_initial_conftests(
  File "C:\Users\corbe\AppData\Local\Programs\Python\Python312\Lib\site-packages\_pytest\config\__init__.py", line 602, in _set_initial_conftests
    self._try_load_conftest(
  File "C:\Users\corbe\AppData\Local\Programs\Python\Python312\Lib\site-packages\_pytest\config\__init__.py", line 640, in _try_load_conftest
    self._loadconftestmodules(
  File "C:\Users\corbe\AppData\Local\Programs\Python\Python312\Lib\site-packages\_pytest\config\__init__.py", line 680, in _loadconftestmodules
    mod = self._importconftest(
          ^^^^^^^^^^^^^^^^^^^^^
  File "C:\Users\corbe\AppData\Local\Programs\Python\Python312\Lib\site-packages\_pytest\config\__init__.py", line 756, in _importconftest
    self.consider_conftest(mod, registration_name=conftestpath_plugin_name)
  File "C:\Users\corbe\AppData\Local\Programs\Python\Python312\Lib\site-packages\_pytest\config\__init__.py", line 837, in consider_conftest
    self.register(conftestmodule, name=registration_name)
  File "C:\Users\corbe\AppData\Local\Programs\Python\Python312\Lib\site-packages\_pytest\config\__init__.py", line 533, in register
    self.consider_module(plugin)
  File "C:\Users\corbe\AppData\Local\Programs\Python\Python312\Lib\site-packages\_pytest\config\__init__.py", line 845, in consider_module
    self._import_plugin_specs(getattr(mod, "pytest_plugins", []))
  File "C:\Users\corbe\AppData\Local\Programs\Python\Python312\Lib\site-packages\_pytest\config\__init__.py", line 852, in _import_plugin_specs
    self.import_plugin(import_spec)
  File "C:\Users\corbe\AppData\Local\Programs\Python\Python312\Lib\site-packages\_pytest\config\__init__.py", line 881, in import_plugin
    raise ImportError(
  File "C:\Users\corbe\AppData\Local\Programs\Python\Python312\Lib\site-packages\_pytest\config\__init__.py", line 879, in import_plugin
    __import__(importspec)
ImportError: Error importing plugin "tests.conftest_factories": No module named 'tests.conftest_factories'
```

## `pytest -q`

- Exit code: 1
- Duration: 0.62s
- Output (tail):
```text
Traceback (most recent call last):
  File "C:\Users\corbe\AppData\Local\Programs\Python\Python312\Lib\site-packages\_pytest\config\__init__.py", line 879, in import_plugin
    __import__(importspec)
ModuleNotFoundError: No module named 'tests.conftest_factories'
System.Management.Automation.RemoteException
The above exception was the direct cause of the following exception:
System.Management.Automation.RemoteException
Traceback (most recent call last):
  File "<frozen runpy>", line 198, in _run_module_as_main
  File "<frozen runpy>", line 88, in _run_code
  File "C:\Users\corbe\AppData\Local\Programs\Python\Python312\Scripts\pytest.exe\__main__.py", line 5, in <module>
  File "C:\Users\corbe\AppData\Local\Programs\Python\Python312\Lib\site-packages\_pytest\config\__init__.py", line 223, in console_main
    code = main()
           ^^^^^^
  File "C:\Users\corbe\AppData\Local\Programs\Python\Python312\Lib\site-packages\_pytest\config\__init__.py", line 193, in main
    config = _prepareconfig(new_args, plugins)
             ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "C:\Users\corbe\AppData\Local\Programs\Python\Python312\Lib\site-packages\_pytest\config\__init__.py", line 361, in _prepareconfig
    config: Config = pluginmanager.hook.pytest_cmdline_parse(
                     ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "C:\Users\corbe\AppData\Local\Programs\Python\Python312\Lib\site-packages\pluggy\_hooks.py", line 512, in __call__
    return self._hookexec(self.name, self._hookimpls.copy(), kwargs, firstresult)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "C:\Users\corbe\AppData\Local\Programs\Python\Python312\Lib\site-packages\pluggy\_manager.py", line 120, in _hookexec
    return self._inner_hookexec(hook_name, methods, kwargs, firstresult)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "C:\Users\corbe\AppData\Local\Programs\Python\Python312\Lib\site-packages\pluggy\_callers.py", line 167, in _multicall
    raise exception
  File "C:\Users\corbe\AppData\Local\Programs\Python\Python312\Lib\site-packages\pluggy\_callers.py", line 139, in _multicall
    teardown.throw(exception)
  File "C:\Users\corbe\AppData\Local\Programs\Python\Python312\Lib\site-packages\_pytest\helpconfig.py", line 124, in pytest_cmdline_parse
    config = yield
             ^^^^^
  File "C:\Users\corbe\AppData\Local\Programs\Python\Python312\Lib\site-packages\pluggy\_callers.py", line 121, in _multicall
    res = hook_impl.function(*args)
          ^^^^^^^^^^^^^^^^^^^^^^^^^
  File "C:\Users\corbe\AppData\Local\Programs\Python\Python312\Lib\site-packages\_pytest\config\__init__.py", line 1186, in pytest_cmdline_parse
    self.parse(args)
  File "C:\Users\corbe\AppData\Local\Programs\Python\Python312\Lib\site-packages\_pytest\config\__init__.py", line 1556, in parse
    self.hook.pytest_load_initial_conftests(
  File "C:\Users\corbe\AppData\Local\Programs\Python\Python312\Lib\site-packages\pluggy\_hooks.py", line 512, in __call__
    return self._hookexec(self.name, self._hookimpls.copy(), kwargs, firstresult)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "C:\Users\corbe\AppData\Local\Programs\Python\Python312\Lib\site-packages\pluggy\_manager.py", line 120, in _hookexec
    return self._inner_hookexec(hook_name, methods, kwargs, firstresult)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "C:\Users\corbe\AppData\Local\Programs\Python\Python312\Lib\site-packages\pluggy\_callers.py", line 167, in _multicall
    raise exception
  File "C:\Users\corbe\AppData\Local\Programs\Python\Python312\Lib\site-packages\pluggy\_callers.py", line 139, in _multicall
    teardown.throw(exception)
  File "C:\Users\corbe\AppData\Local\Programs\Python\Python312\Lib\site-packages\_pytest\warnings.py", line 128, in pytest_load_initial_conftests
    return (yield)
            ^^^^^
  File "C:\Users\corbe\AppData\Local\Programs\Python\Python312\Lib\site-packages\pluggy\_callers.py", line 139, in _multicall
    teardown.throw(exception)
  File "C:\Users\corbe\AppData\Local\Programs\Python\Python312\Lib\site-packages\_pytest\capture.py", line 173, in pytest_load_initial_conftests
    yield
  File "C:\Users\corbe\AppData\Local\Programs\Python\Python312\Lib\site-packages\pluggy\_callers.py", line 121, in _multicall
    res = hook_impl.function(*args)
          ^^^^^^^^^^^^^^^^^^^^^^^^^
  File "C:\Users\corbe\AppData\Local\Programs\Python\Python312\Lib\site-packages\_pytest\config\__init__.py", line 1270, in pytest_load_initial_conftests
    self.pluginmanager._set_initial_conftests(
  File "C:\Users\corbe\AppData\Local\Programs\Python\Python312\Lib\site-packages\_pytest\config\__init__.py", line 602, in _set_initial_conftests
    self._try_load_conftest(
  File "C:\Users\corbe\AppData\Local\Programs\Python\Python312\Lib\site-packages\_pytest\config\__init__.py", line 640, in _try_load_conftest
    self._loadconftestmodules(
  File "C:\Users\corbe\AppData\Local\Programs\Python\Python312\Lib\site-packages\_pytest\config\__init__.py", line 680, in _loadconftestmodules
    mod = self._importconftest(
          ^^^^^^^^^^^^^^^^^^^^^
  File "C:\Users\corbe\AppData\Local\Programs\Python\Python312\Lib\site-packages\_pytest\config\__init__.py", line 756, in _importconftest
    self.consider_conftest(mod, registration_name=conftestpath_plugin_name)
  File "C:\Users\corbe\AppData\Local\Programs\Python\Python312\Lib\site-packages\_pytest\config\__init__.py", line 837, in consider_conftest
    self.register(conftestmodule, name=registration_name)
  File "C:\Users\corbe\AppData\Local\Programs\Python\Python312\Lib\site-packages\_pytest\config\__init__.py", line 533, in register
    self.consider_module(plugin)
  File "C:\Users\corbe\AppData\Local\Programs\Python\Python312\Lib\site-packages\_pytest\config\__init__.py", line 845, in consider_module
    self._import_plugin_specs(getattr(mod, "pytest_plugins", []))
  File "C:\Users\corbe\AppData\Local\Programs\Python\Python312\Lib\site-packages\_pytest\config\__init__.py", line 852, in _import_plugin_specs
    self.import_plugin(import_spec)
  File "C:\Users\corbe\AppData\Local\Programs\Python\Python312\Lib\site-packages\_pytest\config\__init__.py", line 881, in import_plugin
    raise ImportError(
  File "C:\Users\corbe\AppData\Local\Programs\Python\Python312\Lib\site-packages\_pytest\config\__init__.py", line 879, in import_plugin
    __import__(importspec)
ImportError: Error importing plugin "tests.conftest_factories": No module named 'tests.conftest_factories'
```

## `python scripts/check_monolith_guard.py`

- Exit code: 1
- Duration: 0.76s
- Output (tail):
```text
Monolith guard FAILED: 1 violation(s). Split modules or update baseline intentionally.
- thomas/cli/repl.py: 1299 lines (hard 1200) -> file exceeds hard limit and is not baselined
```

## `python scripts/check_release_hygiene.py`

- Exit code: 1
- Duration: 3.81s
- Output (tail):
```text
C:\Users\corbe\Thomas\thomas\api_gateway\core.py:180: UserWarning: THOMAS_SECRET_KEY not set � using random key. Set this env var for production.
  self.auth_middleware = AuthMiddleware()
release hygiene: FAIL
- CHANGELOG.md is missing a section header for version [0.14.31]
- WARN: onboarding outcomes gate warning: insufficient onboarding telemetry sample for KPI threshold checks: events=0, required>=20
- WARN: security audit warnings present: 1
```

## `python scripts/security_audit.py`

- Exit code: 0
- Duration: 3.71s
- Output (tail):
```text
C:\Users\corbe\Thomas\thomas\api_gateway\core.py:180: UserWarning: THOMAS_SECRET_KEY not set � using random key. Set this env var for production.
  self.auth_middleware = AuthMiddleware()
Repo root: C:\Users\corbe\tmp\thomas_baseline_clean_wt_20260304
Result: OK
Checks: 6
Failing checks: none
Error count: 0
Warning count: 1
```

