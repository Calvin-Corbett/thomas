### Changed

- Move the Settings page's local icon fallback and Autonomy, Privacy and Appearance panels into separately loaded assets, keeping the existing controls in their original order.
- Move System Map's main inline stylesheet and page script into loaded assets and the classic Settings template's Advanced Interface and Runtime-through-Cost sections into separately loaded templates.
- Move the classic chat shell's Model Setup modal into a separately loaded template, preserving its place before the remaining shell content.
- Keep every changed web file at 800 lines or fewer; the whole-repo guard still lists only the three unrelated violations.
