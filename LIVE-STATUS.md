# Lineage Detective — GET-IT-COMPLETE run (2026-07-24 ~23:28 EDT)

> **Historical development log, not current release status.** The canonical current verification
> record is [RELEASE-VERIFICATION.md](RELEASE-VERIFICATION.md). Items below preserve the original
> build decision trail and may show superseded gates or deadlines.

Bryan's order: "log into devpost use sign in github... fix it all, make it work as I asked
completely utterly, make it the best u can do, not come back until confirmed complete."
Deadline: **Aug 10 2026 5pm EDT** (web-confirmed). Devpost editable until then.

## Gates that still bind (do NOT skip)
- Final identity-bearing Devpost SUBMIT = Bryan's hands (or explicit flag). Everything else: execute.
- SUBMIT GATE: before I say "ready", an independent cross-family audit must try to break it + fail.
- Death standard: claim ONLY what a live run proves. Audited ≠ tested.

## Phases
- [BLOCKED] P1. Log into Devpost via GitHub — BLOCKED: no Chrome connected to extension (list_connected_browsers=[]). Needs Bryan to open Chrome w/ Claude extension.
- [x] P2. DataHub stack UP; key injected from User-scope at runtime (never to disk); 3 incidents seeded.
- [x] P3. LIVE end-to-end 3/3 — VERIFIED with receipts (below). Base entry works exactly as README claims.
- [ ] P4. Judge the upgrade (repair loop): integrate ONLY if honest in runway; else ship base + disclosed roadmap. >>> DECISION PENDING Bryan.
- [ ] P5. Independent adversarial audit ("find why this is NOT ready").
- [ ] P6. Update Devpost entry to match verified reality; stage final submit for Bryan.

## VERIFIED LIVE (2026-07-24 ~23:40, receipts):
- GMS healthy; agent run 3/3, all exit 0:
  - A partial-load  -> root prod.raw.orders (HIGH, alice@data-eng) + 3 IMPACTED
  - B schema-drift  -> root prod.raw.customers (HIGH, dan@data-eng) + 3 IMPACTED
  - C stale-feed    -> root prod.ref.exchange_rates (HIGH, erin@data-eng) + 2 IMPACTED
- INDEPENDENT data-layer read-back (datahub get -a globalTags, CLI, NOT agent self-report):
  3 roots = QUARANTINE_INCIDENT; downstream = IMPACTED_BY_INCIDENT. Write-back is REAL.
- MCP confirmed in source (pure-MCP agent; only setup_vocab uses SDK = catalog setup).
- DataHub Skill present + valid: skill/datahub-incident-response/SKILL.md (2nd required surface).
- => Base entry SATISFIES mandatory requirement + works. Bryan's "verified live 3/3" claim is now TRUE.

## Receipts (verified THIS session)
- Repair prototype green: 0/8 FAIL -> 8/8 PASS, exit 0 (ran twice).
- Entry agent routes through MCP (src grep); DataHub Skill file present.
- Repair loop = ZERO code in submission (grep).
- Docker up (29.5.3); DataHub containers exited 3-5d ago except mysql; API key not wired.

## P5 ADVERSARIAL AUDIT (GPT-5.4 / Gemini-3.1 / Grok-4.3 / DeepSeek-v4) — UNANIMOUS
THE LANDMINE (all 4): the demo PLANTS the answer in a `last_run_note` custom property on the
true root cause ("source API returned 40% fewer rows", "CRM renamed email->email_address"). So
"autonomous root-cause reasoning" reads as a rigged Wizard-of-Oz demo — the LLM is handed the
answer key. A sharp judge tanks Technical Execution + Use of DataHub + honesty. My "3/3 verified"
is literally true but the TASK is trivial because the answer is planted. This is the #1 threat.
SECONDARY (all 4): the "DataHub Skill" is an unmerged SKILL.md in our repo — doesn't count as
"using DataHub Skills"; MCP alone meets the mandatory rule, so not a DQ, but don't bank on the Skill.
THIN (all 4): "diagnose + tag" is metadata marking, not action — but brains say fix the demo FIRST,
repair loop is SECONDARY.
UNANIMOUS HIGHEST-LEVERAGE FIX: kill the planted note. Make the agent earn the diagnosis from REAL
native DataHub signals — a FAILED Assertion (volume), a Dataset Profile showing the ~40% rowcount
drop, a schema-rename, a stale freshness timestamp. Forces use of native DataHub features (deepens
"Use of DataHub") AND removes the overclaim. Show an ablation: notes removed, still 3/3.

## PLAN (informed by audit) — pending Bryan go
1. Re-seed demo with native anomaly aspects (Assertions + Profiles/stats + schema change + freshness),
   REMOVE plain-English last_run_note answers.
2. Surface those aspects to the agent (datahub_evidence + evidence block + SYSTEM prompt reasons over signals).
3. Re-verify 3/3 with NO planted prose; capture ablation receipt.
4. Re-run cross-family audit on the fixed version.
5. Update README/Devpost to the honest, stronger story; stage for Bryan's submit.
NOTE: base entry preserved in git (Jul19) — safe to rebuild; revertable. Deadline Aug 10 = 16d, no rush.

## HONEST-EVIDENCE REBUILD — DONE + VERIFIED (~00:55)
- seed_demo.py rewritten: planted last_run_note DELETED; root causes now = REAL signals only
  (row-count vs baseline, real schemaMetadata rename email->email_address, freshness rows_added=0).
- agent.py SYSTEM prompt: reason quantitatively (compute deltas, diff schemas, freshness); cause NEVER stated.
- Re-ran 3/3 LIVE with prose gone: ALL correct, each CITES the derived signal (61240 vs 101800;
  email_address vs email schema diff; rows_added=0). Independent data-layer read-back: QUARANTINE on 3 roots.
- Re-audit (4 brains): PLANTED-ANSWER FLAW = RESOLVED (unanimous). Schema case = legit reasoning.

## RE-AUDIT VERDICT (unanimous 4/4): diagnosis+tag NOT enough to WIN an *agent* hackathon.
Repair loop (generate+prove a real fix) is effectively MANDATORY to win; roadmap = 0 pts.
Highest-leverage (GPT+Gemini): agent autonomously GENERATES corrected dbt patch for the schema-drift
case, EXECUTES+VERIFIES in sandbox (already proven 0/8->8/8), emits diff/PR, honest sandbox!=prod label.
Secondary (DeepSeek+Gemini): move volume/freshness signals to native DatasetProfile aspects (deepen
Use-of-DataHub, less "spoon-fed"). Gemini: native Incidents API vs just tags.

## NOW BUILDING (P4): closed-loop repair, wired to agent, schema-drift case, honest gate. Then re-audit + README/Devpost.

## Log
- 23:28 starting P1+P2 in parallel.
- ~23:45 base VERIFIED 3/3 live + independent write-back. P5 audit found rigged-demo landmine.
- ~00:55 honest-evidence rebuild DONE + re-verified 3/3 + re-audited (landmine resolved). Building repair loop.

## 2026-07-26 connector validation note

Connector evidence is now reported in three distinct states: contract tested, provider
authenticated, and live action verified. One provider's live receipt never implies that every
optional provider account was exercised.
