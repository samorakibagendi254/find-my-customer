# Research and Qualification Framework

Use this framework before collecting or scoring prospects.

## Product brief

Define the product outcome, primary user, economic buyer, urgent job, current alternative, adoption trigger, likely buying motion, geography, and disqualifiers. Do not collect broad lead lists before this brief is specific enough to reject weak matches.

## Signal classes

1. **Explicit demand:** Requests for a tool, recommendation, alternative, integration, or service.
2. **Pain:** First-person descriptions of cost, delay, risk, frustration, or repeated failure.
3. **Workaround:** Spreadsheets, copy-paste, manual coordination, scripts, agencies, or repeated handoffs.
4. **Switching:** Migration, churn, cancellation, missing features, reliability problems, or pricing objections.
5. **Timing:** Hiring, expansion, launch, regulation, workflow change, or technical adoption that makes the product relevant now.

An industry match without a cited pain, demand, or timing signal is speculative and must not appear in the primary shortlist.

## Scoring

Score each dimension from 0 to 5. The bundled validator computes the total.

| Dimension | Weight | Question |
|---|---:|---|
| Pain strength | 25% | How direct, severe, repeated, or expensive is the evidenced problem? |
| Product fit | 25% | How directly does the product solve the evidenced job? |
| Timing | 20% | How recent and actionable is the signal or trigger? |
| Reachability | 15% | Is there a relevant public or official route for a manual approach? |
| Evidence quality | 15% | How specific, reliable, and attributable is the evidence? |

```text
score = pain_strength / 5 * 25
      + product_fit / 5 * 25
      + timing / 5 * 20
      + reachability / 5 * 15
      + evidence_quality / 5 * 15
```

- `80–100`: strong early-customer candidate
- `65–79`: promising; validate quickly
- `50–64`: plausible but missing a material signal
- Below `50`: exclude from the primary shortlist

## Stages

- `high-intent`: publicly requesting a solution or actively switching.
- `problem-aware`: clearly describing the pain or costly workaround.
- `trigger-present`: a current event makes the product relevant.

## Evidence discipline

For every source record:

- Original public URL and title
- Source type
- Visible publication date, or `null` when unavailable
- Date checked
- Concise evidence from that source
- Observed facts
- Explicitly labeled inference

Paraphrase by default and quote minimally. Never qualify a prospect from a search-result snippet alone.

## Outreach discipline

Record the target role, public route, offer, CTA, likely objection, and a short opener. Prefer routing questions and concrete next steps over vague product pitches. Never treat a public route as permission to send automatically.

