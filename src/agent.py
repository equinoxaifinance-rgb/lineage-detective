"""agent.py — Lineage Detective.

An autonomous data-incident root-cause agent. Given a symptom in plain English
("the revenue dashboard dropped 40% overnight") and the affected entity, it:
  1. walks UPSTREAM through DataHub lineage, gathering evidence at every node,
  2. reasons over the collected evidence with a frontier LLM,
  3. returns a ranked root-cause report + who to contact (owner).

The agent never invents metadata — every fact comes from DataHub (datahub_evidence).
The LLM only *reasons* over real evidence; it does not supply the facts.
"""
from __future__ import annotations
import json
import os
import sys

from datahub_evidence import make_client, gather_upstream, NodeEvidence

SYSTEM = """You are Lineage Detective, a data-incident root-cause analyst.
You are given (a) a symptom reported by a human and (b) real evidence gathered from a DataHub
metadata catalog: the affected dataset and its UPSTREAM lineage, each node with owner/schema/
description. Reason like an on-call data engineer.

Rules:
- Use ONLY the evidence provided. Do not invent tables, owners, or failures not present.
- Rank the 1-3 most likely root-cause locations in the upstream graph, each with WHY the evidence
  points there and WHAT to check next.
- Name the owner to contact for the top suspect if known.
- If the evidence is insufficient, say exactly what additional signal (an assertion, a run log)
  would resolve it. Never bluff a confident answer the evidence can't support.
Return STRICT JSON: {"summary": str, "suspects": [{"urn": str, "why": str, "check_next": str,
"owner": str|null, "confidence": "high"|"medium"|"low"}], "missing_evidence": str|null}"""


def _evidence_block(nodes: list[NodeEvidence]) -> str:
    lines = []
    for n in nodes:
        lines.append(f"- {n.summary()}\n    urn: {n.urn}"
                     + (f"\n    description: {n.description}" if n.description else "")
                     + (f"\n    columns: {', '.join(n.schema_fields[:20])}" if n.schema_fields else ""))
    return "\n".join(lines)


def investigate(symptom: str, affected_urn: str, *, server: str, token: str | None = None,
                max_hops: int = 3, model: str = "claude-sonnet-5", act: bool = False) -> dict:
    """Run the full autonomous investigation. Returns the parsed root-cause report.
    If act=True, the agent quarantines the top high/medium-confidence suspect in DataHub."""
    client = make_client(server, token)
    evidence = gather_upstream(client, affected_urn, max_hops=max_hops)

    from anthropic import Anthropic
    llm = Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
    user = (f"SYMPTOM: {symptom}\n\nAFFECTED ENTITY: {affected_urn}\n\n"
            f"UPSTREAM EVIDENCE FROM DATAHUB ({len(evidence)} nodes):\n{_evidence_block(evidence)}")
    resp = llm.messages.create(
        model=model, max_tokens=1500, system=SYSTEM,
        messages=[{"role": "user", "content": user}],
    )
    # response may contain thinking + text blocks; take the text block(s) only
    text = "".join(getattr(b, "text", "") for b in resp.content
                   if getattr(b, "type", None) == "text").strip()
    if text.startswith("```"):
        text = text.split("```")[1].removeprefix("json").strip()
    try:
        report = json.loads(text)
    except json.JSONDecodeError:
        report = {"summary": text, "suspects": [], "missing_evidence": "LLM did not return valid JSON"}
    report["_evidence_nodes"] = len(evidence)

    # close the loop: act on the finding by quarantining the top confident suspect in DataHub
    if act and report.get("suspects"):
        top = report["suspects"][0]
        if str(top.get("confidence", "")).lower() in {"high", "medium"} and top.get("urn"):
            from act import quarantine_node, map_and_contain_blast_radius
            report["action"] = quarantine_node(client, top["urn"], note=top.get("why"))
            report["blast_radius"] = map_and_contain_blast_radius(client, top["urn"])
    return report


_CONF_ICON = {"high": "[!!!]", "medium": "[!! ]", "low": "[!  ]"}


def render_report(report: dict, symptom: str, affected_urn: str) -> str:
    """Human-readable incident report — this is what the demo/video shows and judges read."""
    L = []
    L.append("=" * 68)
    L.append("  LINEAGE DETECTIVE — Autonomous Data-Incident Report")
    L.append("=" * 68)
    L.append(f"Symptom  : {symptom}")
    L.append(f"Affected : {affected_urn.rsplit('(', 1)[-1].rstrip(')')}")
    L.append(f"Traced   : {report.get('_evidence_nodes', '?')} upstream entities via DataHub lineage")
    L.append("")
    L.append("SUMMARY")
    L.append("  " + (report.get("summary") or "").strip())
    L.append("")
    L.append("ROOT-CAUSE SUSPECTS (ranked)")
    for i, s in enumerate(report.get("suspects", []), 1):
        icon = _CONF_ICON.get(str(s.get("confidence", "")).lower(), "•")
        name = s.get("urn", "").rsplit("(", 1)[-1].rstrip(")").split(",")
        label = name[-2] if len(name) >= 2 else s.get("urn", "")
        who = s.get("owner") or "owner unknown"
        L.append(f"  {i}. {icon} [{str(s.get('confidence','?')).upper()}] {label}   → contact: {who}")
        L.append(f"       why : {s.get('why','').strip()}")
        L.append(f"       next: {s.get('check_next','').strip()}")
    act = report.get("action")
    if act:
        node = act.get("urn", "").rsplit("(", 1)[-1].rstrip(")").split(",")
        node = node[-2] if len(node) >= 2 else act.get("urn", "")
        status = "[OK] APPLIED" if act.get("applied") else "[..] attempted"
        L.append("")
        L.append("ACTION TAKEN (autonomous write-back to DataHub)")
        L.append(f"  {status}: tagged {node} '{act.get('tag','').split(':')[-1]}' "
                 f"— downstream consumers are now warned in the catalog they already use.")
    br = report.get("blast_radius")
    if br:
        L.append("")
        L.append(f"BLAST RADIUS — {br.get('impacted_count', 0)} downstream assets contaminated "
                 f"({br.get('tagged', 0)} tagged IMPACTED)")
        if br.get("dashboards"):
            L.append("  dashboards affected: " + ", ".join(br["dashboards"]))
        if br.get("assets"):
            L.append("  data assets affected: " + ", ".join(br["assets"]))
    if report.get("missing_evidence"):
        L.append("")
        L.append("TO CONFIRM")
        L.append("  " + report["missing_evidence"].strip())
    L.append("=" * 68)
    return "\n".join(L)


if __name__ == "__main__":
    import argparse
    try:  # unicode-safe output on any platform (Windows cp1252, judge terminals, etc.)
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    p = argparse.ArgumentParser(description="Lineage Detective — autonomous data-incident root cause")
    p.add_argument("symptom")
    p.add_argument("affected_urn")
    p.add_argument("--server", default=os.environ.get("DATAHUB_SERVER", "http://localhost:8080"))
    p.add_argument("--token", default=os.environ.get("DATAHUB_TOKEN"))
    p.add_argument("--max-hops", type=int, default=3)
    p.add_argument("--format", choices=["report", "json"], default="report")
    p.add_argument("--act", action="store_true", help="quarantine the top suspect in DataHub")
    args = p.parse_args()
    out = investigate(args.symptom, args.affected_urn, server=args.server, token=args.token,
                      max_hops=args.max_hops, act=args.act)
    if args.format == "json":
        print(json.dumps(out, indent=2, default=str))
    else:
        print(render_report(out, args.symptom, args.affected_urn))
