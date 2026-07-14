# Find My Customer

An auditable customer-discovery system with two entry points: an installable Codex skill and a private web portal. Both analyze a startup, define its ideal customer profile, research current public pain and timing signals, qualify potential early customers, and create a polished standalone report with source-grounded manual outreach.

The repository is the source of truth. The `find-first-customers/` directory is the self-contained skill. The portal loads that exact workflow, schema, validator, scorer, and renderer so the two experiences cannot silently drift.

## Capabilities

- Primary and adjacent ICP analysis with disqualifiers
- Independent research depth and prospect-focus controls
- Public demand, pain, workaround, switching, and timing research
- Original source links and checked dates for every prospect
- Explicit separation of observed evidence and inference
- Deterministic weighted scoring with strict validation
- Public contact-route guidance without private enrichment
- Personalized openers with concrete manual CTAs
- Responsive, printable, standalone HTML reports
- Atomic cross-platform installation
- Standard-library Python implementation with no runtime dependencies
- Durable portal runs, events, artifacts, and release identity
- OpenAI Responses API research with built-in web search only
- Cloudflare Access JWT verification at the origin

The skill never sends messages automatically and never treats a public signal as consent or confirmed buying intent.

## Web portal

The portal is a small server-rendered FastAPI application with a separate durable worker and PostgreSQL as its only shared service. It deliberately avoids a SPA, Redis, Celery, browser automation, and server-side Codex credentials.

Run the fixture-backed development stack:

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev]"  # Windows
$env:FMC_PROVIDER = "fixture"
.venv/Scripts/python -m uvicorn find_my_customer.web:app --reload
```

In another terminal:

```bash
.venv/Scripts/python -m find_my_customer.worker
```

On macOS or Linux, use `.venv/bin/python` and `export FMC_PROVIDER=fixture` instead. Fixture mode uses the synthetic example and is rejected when `FMC_ENV=production`.

### Run lifecycle

1. The portal validates the public HTTP(S) startup URL without fetching it.
2. PostgreSQL stores an immutable input artifact and queues the run.
3. A leased worker assembles a prompt from the versioned skill documents.
4. The OpenAI Responses API receives only the built-in `web_search` tool.
5. The worker captures the provider source ledger and rejects evidence URLs absent from it.
6. The canonical validator calculates scores and permits at most one bounded schema repair.
7. Normalized JSON and escaped standalone HTML are stored with SHA-256 hashes.
8. Persisted events stream to the browser through resumable SSE.

Every run records the workflow Git SHA, prompt hash, schema version, model, provider response ID, usage metadata, warnings, and artifact hashes.

## Local installation

```bash
node scripts/install.js
```

Install to a custom skills directory:

```bash
node scripts/install.js --skills-dir /path/to/.codex/skills
```

Restart Codex, then use:

```text
Use $find-first-customers to find ten evidence-backed potential first customers for https://example.com and create an auditable HTML report.
```

After the npm package is published, the same installer can run through:

```bash
npx --yes codex-find-first-customers-skill@latest
```

## Development

Requirements:

- Python 3.11 or newer
- Node.js 18 or newer for installer and package checks

Run the complete test suite:

```bash
python -m unittest discover -s tests -v
python -m pytest
```

Validate the synthetic fixture:

```bash
python find-first-customers/scripts/validate_report.py \
  examples/analysis.example.json \
  --normalized outputs/example.normalized.json
```

Generate the example report:

```bash
python find-first-customers/scripts/generate_report.py \
  examples/analysis.example.json \
  outputs/example-report.html
```

The example uses `example.com` URLs and is explicitly synthetic. It tests behavior and presentation; it is not a real prospect list.

## Architecture

- `find-first-customers/SKILL.md` — concise agent workflow and safety contract
- `find-first-customers/references/` — research, source, and report contracts
- `find-first-customers/scripts/report_model.py` — deterministic validation, scoring, warnings, and normalization
- `find-first-customers/scripts/validate_report.py` — validation CLI
- `find-first-customers/scripts/generate_report.py` — safe standalone HTML renderer
- `find-first-customers/assets/report.css` — responsive report presentation
- `tests/` — regression, security, contract, CLI, and installer tests
- `examples/` — synthetic development fixtures
- `src/find_my_customer/` — portal, worker, provider adapter, auth, and durable run state
- `deploy/` — immutable container and isolated Hetzner Compose deployment

## Production topology

Production runs as an isolated Compose project in `/opt/find-my-customer`:

- `app` — FastAPI/Jinja portal on loopback-only `127.0.0.1:4314`
- `worker` — OpenAI research worker with the API key as a Docker secret
- `postgres` — private durable run and artifact store
- `migrate` — one-shot additive schema migration

Cloudflare Tunnel publishes `agentzero.kitabu.ai`; Cloudflare Access protects the entire hostname. The application independently validates the Access JWT audience, issuer, signature, subject, and allowed email. The shared Kitabu Compose and Caddy configuration are not modified.

See `deploy/README.md` for immutable release, verification, backup, and rollback requirements.

## Security boundaries

- User-submitted websites are never fetched by the application server.
- Only OpenAI's built-in web search is available to the model; there is no shell, filesystem, browser, or arbitrary HTTP tool.
- Public source text is treated as hostile prompt-injection content.
- Mutations require same-origin CSRF validation and per-owner quotas.
- Every artifact route rechecks ownership.
- Reports are escaped, CSP-restricted, and sandboxed when embedded.
- Production refuses fixture mode, SQLite, missing Access configuration, or a missing worker API key.

## Scoring

| Dimension | Weight |
|---|---:|
| Pain strength | 25% |
| Product fit | 25% |
| Timing | 20% |
| Public reachability | 15% |
| Evidence quality | 15% |

The validator calculates the total and rejects a supplied score that does not match its dimensions. Primary prospects below 50 are rejected.

## License

MIT
