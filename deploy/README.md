# Production deployment

The production stack is isolated at `/opt/find-my-customer` and binds only to `127.0.0.1:4314`. The existing Cloudflare Tunnel publishes that loopback origin. It must not be added to Kitabu's shared Compose or Caddy configuration.

## Release contract

1. CI tests the exact commit and publishes `ghcr.io/samorakibagendi254/find-my-customer:<full-sha>`.
2. Resolve the tag to its immutable digest and set `FMC_IMAGE` to the digest, never a mutable tag.
3. Capture the current Compose state, database backup, and complete Cloudflare Tunnel ingress list.
4. Acquire `/opt/find-my-customer/deploy.lock` before mutation.
5. Run the one-shot migration, then activate app and worker.
6. Verify loopback readiness, `/api/release`, Access denial without identity, authenticated critical flow, and every pre-existing tunnel hostname.
7. Keep the previous digest and tunnel config for rollback.

Secrets are owner-readable files in `current/secrets/` and are mounted through Compose secrets. They must never enter `.env`, the image, GitHub logs, or shell history.
