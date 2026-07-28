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
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path
from typing import Any

from datahub_mcp import MCPDataHub
from datahub_evidence import gather_upstream, NodeEvidence
from network_policy import validate_network_url, validate_resolution
from runtime_mode import is_public_judge

HOSTED_JUDGE_GATEWAY = "https://lineage-detective-judge-gateway.equinoxaifinance.workers.dev"


def _direct_provider_key() -> str | None:
    """Expose a direct model credential only in explicit self-hosted mode."""
    if is_public_judge():
        return None
    return os.environ.get("ANTHROPIC_API_KEY")


SYSTEM = """You are Lineage Detective, a data-incident root-cause analyst.
You are given (a) a symptom reported by a human and (b) REAL evidence gathered from a DataHub
metadata catalog: the affected dataset and its UPSTREAM lineage. For each node you may see its
schema (column names + types), owner, description, and operational properties (row counts, load
timestamps, run statuses, data-quality test coverage, null rates, refresh cadence). Reason like an
on-call data engineer.

THE CAUSE IS NEVER STATED IN PLAIN LANGUAGE. No property tells you the answer — you must DERIVE it
by reasoning over the signals:
- Volume: a node whose current row count is far below its own prior/baseline average is a silent
  partial load — a real data loss even when run_status is 'success'. Compare the numbers.
- Schema drift: diff schemas across hops. A column that appears upstream under a NEW name but is
  still selected under its OLD name downstream is a broken mapping; a spiking null rate on that
  downstream column corroborates it. Distinguish the upstream rename (the trigger) from the
  downstream mapping that still selects the old field (the immediate repair locus). Rank the broken
  mapping first when it is the safe actionable target, and name the upstream rename as its trigger.
- Freshness: a source whose latest data date is stale, or that added ~0 rows across recent runs
  despite a daily cadence and a 'success' status, is a frozen/stale feed.
- 'success' status does NOT mean healthy. Look for silent data problems, and note where a guarding
  test (volume / freshness / not_null) is absent — that absence is why the failure went undetected.
- The root cause is usually the FARTHEST-UPSTREAM node that FIRST exhibits the anomaly; downstream
  nodes that merely pass it through are impacts, not causes.

Rules:
- Use ONLY the evidence provided. Do not invent tables, owners, numbers, or failures.
- Rank the 1-3 most likely root-cause locations, each with WHY the evidence points there — cite the
  SPECIFIC signal you reasoned from (the row-count delta, the schema mismatch, the freshness gap) —
  and WHAT to check next.
- Name the owner to contact for the top suspect if known.
- If the evidence is insufficient, say exactly what additional signal (an assertion, a run log)
  would resolve it. Never bluff a confident answer the evidence can't support.
Return STRICT JSON: {"summary": str, "suspects": [{"urn": str, "why": str, "check_next": str,
"owner": str|null, "confidence": "high"|"medium"|"low"}], "missing_evidence": str|null}"""


def _extract_json_report(text: str) -> dict | None:
    """Tolerate a Markdown fence or a short model preamble, never silently invent a report."""
    value = (text or "").strip()
    if value.startswith("```"):
        parts = value.split("```", 2)
        value = parts[1].removeprefix("json").strip() if len(parts) > 1 else value
    if not value.startswith("{"):
        first, last = value.find("{"), value.rfind("}")
        value = value[first:last + 1] if first >= 0 and last > first else value
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _validated_model_report(
    report: dict | None, *, observed_urns: set[str]
) -> dict | None:
    """Return a bounded, evidence-grounded report or reject the whole model result."""
    if not isinstance(report, dict):
        return None
    summary = report.get("summary")
    suspects = report.get("suspects")
    missing = report.get("missing_evidence")
    if not isinstance(summary, str) or not summary.strip() or len(summary) > 4_000:
        return None
    if not isinstance(suspects, list) or len(suspects) > 3:
        return None
    if missing is not None and (
        not isinstance(missing, str) or len(missing) > 2_000
    ):
        return None
    clean_suspects: list[dict[str, Any]] = []
    for suspect in suspects:
        if not isinstance(suspect, dict):
            return None
        urn = suspect.get("urn")
        why = suspect.get("why")
        check_next = suspect.get("check_next")
        owner = suspect.get("owner")
        confidence = suspect.get("confidence")
        if (
            not isinstance(urn, str)
            or urn not in observed_urns
            or len(urn) > 2_048
            or not isinstance(why, str)
            or not why.strip()
            or len(why) > 2_000
            or not isinstance(check_next, str)
            or not check_next.strip()
            or len(check_next) > 2_000
            or (owner is not None and (not isinstance(owner, str) or len(owner) > 500))
            or confidence not in {"high", "medium", "low"}
        ):
            return None
        clean_suspects.append({
            "urn": urn,
            "why": why.strip(),
            "check_next": check_next.strip(),
            "owner": owner.strip() if isinstance(owner, str) else None,
            "confidence": confidence,
        })
    return {
        "summary": summary.strip(),
        "suspects": clean_suspects,
        "missing_evidence": missing.strip() if isinstance(missing, str) else None,
    }


def _reason_over_evidence(
    llm, *, model: str, user: str, observed_urns: set[str]
) -> dict:
    """Make at most one corrective retry for a malformed structured response.

    The retry only asks for the same report in valid JSON; it does not add facts or change the
    evidence. If it still fails we return an explicit insufficient-format report instead of
    pretending the incident was diagnosed.
    """
    messages = [{"role": "user", "content": user}]
    for attempt in range(2):
        resp = llm.messages.create(model=model, max_tokens=1500, system=SYSTEM, messages=messages)
        text = "".join(getattr(block, "text", "") for block in resp.content
                       if getattr(block, "type", None) == "text").strip()
        report = _validated_model_report(
            _extract_json_report(text),
            observed_urns=observed_urns,
        )
        if report is not None:
            return report
        if attempt == 0:
            messages.append({"role": "user", "content": (
                "Your last response failed the required JSON schema or referenced an entity outside "
                "the supplied DataHub evidence. Return the same evidence-grounded report again as "
                "one JSON object only, with exactly the required keys and no Markdown. Every suspect "
                "URN must exactly match an evidence URN.")})
    return {
        "summary": "The evidence was gathered, but the reasoning response failed schema or evidence-grounding validation.",
        "suspects": [],
        "missing_evidence": "Retry the investigation; no containment or repair was performed from an invalid model response.",
    }


class _GatewayTextBlock:
    type = "text"

    def __init__(self, text: str):
        self.text = text


class _GatewayResponse:
    def __init__(self, text: str):
        self.content = [_GatewayTextBlock(text)]


class _RejectGatewayRedirects(urllib.request.HTTPRedirectHandler):
    """Never forward the invitation credential to a redirected host."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class _GatewayMessages:
    """Small Anthropic-compatible adapter that keeps the provider credential server-side."""
    def __init__(self, endpoint: str, judge_code: str, *, hosted_mode: bool = False):
        normalized = validate_network_url(
            endpoint,
            allow_private=not hosted_mode,
            label="Judge gateway URL",
        ).rstrip("/")
        if hosted_mode and normalized != HOSTED_JUDGE_GATEWAY:
            raise ValueError("The hosted app accepts only its release-bound judge gateway.")
        self.base_endpoint = normalized
        self.endpoint = normalized + "/reason"
        self.judge_code = judge_code
        self.hosted_mode = hosted_mode

    def create(self, *, model: str, max_tokens: int, system: str = "", messages: list[dict]) -> _GatewayResponse:
        # Preserve the original evidence on the one allowed format-correction retry.  Sending
        # only the final retry instruction would make the remote model reason without facts.
        user = "\n\n".join(
            str(item.get("content", "")) for item in messages if item.get("role") == "user"
        )
        body = json.dumps({"system": system, "user": user}).encode("utf-8")
        request = urllib.request.Request(
            self.endpoint, data=body, method="POST",
            # Cloudflare's managed browser-integrity layer rejects Python urllib's
            # anonymous default user agent before the Worker gets a chance to
            # authenticate it. This is an honest client identity, not browser
            # impersonation, and keeps the local judge route usable.
            headers={"content-type": "application/json", "x-lineage-judge-code": self.judge_code,
                     "user-agent": "Lineage-Detective-Judge/1.0"},
        )
        try:
            validate_resolution(
                self.endpoint,
                allow_private=not self.hosted_mode,
                label="Judge gateway URL",
            )
            opener = urllib.request.build_opener(_RejectGatewayRedirects())
            with opener.open(request, timeout=45) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:400]
            raise RuntimeError(f"Judge gateway returned HTTP {exc.code}: {detail}") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise RuntimeError(f"Judge gateway is unavailable: {exc}") from exc
        text = payload.get("text") if isinstance(payload, dict) else None
        if not isinstance(text, str) or not text.strip():
            raise RuntimeError("Judge gateway returned no reasoning text.")
        return _GatewayResponse(text)

    def preflight(self) -> dict[str, Any]:
        """Verify the judge invitation and server-side bindings without model spend."""
        endpoint = self.base_endpoint + "/preflight"
        request = urllib.request.Request(
            endpoint,
            data=b"",
            method="POST",
            headers={
                "x-lineage-judge-code": self.judge_code,
                "user-agent": "Lineage-Detective-Judge/1.0",
            },
        )
        try:
            validate_resolution(
                endpoint,
                allow_private=not self.hosted_mode,
                label="Judge gateway URL",
            )
            opener = urllib.request.build_opener(_RejectGatewayRedirects())
            with opener.open(request, timeout=15) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:400]
            raise RuntimeError(
                f"Judge gateway preflight returned HTTP {exc.code}: {detail}"
            ) from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise RuntimeError(f"Judge gateway preflight is unavailable: {exc}") from exc
        if not isinstance(payload, dict) or payload.get("ready") is not True:
            raise RuntimeError("Judge gateway preflight did not verify access.")
        return {
            "ready": True,
            "access_expires": str(payload.get("access_expires") or ""),
            "model": str(payload.get("model") or ""),
            "daily_requests_remaining": int(payload.get("daily_requests_remaining") or 0),
        }


class _GatewayClient:
    def __init__(self, endpoint: str, judge_code: str, *, hosted_mode: bool = False):
        self.messages = _GatewayMessages(endpoint, judge_code, hosted_mode=hosted_mode)


def preflight_judge_gateway(
    endpoint: str, judge_code: str, *, hosted_mode: bool = False
) -> dict[str, Any]:
    return _GatewayMessages(
        endpoint, judge_code, hosted_mode=hosted_mode
    ).preflight()


def _evidence_block(nodes: list[NodeEvidence]) -> str:
    lines = []
    for n in nodes:
        lines.append(f"- {n.summary()}\n    urn: {n.urn}"
                     + (f"\n    description: {n.description}" if n.description else "")
                     + (f"\n    columns: {', '.join(n.schema_fields[:20])}" if n.schema_fields else ""))
    return "\n".join(lines)


def _number(value: Any) -> float | None:
    """Parse a catalog numeric property without treating malformed metadata as zero."""
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _evidence_only_report(nodes: list[NodeEvidence]) -> dict:
    """Return a deterministic report from *observed* catalog signals.

    This is deliberately narrower than the model-backed investigator.  It is a
    no-key judge route, not an imitation LLM: every rule below names the exact
    DataHub property which triggered it and declines a diagnosis where no
    deterministic signal exists.
    """
    suspects: list[dict] = []
    for index, node in enumerate(nodes):
        props = {str(k).lower(): v for k, v in node.custom_properties.items()}
        latest_key = next((k for k in props if "rows" in k and ("latest" in k or "current" in k)), None)
        baseline_key = next((k for k in props if "rows" in k and ("prior" in k or "baseline" in k or "avg" in k)), None)
        latest = _number(props.get(latest_key)) if latest_key else None
        baseline = _number(props.get(baseline_key)) if baseline_key else None
        if latest is not None and baseline and baseline > 0:
            drop = (baseline - latest) / baseline
            if drop >= 0.20:
                test_key = next((k for k in props if "volume" in k and "test" in k), None)
                test_note = (f"; {test_key}={props[test_key]}" if test_key else "")
                suspects.append({
                    "urn": node.urn,
                    "why": (f"{latest_key}={latest:,.0f} is {drop:.0%} below "
                            f"{baseline_key}={baseline:,.0f}{test_note}."),
                    "check_next": "Confirm the source extract and row-count history before a governed backfill.",
                    "owner": ", ".join(node.owners) or node.custom_properties.get("owner"),
                    "confidence": "high" if drop >= 0.35 else "medium",
                    "_score": 100 + drop,
                })

        null_key = next((k for k in props if "null_rate" in k and ("current" in k or "latest" in k)), None)
        prior_null_key = next((k for k in props if "null_rate" in k and ("prior" in k or "baseline" in k)), None)
        current_null = _number(props.get(null_key)) if null_key else None
        prior_null = _number(props.get(prior_null_key)) if prior_null_key else None
        if current_null is not None and current_null >= 0.80 and (prior_null is None or current_null - prior_null >= 0.30):
            upstream_columns = set()
            for upstream in nodes[index + 1:]:
                upstream_columns.update(str(field) for field in upstream.schema_fields)
            local_columns = set(str(field) for field in node.schema_fields)
            possible_renames = sorted(
                column for column in upstream_columns - local_columns
                if any(column.startswith(local + "_") for local in local_columns)
            )
            rename_note = (f" Upstream exposes possible renamed field(s): {', '.join(possible_renames[:3])}."
                           if possible_renames else "")
            suspects.append({
                "urn": node.urn,
                "why": (f"{null_key}={current_null:.2f}" +
                        (f" versus {prior_null_key}={prior_null:.2f}" if prior_null is not None else "") +
                        f" shows an abrupt null surge in this mapping.{rename_note}"),
                "check_next": "Review the upstream-to-downstream column mapping and add a not-null assertion before retrying.",
                "owner": ", ".join(node.owners) or node.custom_properties.get("owner"),
                "confidence": "high",
                "_score": 90 + current_null,
            })

        added_key = next((k for k in props if "rows_added" in k), None)
        freshness_key = next((k for k in props if "latest" in k and ("date" in k or "fresh" in k)), None)
        cadence_key = next((k for k in props if "cadence" in k or "frequency" in k), None)
        added = _number(props.get(added_key)) if added_key else None
        stale_days = None
        if freshness_key:
            try:
                stale_days = (date.today() - date.fromisoformat(str(props[freshness_key])[:10])).days
            except ValueError:
                pass
        daily = cadence_key and "daily" in str(props[cadence_key]).lower()
        if added == 0 and (daily or stale_days is not None):
            detail = f"{added_key}=0"
            if freshness_key and stale_days is not None:
                detail += f"; {freshness_key}={props[freshness_key]} ({stale_days} days old)"
            if cadence_key:
                detail += f"; {cadence_key}={props[cadence_key]}"
            suspects.append({
                "urn": node.urn,
                "why": f"{detail}, so the feed has an observable freshness/throughput anomaly.",
                "check_next": "Inspect the source extract and run history, then restore freshness before downstream recomputation.",
                "owner": ", ".join(node.owners) or node.custom_properties.get("owner"),
                "confidence": "high" if stale_days is not None and stale_days >= 2 else "medium",
                "_score": 80 + min(stale_days or 0, 30),
            })

    ranked = sorted(suspects, key=lambda item: item.pop("_score"), reverse=True)[:3]
    if ranked:
        return {
            "summary": "Evidence-only mode found deterministic anomaly signals in live DataHub metadata. "
                       "This ranking is rule-based, not model-generated.",
            "suspects": ranked,
            "missing_evidence": "Use model-backed mode for broader, evidence-constrained reasoning over ambiguous incidents.",
            "reasoning_mode": "evidence_only_deterministic",
        }
    return {
        "summary": "Evidence-only mode found no deterministic volume, null-rate, or freshness anomaly in the returned DataHub metadata.",
        "suspects": [],
        "missing_evidence": "Add operational metadata (baseline volumes, freshness timestamps, or quality assertions), or use model-backed mode for broader evidence-constrained reasoning.",
        "reasoning_mode": "evidence_only_deterministic",
    }


def investigate(symptom: str, affected_urn: str, *, server: str, token: str | None = None,
                max_hops: int = 3, model: str = "claude-sonnet-5", act: bool = False,
                on_progress=None, reasoning_mode: str = "auto", reasoning_endpoint: str | None = None,
                judge_code: str | None = None,
                repair_artifact: dict | None = None,
                mcp_url: str | None = None) -> dict:
    """Run the full autonomous investigation. Returns the parsed root-cause report.
    If act=True, the agent quarantines the top high/medium-confidence suspect in DataHub.
    All DataHub access — reads and the write-back — flows through the DataHub MCP Server."""
    def progress(phase: str, detail: str) -> None:
        """Report only real checkpoints to an optional UI/CLI observer."""
        if on_progress:
            on_progress(phase, detail)

    progress("connecting", "Opening the official DataHub MCP connection...")
    with MCPDataHub(gms_url=server, token=token, mcp_url=mcp_url) as client:
        progress("evidence", f"Reading the affected asset and up to {max_hops} upstream lineage hops...")
        evidence = gather_upstream(client, affected_urn, max_hops=max_hops)
        progress("reasoning", f"DataHub returned {len(evidence)} evidence nodes. Grounding the diagnosis in those facts...")

        requested_mode = reasoning_mode.lower()
        if requested_mode not in {"auto", "model", "evidence"}:
            raise ValueError("reasoning_mode must be auto, model, or evidence")
        provider_key = _direct_provider_key()
        reasoning_endpoint = reasoning_endpoint or os.environ.get("LINEAGE_REASONING_ENDPOINT")
        judge_code = judge_code or os.environ.get("LINEAGE_JUDGE_CODE")
        gateway_available = bool(reasoning_endpoint and judge_code)
        use_model = requested_mode == "model" or (requested_mode == "auto" and bool(provider_key or gateway_available))
        llm = None
        if use_model:
            if provider_key:
                from anthropic import Anthropic
                llm = Anthropic(api_key=provider_key)
                report_mode = "model_backed_local_secret"
            elif gateway_available:
                llm = _GatewayClient(
                    str(reasoning_endpoint),
                    str(judge_code),
                    hosted_mode=is_public_judge(),
                )
                report_mode = "model_backed_judge_gateway"
            else:
                raise RuntimeError("Model-backed mode requires a local provider key or configured judge gateway.")
            user = (f"SYMPTOM: {symptom}\n\nAFFECTED ENTITY: {affected_urn}\n\n"
                    f"UPSTREAM EVIDENCE FROM DATAHUB ({len(evidence)} nodes):\n{_evidence_block(evidence)}")
            report = _reason_over_evidence(
                llm,
                model=model,
                user=user,
                observed_urns={node.urn for node in evidence} | {affected_urn},
            )
            report["reasoning_mode"] = report_mode
        else:
            progress("reasoning", "No model key is present; applying deterministic checks to the live DataHub evidence...")
            report = _evidence_only_report(evidence)
        report["_evidence_nodes"] = len(evidence)

        # Containment is the existing autonomous action: act on a confident finding in DataHub.
        if act and report.get("suspects") and use_model:
            top = report["suspects"][0]
            if str(top.get("confidence", "")).lower() in {"high", "medium"} and top.get("urn"):
                from act import quarantine_node, map_and_contain_blast_radius
                progress("containment", "Writing the confirmed incident tags through MCP, then reading them back...")
                report["action"] = quarantine_node(client, top["urn"], note=top.get("why"))
                report["blast_radius"] = map_and_contain_blast_radius(client, top["urn"])

        # A repair is never an automatic continuation of containment. We may generate a
        # reviewable diff, but the UI requires an explicit sandbox action before it offers a
        # separate hash-bound apply action against a checked-out file. Deployment remains outside
        # this agent because a local file write is not proof of production correctness.
        if report.get("suspects") and use_model:
            try:
                from repair import propose_repair
                progress("repair", "Checking whether the evidence supports a reviewable repair proposal...")
                proposal = propose_repair(
                    llm,
                    report,
                    evidence,
                    model=model,
                    target_artifact=repair_artifact,
                )
                if proposal:
                    report["repair"] = proposal
            except Exception as e:  # additive only; diagnosis/containment remain available
                report["repair"] = {"state": "proposal_failed", "attempted": False,
                                    "verified": False, "error": f"{type(e).__name__}: {e}"}
        elif act and not use_model:
            report["action"] = {"applied": False, "blocked": True,
                                "reason": "Evidence-only mode is read-only; model-backed mode is required before catalog containment."}

        # visualization only (fail-open): recover the lineage graph the agent walked, root cause lit up
        try:
            from graph_viz import lineage_dot
            progress("visualizing", "Rendering the lineage path that the agent actually walked...")
            report["lineage_dot"] = lineage_dot(client, affected_urn, report, max_hops=max_hops)
        except Exception:
            report["lineage_dot"] = None
    progress("complete", "Investigation complete. The report below separates evidence, action, and any unverified boundary.")
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
    rep = report.get("repair")
    if rep and rep.get("state") == "approval_required":
        L.append("")
        L.append("REPAIR PROPOSAL — explicit sandbox action required before implementation")
        L.append(f"  target: {rep.get('target', '?')}")
        L.append(f"  rationale: {rep.get('rationale', '').strip()}")
        if rep.get("diff"):
            L.append("  patch (review only; not applied):")
            for dl in rep["diff"].splitlines():
                L.append("    " + dl)
        L.append("  boundary: " + rep.get("representativeness", ""))
    elif rep and rep.get("attempted") and rep.get("applicable") is not False and not rep.get("error"):
        L.append("")
        status = "[OK] VERIFIED" if rep.get("verified") else "[!!] NOT VERIFIED"
        L.append(f"APPROVED SANDBOX TRIAL — verified in an isolated sandbox  {status}")
        L.append(f"  before: {rep.get('before','?')}")
        L.append(f"  after : {rep.get('after','?')}")
        if rep.get("diff"):
            L.append("  patch (unified diff, for human review — NOT auto-applied to prod):")
            for dl in rep["diff"].splitlines():
                L.append("    " + dl)
        L.append("  honesty: " + rep.get("representativeness", ""))
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
    p.add_argument(
        "--mcp-url", default=os.environ.get("DATAHUB_MCP_URL"),
        help="optional DataHub Cloud managed MCP endpoint (streamable HTTP)",
    )
    p.add_argument("--max-hops", type=int, default=3)
    p.add_argument("--format", choices=["report", "json"], default="report")
    p.add_argument("--act", action="store_true", help="quarantine the top suspect in DataHub")
    p.add_argument(
        "--repair-file",
        help="optional existing checked-out dbt .sql file to inspect and propose a constrained repair for",
    )
    args = p.parse_args()
    repair_artifact = None
    if args.repair_file:
        repair_path = Path(args.repair_file).expanduser().resolve(strict=True)
        if repair_path.is_symlink() or not repair_path.is_file() or repair_path.suffix.lower() != ".sql":
            p.error("--repair-file must be an existing regular .sql file")
        if repair_path.stat().st_size > 200_000:
            p.error("--repair-file exceeds the 200 KB repair limit")
        try:
            repair_sql = repair_path.read_text(encoding="utf-8")
        except UnicodeError:
            p.error("--repair-file must be UTF-8 text")
        repair_artifact = {
            "path": str(repair_path),
            "file_name": repair_path.name,
            "sql": repair_sql,
        }
    if args.act:  # catalog SETUP on any instance (create-if-missing incident tags); the agent stays pure-MCP
        try:
            from setup_vocab import ensure_incident_vocabulary
            ensure_incident_vocabulary(args.server, token=args.token)
        except Exception as _e:
            print(f"[setup] tag vocabulary ensure skipped ({type(_e).__name__}) — "
                  f"if acting fails, create QUARANTINE_INCIDENT / IMPACTED_BY_INCIDENT once in your catalog.")
    out = investigate(args.symptom, args.affected_urn, server=args.server, token=args.token,
                      max_hops=args.max_hops, act=args.act, repair_artifact=repair_artifact,
                      mcp_url=args.mcp_url)
    if args.format == "json":
        print(json.dumps(out, indent=2, default=str))
    else:
        print(render_report(out, args.symptom, args.affected_urn))
