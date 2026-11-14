### Changed

- **The questions Thomas puts to you and its checklist now load with Chat.** `GET /api/chat/questions`, its answer route and `GET /api/chat/todos` are registered by the Chat plugin instead of the server shell, so a password or protected file card is answered through a route that cannot be turned off. `/api/health` no longer lists `user_questions` and `todos` among its features.
