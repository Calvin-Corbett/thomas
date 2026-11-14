### Fixed

- Registered the settings catalogue, controls and provider with the existing plugin manifests, including their explicit import boundaries, so the final plugin ownership and fencing checks cover the new integration.

- Express approval cards call the existing window control in-process after the verified press, using `open --until-off` or `close`, without launching an extra command process.
- Loading settings controls no longer imports Windows history at startup. The history reader is imported only when the settings index requests Express status.
- The settings row installs its provider synchronously when the host fires its ready hook, so requests can find the active settings controls.
- Studio's built-in timeline renderer mounts the existing Comfy controls too, so they remain available when the external audio editor cannot load.
- Added regression coverage for the ready hook, startup import isolation and both Express commands, including refusal before sign-in and a check that no extra process is launched.
- Approval cards show the requested value alongside the current value before you press. Cancelled Windows sign-ins are audited without consuming the card or launching Express. The route test checks the real audit events and the existing boolean Express runner contract.
