### Fixed

- **A restart that is waiting can be cancelled.** A restart you ask for waits for every running check, which can take an hour, and meanwhile new tasks are held; there was no way to say "not now". Thomas now answers `POST /api/server/restart/cancel`: new tasks start again, held work resumes, and nothing that was running is stopped. The **Cancel restart** button that calls it arrives with the one-line restart notice, which another session is still editing. You said: "this restasrt wanring is ugly and i dont think it svene working im tryna use thoamd and he is liek frozen".
