### Fixed

- A message you send while Thomas waits to reload is queued, not refused. You said: "i dotn liek trade offs ... its all about speed". Thomas now waits for the checks that are running before he reloads for new Python, and that wait can last as long as a check, so the Build page used to answer "landed code is reloading" with a red error on a message that only needed to wait. The Build composer now gets "Queued, runs next" and asks again until the run starts. Callers that do not send the flag (Autopilot, Praxis intake) keep the refusal they branch on.
