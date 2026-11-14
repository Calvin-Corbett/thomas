### Fixed

- Run the approval-landing and saved-green replay tests with explicit repository-local `core.autocrlf=true` and `false`, so Git commands that discard inherited configuration and commands that retain pytest's isolated configuration agree on line-ending conversion.
- Compare landed source bytes against Git's checkout of the landed index while retaining the plain Git clean-status assertion. The production landing already uses Git checkout and is unchanged.
- Reuse a committed starting repository without sample hooks, resolve the Git executable directly, and precreate private green directories in the landing fixtures. The imported approval fixture resolves its cached template without requiring consumers to import another pytest fixture.
- Give approval fixture repositories an explicit host-native line-ending setting; keep the saved-green template's byte-written base at `core.autocrlf=false` before testing either checkout setting.
