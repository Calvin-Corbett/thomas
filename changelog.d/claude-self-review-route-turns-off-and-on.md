### Changed

- **Thomas's review of its own recent work can now be turned off and on from the Plugins page.** Turning it off removes `GET /api/self-review`, cancels a review that is still being written, and forgets the reports held in memory. Nothing in Thomas asks for this route.
- **Asking for Thomas's self review now needs the same access as the other routes that cost a model call.** `GET /api/self-review` starts a request to the model, and until now a program on another computer with no access key could start one. It is refused with 401 now, and programs on this computer are answered as before.
