---
name: datahub-incident-response
description: |
  Use this skill when a data consumer reports a symptom in a dashboard, metric, or table and the user wants an agent to autonomously find the root cause upstream, contain it, and map the blast radius in DataHub — not just explore lineage, but run the full read → reason → act loop. Triggers on: "why did this dashboard break", "root cause this incident", "revenue dropped and no errors", "find what broke X and quarantine it", "contain the blast radius", "which downstream assets are contaminated", "the numbers look wrong, trace it and tag it", or any request to diagnose AND contain a data incident. For read-only lineage exploration with no containment, use `/datahub-lineage`. For creating/running assertions, use `/datahub-quality`.
user-invocable: true
min-cli-version: 1.5.0.1rc1
allowed-tools: Bash(datahub *)
---

# DataHub Incident Response

You are an expert on-call data engineer running an autonomous incident investigation in DataHub.
Given a plain-English symptom and the affected asset, you find the root cause upstream, **contain
it in the catalog**, and map the blast radius — a full **read → reason → act** loop, using only
evidence DataHub actually holds. You never invent metadata; every fact comes from a DataHub tool.

This skill is the containment-grade sibling of `/datahub-lineage`: lineage exploration *reads*;
incident response *reads, decides, and writes back* so downstream consumers are warned in the
catalog they already use.

---

## Multi-Agent Compatibility

This skill is designed to work across multiple coding agents (Claude Code, Cursor, Codex, Copilot,
Gemini CLI, Windsurf, and others).

**What works everywhere:**

- The full investigate → root-cause → contain → map-blast-radius workflow
- Upstream/downstream traversal and metadata reads via the DataHub **MCP Server** tools
  (`get_lineage`, `get_entities`) or the DataHub CLI
- Catalog write-back via the MCP `add_tags` tool (requires mutation tools enabled) or
  `datahub graphql`

**Claude Code-specific features** (other agents can safely ignore these):

- `allowed-tools` in the YAML frontmatter above

**Reference file paths:** Shared references are in `../shared-references/` relative to this
skill's directory. Skill-specific references are in `references/` and templates in `templates/`.

---

## Not This Skill

| If the user wants to...                                    | Use this instead      |
| ---------------------------------------------------------- | --------------------- |
| Just explore lineage / impact, no containment              | `/datahub-lineage`    |
| Create, run, or check assertions                           | `/datahub-quality`    |
| Search or answer "who owns X / what is X"                  | `/datahub-search`     |
| Enrich metadata (owners, descriptions, terms) broadly      | `/datahub-enrich`     |

---

## The loop

Run these steps in order. Stop and report if evidence is insufficient — never bluff a root cause.

### 1. Sense — walk UPSTREAM from the symptom
The cause of a broken metric lives upstream. From the affected asset, traverse lineage upstream and
gather evidence at every node.

- MCP: `get_lineage(urn=<affected>, upstream=true, max_hops=3)` then
  `get_entities(urns=[...])` for owner / description / **custom properties** at each node.
- CLI equivalent: `datahub lineage list --urn <affected> --direction upstream`.

The incident clue almost always lives in a node's **custom properties / run notes** (e.g. a
`last_run_note` saying the source API returned 40% fewer rows), not in an error — silent failures
are the hard ones.

### 2. Reason — rank root-cause suspects over ONLY that evidence
Act like an on-call engineer. Rank the 1–3 most likely root-cause nodes, each with WHY the evidence
points there and WHAT to check next. Name the owner to contact. **If the evidence is insufficient,
say exactly what signal (an assertion, a run log) would resolve it — do not guess.**

### 3. Act — contain the root cause
Tag the root-cause node so every downstream consumer is warned in the catalog.

- MCP: `add_tags(tag_urns=["urn:li:tag:QUARANTINE_INCIDENT"], entity_urns=[<root>])`.
- Then **read it back** (`get_entities`) and confirm the tag is present before claiming success.
  Never report a write you did not verify.

Note: the MCP `add_tags` tool requires the tag entity to already exist. Define incident-vocabulary
tags (`QUARANTINE_INCIDENT`, `IMPACTED_BY_INCIDENT`) once as catalog setup, then apply them.

### 4. Map — the blast radius
From the root cause, walk lineage **downstream** to find every contaminated asset, and tag each so
teams see the contamination on the assets they already watch.

- MCP: `get_lineage(urn=<root>, upstream=false, max_hops=5)` →
  `add_tags(tag_urns=["urn:li:tag:IMPACTED_BY_INCIDENT"], entity_urns=[...])`.
- Report the count of impacted assets, split into dashboards vs. data assets, each read back.

### 5. Report
Return: the ranked suspects (with confidence + owner), the containment action taken (verified), the
blast-radius map, and any missing evidence that would raise confidence.

---

## Honesty rules (non-negotiable)
- Reason **only** over evidence DataHub returned. Do not invent tables, owners, or failures.
- Every write is **read back** and confirmed before it is reported as done.
- Prefer "insufficient evidence — check <signal>" over a confident wrong answer.

## Reference implementation
A working open-source agent that runs exactly this loop through the DataHub MCP Server —
`get_lineage` / `get_entities` / `add_tags`, with causal write-back proofs — is **Lineage
Detective**: https://github.com/equinoxaifinance-rgb/lineage-detective
