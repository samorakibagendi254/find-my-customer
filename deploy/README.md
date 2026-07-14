# Production deployment

The production stack is isolated at `/opt/find-my-customer` and binds only to `127.0.0.1:4314`. The existing Cloudflare Tunnel publishes that loopback origin. It must not be added to Kitabu's shared Compose or Caddy configuration.

## Release contract

1. CI tests the exact commit and publishes `ghcr.io/samorakibagendi254/find-my-customer:<full-sha>`.
2. Resolve the tag to its immutable digest and set `FMC_IMAGE` to the digest, never a mutable tag.
3. Capture the current Compose state, database backup, and complete Cloudflare Tunnel ingress list.
4. Acquire `/opt/find-my-customer/deploy.lock` before mutation.
5. Install `database_url`, `postgres_password`, `admin_password_hash`, and `openai_api_key` as owner-readable secret files; app secrets must be readable by container UID `10001`.
6. Run the one-shot migration, then activate app and worker.
7. Verify loopback readiness, `/api/release`, login denial without a session, authenticated critical flow, and every pre-existing tunnel hostname.
7. Keep the previous digest and tunnel config for rollback.

Secrets are owner-readable files in `shared/secrets/` and are mounted through Compose secrets. The admin password file contains an Argon2id encoded hash, never a plaintext password. Secrets must never enter `.env`, the image, GitHub logs, or shell history.
