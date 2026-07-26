# Official rules checklist

Primary source: [Build with DataHub: The Agent Hackathon — Official Rules](https://datahub.devpost.com/rules)
Checked: 2026-07-26. Recheck immediately before submission because the rules permit amendments.

| Official requirement | Lineage Detective evidence | State |
|---|---|---|
| Working application using DataHub plus an eligible agent surface | DataHub MCP drives search, lineage, entity reads, containment writes, and readback | Implemented and tested |
| Easy-access project URL | `https://lineage-detective.equinoxaifinance.workers.dev` | Reverify after final deploy |
| Public repository with all source, assets, and setup instructions | `https://github.com/equinoxaifinance-rgb/lineage-detective` | Synchronize and read back after owner video approval |
| Apache 2.0 license visible in repository | [`LICENSE`](LICENSE) | Present; recheck GitHub About |
| Text description of features, functionality, technologies, and data | [`README.md`](README.md) plus draft Devpost copy | Repository complete; Devpost pending |
| Public YouTube/Vimeo/Youku video under three minutes | 148.100-second final live-function candidate, SHA-256 `6e0312290a707e536820f4e2e5e206b444de15d516d70d45063a0c078ee323ba` | Artifact verified; owner approval and publication pending |
| Video shows the project functioning on its intended device | Uninterrupted browser approval → live lineage → containment → repair → sandbox → apply → handoff | Recorded and independently inspected |
| No unlicensed trademarks, copyrighted music, or material | Use original UI/Trace art, generated narration, and licensed/original audio only | Enforce during media QA |
| Recommended sample generated outputs | [`examples/generated`](examples/generated/) with exact SQL, diffs, receipts, and ZIPs | Present and hash-verified |
| Free, unrestricted judge access through judging period | Public app plus bounded model gateway instructions; DataHub tenant connection or local quickstart | Reverify credentials, budgets, and expiry before submission |
| New project during submission period; AI assistant use permitted | Provenance/disclosure section in README | Owner attestation required at submission |
| Authorized third-party SDK/API/data use | Public/open-source dependencies and user-supplied scoped service credentials | Owner attestation required at submission |
| Original work, ownership, and no conflict | No pre-existing proprietary code claimed; Apache-compatible dependencies | Owner attestation required at submission |

## Judging alignment

The official criteria are equally weighted. The release deliberately maps to each:

1. **Use of DataHub** — reads the context graph, reasons over lineage/schema/ownership, then writes
   incident state back and verifies it.
2. **Technical execution** — fail-closed receipts, per-run isolation, concurrency tests, source
   drift protection, exact-byte apply/restore, packaged Linux tests, and public readback.
3. **Originality** — closes the loop from metadata-aware diagnosis to catalog containment and a
   verified, human-governed implementation artifact.
4. **Real-world usefulness** — compresses incident triage, blast-radius mapping, owner handoff, and
   repair preparation into one evidence-bound workflow.
5. **Submission quality** — current examples, setup paths, rule checklist, release matrix, and a
   final live demonstration recorded only from the locked product.
6. **Bonus** — no DataHub upstream contribution is claimed unless a real accepted/published
   contribution exists before submission.
