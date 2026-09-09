# Docker Deployment

## Quick Start

```bash
docker compose up --build -d
```

Thomas UI/API will be available at:

- `http://127.0.0.1:8899`

## Files

- `Dockerfile`
- `docker-compose.yml`
- `.dockerignore`

## Notes

1. Runtime data is persisted on the host at `./runtime`.
2. `thomas.toml` is mounted read-only into the container.
3. For remote access, configure `server.access_mode` and `server.api_token` in `thomas.toml`.
