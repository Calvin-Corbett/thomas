### Fixed

- **A plugin you turn on now answers only once it has finished starting.** It used to take requests while its startup work was still running, so it could read as on and answer with an error. It now reads as loading until it is ready, turning it off during that ends the wait, and one that fails while starting never begins answering.
- **Your plugin choices now save in the order you pressed them.** Two presses close together could save either way round, so a plugin could read one way now and come back the other way at the next restart.
- **One plugin's broken routes now stay that plugin's.** A plugin whose folder had vanished made turning a different plugin off answer with an error, while the broken one read as fine, and a plugin that depended on the one you pressed could fail it. The broken one now reads as failed and says why, and the rest carry on. A plugin can also no longer quietly take over an address Thomas already answers: it fails and says so.
- **Turning plugins off in any order now leaves nothing behind.** Two plugins that had written the same setting could leave the older one's value in place with both of them off.
- **A plugin's background work can no longer leave it stuck by turning itself off.** It used to wait for itself and stay stopping for good. That press is now refused with a reason.
