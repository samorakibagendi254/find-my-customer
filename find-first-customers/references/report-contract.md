# Report Contract

Create a JSON analysis, validate it, and render the normalized result. Do not hand-author the final HTML.

## Commands

Run from the installed skill directory:

```bash
python scripts/validate_report.py analysis.json --normalized normalized.json
python scripts/generate_report.py normalized.json outputs/first-customers.html
```

The validator uses only the Python standard library. It calculates scores, rejects incomplete primary prospects, detects duplicate identities and source links, enforces mode limits, and emits freshness or reachability warnings.

## Contract

Use [report.schema.json](report.schema.json) as the machine-readable structure. Important rules:

- Set `schema_version` to `1`.
- Set one depth in `mode` and one independent prospect emphasis in `focus`.
- Use ISO `YYYY-MM-DD` dates.
- Represent unknown publication dates as `null`.
- Keep `observed` and `inferred` separate.
- Provide one or more original public sources per prospect.
- Score every dimension from 0 to 5.
- Omit `score` or provide the exact computed score; normalization always writes the computed value.
- Keep primary prospects at score 50 or above.
- Use only enumerated public contact-route types.
- Keep the opener under 90 words.
- Reference valid prospect IDs in pattern evidence.

The generated report is a standalone, responsive HTML file. It escapes all research text and permits only HTTP or HTTPS links.
