---
name: find-first-customers
description: Find and qualify evidence-backed potential first customers, early adopters, design partners, or beta users for a startup from recent public pain, demand, switching, workaround, and business-timing signals. Use when Codex needs to analyze a startup URL or product idea, define an ideal customer profile, research public sources, score prospect fit and timing, draft source-grounded manual outreach, or create an auditable HTML prospect report without sending messages or using private contact enrichment.
---

# Find First Customers

Turn a startup URL, repository, or product description into a small, auditable shortlist of potential early customers. Treat every prospect as a hypothesis derived from public evidence, never as a confirmed buyer.

Read [references/research-framework.md](references/research-framework.md) before planning searches or scoring prospects. Read [references/source-playbooks.md](references/source-playbooks.md) when selecting sources and queries. Read [references/report-contract.md](references/report-contract.md) before writing the report JSON.

## Workflow

### 1. Define the product and ICP

- Inspect the supplied website, repository, or product description.
- Record the product outcome, user, economic buyer, urgent job, current alternative, adoption trigger, buying motion, geography, and constraints.
- Define one primary ICP, one adjacent ICP, and explicit disqualifiers.
- Label assumptions. Ask one concise question only when ambiguity would materially change the search.

### 2. Plan the research

- Select a depth: `quick`, `standard`, or `deep`. Use `standard` by default.
- Select a focus: `general`, `design-partners`, `b2b`, or `community`. Use `general` by default.
- Build query groups for explicit demand, pain, workaround, switching, and timing.
- Use multiple source types. Prefer original public pages over search snippets or aggregators.
- Set a concrete search scope and research date before collecting prospects.

### 3. Research public signals

- Browse current public sources and open every source used for qualification.
- Record the original URL, title, source type, visible publication date, checked date, and the exact signal.
- Separate observed evidence from inference. Never write an inference as an observed fact.
- Use only intentionally public professional or business information.
- Do not bypass login walls, paywalls, access controls, rate limits, or robots restrictions.
- Do not use data brokers, leaked datasets, private groups, personal-email discovery, phone enrichment, or sensitive personal information.

### 4. Qualify and deduplicate

- Score pain strength, product fit, timing, public reachability, and evidence quality from 0 to 5.
- Let the bundled validator calculate the weighted score. Do not invent or manually adjust the total.
- Exclude scores below 50 from the primary shortlist.
- Remove duplicate people, companies, projects, and repeated evidence.
- Require at least one meaningful public pain, demand, or timing source for every listed prospect.
- Mark old signals visibly; freshness affects timing but does not erase relevant evidence.

### 5. Prepare manual outreach

- Identify the most relevant buyer role or function.
- Recommend a concrete official or public route already connected to the evidence. Say `none-found` when no route is visible.
- Translate the product into the prospect's language.
- Write an opener under 90 words with one specific, low-friction CTA that can be accepted, declined, or forwarded.
- Never send, submit, connect, follow, comment, enrich, or create CRM records unless the user separately requests and authorizes that action.

### 6. Validate and generate the report

1. Create JSON that follows [references/report.schema.json](references/report.schema.json).
2. Run `python scripts/validate_report.py <analysis.json> --normalized <normalized.json>`.
3. Resolve every validation error. Review freshness and reachability warnings.
4. Run `python scripts/generate_report.py <normalized.json> <report.html>`.
5. Save final artifacts in the workspace `outputs/` directory.
6. Verify ICP fields, prospect scores, source links, dates, observed evidence, inferences, public routes, CTAs, patterns, plan, and limitations.
7. Return a clickable absolute link to the HTML report. Cite public sources in the chat summary whenever web research was performed.

## Depth and focus

- `quick`: up to five strong prospects.
- `standard`: up to ten prospects across several source types.
- `deep`: up to twenty prospects with repeated-pattern analysis.
- `general`: balance likely early adopters across relevant public signals.
- `design-partners`: prioritize feedback readiness over immediate purchasing intent.
- `b2b`: prioritize companies, business triggers, and relevant buyer functions.
- `community`: prioritize explicit requests and public discussion signals.

## Quality bar

- Prefer five strong, reachable prospects over twenty generic matches.
- Link each material claim to original evidence.
- Make uncertainty, missing dates, stale signals, and absent contact routes visible.
- Keep observed facts distinct from interpretation.
- Make the next manual step operationally clear.
- Preserve user privacy and source terms.
- Never claim interest, consent, intent to buy, or guaranteed conversion.
