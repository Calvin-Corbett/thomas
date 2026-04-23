# Security Checklist (practical)

## OS
- Keep Windows updated
- Enable disk encryption (BitLocker)
- Separate user account for running the broker service
- Put vault DB under a restricted directory (ACL)

## Broker
- Run broker as a service (LocalService or dedicated user)
- Lock down pipe permissions if you extend this (Windows named pipe ACLs)
- Keep IPC endpoint local only

## Tools
- Prefer Docker isolation for any tool that handles network or files
- Default deny network (`--network none`) unless needed
- Mount only needed dirs

## Workflow
- Unlock minimal scopes; short TTL; short inactivity timeout
- Use high/critical for anything with financial impact
- Mint confirm tokens only when you are watching the run happen
- Review audit receipts when something feels “off”
