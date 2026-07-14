# Find First Customers

An auditable Codex skill that analyzes a startup, defines its ideal customer profile, researches current public pain and timing signals, qualifies potential early customers, and creates a polished standalone report with source-grounded manual outreach.

The repository is the source of truth. The `find-first-customers/` directory is the installable skill; tests and development fixtures remain outside the distributed skill.

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

The skill never sends messages automatically and never treats a public signal as consent or confirmed buying intent.

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
