# DataHub Agent Hackathon rules checklist

Official sources accessed 2026-07-27 EDT:

- <https://datahub.devpost.com/>
- <https://datahub.devpost.com/rules>

Submission deadline: **August 10, 2026 at 5:00 PM EDT**. Judging runs
August 17–31, 2026. Access must remain free and unrestricted through the end
of judging.

| Official requirement | Evidence | State |
|---|---|---|
| Working application using DataHub plus MCP Server, Agent Context Kit, DataHub Skills, or Analytics Agent | MCP search, lineage, entity reads, tag writes/readback; reusable DataHub skill | Green in packaged tests |
| Project functions as depicted and described | 205-test packaged suite plus live browser, DataHub write/readback, sandbox, apply, and download receipts | Green in current release candidate |
| Easy project URL for judges | `https://lineage-detective.equinoxaifinance.workers.dev` | Green: public app and full judge path verified |
| Public repository with all source, assets, and setup instructions | `https://github.com/equinoxaifinance-rgb/lineage-detective` | Yellow: synchronize and anonymous-readback |
| Apache 2.0 license visible in repository | `LICENSE` | File green; GitHub About detection pending |
| English project description | `SUBMISSION-DRAFT.md` | Draft green; existing Devpost description is historical and must be synchronized |
| Public video under three minutes showing the product functioning | Final 169.733-second natural-speed live-action video | Media green; owner approval and public YouTube URL remain publication gates |
| Sample generated outputs recommended | `examples/generated/` with verified receipts and handoff archives | Green |
| Free, unrestricted access through August 31 | Bundled public judge DataHub plus bounded reasoning access through September 15 | Green: final code rotated and authenticated through live preflight |
| Newly built during submission period; prior work disclosed | README provenance section | Owner attestation required |
| Authorized third-party APIs/data and original ownership | Public dependencies and scoped credentials | Owner attestation required |
| No prohibited third-party marks/music in video | Final media inspection and signal QA | Green |

## How the entry maps to judging

1. **Use of DataHub** — DataHub is the evidence and action plane, not a logo:
   search, bidirectional lineage, entity metadata, catalog containment writes,
   and readback all flow through MCP.
2. **Technical execution** — fail-closed runtime modes, schema/URN grounding,
   per-run isolation, concurrent-write protection, hash-bound receipts,
   independent live verification, verified rollback, rate/spend controls, and
   a non-root digest-pinned container.
3. **Originality** — turns the DataHub graph into a controlled
   evidence-to-remediation workflow rather than merely answering catalog
   questions.
4. **Real-world usefulness** — gives data-platform and analytics-engineering
   teams a reproducible way to investigate, contain, repair, verify, and hand
   off incidents.
5. **Submission quality** — one concise story, a public live demonstration,
   current setup instructions, sample outputs, and a single canonical receipt
   ledger.

## Owner-only attestations

Bryan must personally confirm on Devpost that eligibility, conflicts,
ownership, third-party authorization, and all required rule agreements are
true. Code can prepare these fields but cannot truthfully attest identity or
legal facts on his behalf.
