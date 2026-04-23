# Thomas Browser Module Guardrails

> **THIS FILE IS READ-ONLY POLICY. NO AGENT MAY MODIFY THIS FILE.**
> **NO AGENT MAY MODIFY THE FILES THAT ENFORCE THESE RULES.**
> If you believe a rule needs changing, STOP and ask the user. Do not proceed.

## Overview

Browser is an extension module for browser automation and page capture. It's critical for web interaction but also a source of complexity. Files in this module should be focused, well-tested, and isolated from CLI/server.

Reference the master guardrails: `/Thomas/GUARDRAILS.md`

## Module Metadata

- **Tier**: Extension
- **Depends On**: core, tools, cli (TECH DEBT: cli import should be inverted)
- **Health**: Yellow
- **Architecture Debt**: Circular dependency with cli (p015 imports cli)

## Known Debt Items

From `_architecture.py`:

| File | Issue | Target Size | Notes |
|------|-------|------------|-------|
| `p015_browser_command_registry_scaffold.py` | Imports cli | DO NOT USE | Should be inverted; cli imports browser, not vice versa |
| `p001_browser_command_registry_scaffold.py` | Exceeds 850 lines | Split to ~700 lines | Command registry |
| `p024_browser_error_normalization.py` | Exceeds 845 lines | Split to ~700 lines | Error handling normalization |

## Rule 1: No New Numbered Stub Files

**DO NOT create files named:**
- `p###_*.py` (any numbered pattern)
- `p001_`, `p002_`, etc.

This legacy pattern is banned. Use descriptive names:
- `browser_commands.py` — Command registry
- `browser_errors.py` — Error normalization
- `browser_navigation.py` — Page navigation
- `browser_capture.py` — Screenshot/capture logic

If you see numbered files, plan to rename them with descriptive names.

## Rule 2: Dependency Inversion — Browser Should NOT Import CLI

**Known Problem: p015 imports cli. This is backward.**

Current state:
- cli imports browser (CORRECT)
- browser imports cli (WRONG — circular)

**If you touch the cli import in browser, STOP and ask the user how to break the cycle.**

Options:
1. Extract the CLI-independent logic into a separate file
2. Inject CLI functionality at boot time
3. Move the CLI-specific code into cli/commands/

## Rule 3: Command Registry Must Be Focused

If you're building a command registry (p001, p015, or a new descriptive file):

```python
# GOOD: Focused, discoverable
class BrowserCommandRegistry:
    """Registry of browser-related commands."""

    def register_command(self, name: str, handler: Callable) -> None:
        """Register a command handler."""
        pass

# BAD: Monolithic, unclear scope
class BrowserCommandRegistryScaffold:
    """Everything browser-related."""
    # 850+ lines of mixed concerns
```

## Rule 4: Error Normalization Must Be Specific

Error handling in browser automation is critical. Patterns:

```python
# GOOD: Specific exceptions
class BrowserError(Exception):
    """Base browser error."""
    pass

class NavigationError(BrowserError):
    """Navigation failed."""
    pass

class TimeoutError(BrowserError):
    """Operation timed out."""
    pass

# BAD: Generic error classes
class Error(Exception):
    """Error."""
    pass
```

Every error should:
1. Have a specific name
2. Document when it's raised
3. Be catchable by the agent loop

## Rule 5: Exception Handling

All exception handlers must be specific. Follow the master guardrails Rule 3.

Browser-specific patterns:
- `except playwright.Error:` — Playwright library errors
- `except asyncio.TimeoutError:` — Operation timeouts
- `except FileNotFoundError:` — File access errors (screenshot save)
- `except ConnectionError:` — Browser process connection

**No bare `except:` or swallowing errors without logging:**

```python
# WRONG:
try:
    page = await browser.new_page()
except:
    return None  # Silent failure!

# RIGHT:
try:
    page = await browser.new_page()
except asyncio.TimeoutError:
    logger.warning("Browser page creation timed out")
    raise NavigationError("Timeout creating page")
except playwright.Error as e:
    logger.exception("Browser error creating page")
    raise NavigationError(f"Browser error: {e}")
```

## Rule 6: Module-Specific Import Rules

**browser MAY import:**
- core
- tools
- cli (but this is a tech debt item — dependency inversion needed)
- Standard library and third-party (playwright, selenium, etc.)

**browser MAY NOT import:**
- server
- agent
- other extension modules (channels, integrations, etc.)
- domain-specific modules

## Rule 7: Browser Lifecycle Management

Browser automation is resource-intensive. Always implement proper lifecycle:

```python
class BrowserManager:
    async def __aenter__(self):
        """Start browser context."""
        self.browser = await playwright.chromium.launch()
        return self.browser

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Clean up browser context."""
        if self.browser:
            await self.browser.close()

# Usage:
async with BrowserManager() as browser:
    page = await browser.new_page()
    # Use page
    # Cleanup happens automatically
```

## Rule 8: Avoid Long-Running Browser Instances

Browser processes should be short-lived. Guidelines:
- Create browser instance for each command
- Close browser instance after command completes
- Cache browser profiles/state if needed, not the instance itself
- Implement timeouts for all browser operations

## Verification Checklist

Before committing any browser/ changes:

- [ ] Run `python -c "import py_compile; py_compile.compile('thomas/browser/<file>.py', doraise=True)"`
- [ ] Run `python -m pytest tests/test_architecture.py -x --tb=short -q`
- [ ] Verify no new files exceed 800 lines
- [ ] Check: did you extend p001, p024, or p015? Plan a rename/split first
- [ ] No new numbered stub files
- [ ] All exception handlers are specific (no bare except)
- [ ] Browser instances are properly cleaned up (async context managers)
- [ ] All browser operations have timeouts
- [ ] Run `python -m thomas serve --port 0` and verify boot

## Changelog

Always update `CHANGELOG.md` with browser/ changes. Format:

```markdown
### [Added] or [Changed] or [Fixed]
- browser: <brief description of what changed and why>
```

Example:
```markdown
### Fixed
- browser: Screenshot capture now properly waits for page load before capturing
- browser: Navigation errors now distinguished from timeout errors

### Changed
- browser: Upgraded to Playwright 1.45 for better mobile support
```
