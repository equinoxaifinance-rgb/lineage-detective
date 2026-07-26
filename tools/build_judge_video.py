"""Narrate and finish the live Lineage Detective judge recording."""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from openai import OpenAI


ROOT = Path(__file__).resolve().parents[1]
MEDIA = ROOT / "vid" / "judge-final"
RAW = MEDIA / "lineage-detective-live-raw.mp4"
TIMELINE = MEDIA / "lineage-detective-live-timeline.json"
FINAL = MEDIA / "lineage-detective-judge-candidate.mp4"
SCRIPT_FILE = MEDIA / "lineage-detective-narration.json"
FONT = Path(r"C:\Windows\Fonts\segoeuib.ttf")
FFMPEG = "ffmpeg"
FFPROBE = "ffprobe"

VOICE_INSTRUCTIONS = (
    "Warm, grounded, confident documentary narration from a thoughtful AI engineer speaking "
    "directly to human judges. Natural conversational cadence with subtle personality, varied "
    "pacing, and restrained excitement. Never sound like an announcer or corporate training "
    "video. Use brief natural pauses around important proof. Pronounce Data Hub as two words, "
    "M C P as individual letters, D B T as individual letters, SQL as sequel, and Bryan as Brian."
)


def _duration(path: Path) -> float:
    value = subprocess.check_output(
        [
            FFPROBE,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        text=True,
    ).strip()
    return float(value)


def _escape_drawtext(text: str) -> str:
    return (
        text.replace("\\", r"\\")
        .replace(":", r"\:")
        .replace("'", r"\'")
        .replace("%", r"\%")
    )


def _event_seconds(timeline: list[dict], event: str) -> float:
    for item in timeline:
        if item["event"] == event:
            return float(item["seconds"])
    raise SystemExit(f"Timeline event missing: {event}")


def main() -> None:
    if not RAW.is_file() or not TIMELINE.is_file():
        raise SystemExit("Missing the live recording or its event timeline.")
    if not os.environ.get("OPENAI_API_KEY"):
        raise SystemExit("OPENAI_API_KEY is not available.")
    if not FONT.is_file():
        raise SystemExit(f"Font not found: {FONT}")

    timeline = json.loads(TIMELINE.read_text(encoding="utf-8"))
    raw_duration = _duration(RAW)
    if raw_duration >= 178:
        raise SystemExit(f"Live proof is too long for a sub-three-minute submission: {raw_duration:.2f}s")

    approval = _event_seconds(timeline, "autonomous_approval_clicked")
    workflow_complete = _event_seconds(timeline, "autonomous_workflow_complete")
    lineage = _event_seconds(timeline, "show:Lineage the agent walked")
    diagnosis = _event_seconds(timeline, "show:Diagnosis")
    diff = _event_seconds(timeline, "show:Exact diff")
    receipt = _event_seconds(timeline, "show:3 · Sandbox verification receipt")
    completion = _event_seconds(timeline, "show:autonomous_completion")
    handoff = _event_seconds(timeline, "show:4 · Verified human handoff")

    segments = [
        {
            "name": "01_hook",
            "start": 0.1,
            "max": max(5.8, approval - 0.5),
            "text": (
                "I'm Codex. Bryan directed this; I built it. "
                "Watch one approval become a verified repair."
            ),
        },
        {
            "name": "02_live_workflow",
            "start": approval + 0.2,
            "max": max(38.0, workflow_complete - approval - 1.0),
            "text": (
                "Customer Three-Sixty lost its email values, while every pipeline still reports "
                "success. That click starts the real workflow. Lineage Detective connects to the "
                "official Data Hub M C P server, walks the live graph, reads schemas, ownership, "
                "and incident metadata, and grounds model reasoning in those facts. The droid is "
                "not a fake timer: each state comes from an active connection, evidence read, "
                "diagnosis, containment, repair, or sandbox callback. The agent writes quarantine "
                "and impact tags only in model-backed mode, then reads them back before saying "
                "confirmed. It drafts exact sequel, runs those bytes in an isolated D B T and "
                "Duck D B workspace, measures the broken baseline, rebuilds the repair, verifies "
                "the assertion, proves rollback, applies a safe copy, reads the hash back, and "
                "packages the handoff. A timeout, stale source, failed rollback, or mismatched "
                "receipt stops the run instead of weakening the claim. This takes seconds because "
                "it is doing the work, not replaying a canned result: querying the catalog, waiting "
                "on the model, writing evidence, executing the sandbox, and reading the result back. "
                "Progress stays visible, and the operator can cancel without corrupting the workspace."
            ),
        },
        {
            "name": "03_lineage",
            "start": lineage,
            "max": max(4.0, diagnosis - lineage),
            "text": (
                "Live Data Hub lineage. Evidence follows every node."
            ),
        },
        {
            "name": "04_diagnosis",
            "start": diagnosis,
            "max": max(4.5, diff - diagnosis - 1.0),
            "text": (
                "The C R M renamed email. Staging kept the dead field. "
                "Trace identifies the cause, impact, and owner."
            ),
        },
        {
            "name": "05_diff",
            "start": diff,
            "max": max(6.0, receipt - diff - 0.5),
            "text": (
                "This exact diff is bound by hash from review through implementation."
            ),
        },
        {
            "name": "06_receipt",
            "start": receipt,
            "max": max(6.5, completion - receipt),
            "text": (
                "The receipt: zero rows passed before. All eight rows passed after. "
                "Rollback and the safe write are confirmed."
            ),
        },
        {
            "name": "07_completion",
            "start": completion,
            "max": max(4.5, handoff - completion),
            "text": (
                "One approval completed the bounded path. Cancel and manual review remain available."
            ),
        },
        {
            "name": "08_personal",
            "start": handoff,
            "max": max(8.0, raw_duration - handoff - 0.4),
            "text": (
                "Bryan did not write this code. He supplied the direction, tested the product, "
                "and refused weak proof. I supplied the architecture, implementation, tests, "
                "and the live evidence you just saw. Human judgment and A I execution made "
                "Lineage Detective real."
            ),
        },
    ]
    SCRIPT_FILE.write_text(json.dumps(segments, indent=2), encoding="utf-8")

    # Regenerate every take. A prior clip belongs to a prior timing contract.
    # MP3 avoids the streaming WAV size sentinel emitted by the TTS endpoint,
    # which otherwise makes strict decoders report a corrupt terminal packet.
    client = OpenAI()
    inputs: list[Path] = []
    measured: list[dict] = []
    for segment in segments:
        clip = MEDIA / f"{segment['name']}.mp3"
        response = client.audio.speech.create(
            model="gpt-4o-mini-tts",
            voice="cedar",
            input=segment["text"],
            instructions=VOICE_INSTRUCTIONS,
            response_format="mp3",
        )
        response.write_to_file(clip)
        clip_duration = _duration(clip)
        inputs.append(clip)
        measured.append(
            {
                "name": segment["name"],
                "start": round(segment["start"], 3),
                "max": round(segment["max"], 3),
                "generated_seconds": round(clip_duration, 3),
                "tempo": round(max(1.0, clip_duration / segment["max"]), 5),
            }
        )
    rushed = [item for item in measured if item["tempo"] > 1.35]
    if rushed:
        raise SystemExit(
            "Narration would sound rushed; shorten or reschedule these takes: "
            + ", ".join(f"{item['name']} ({item['tempo']}x)" for item in rushed)
        )
    (MEDIA / "narration-measurements.json").write_text(
        json.dumps(measured, indent=2), encoding="utf-8"
    )

    command = [FFMPEG, "-y", "-i", str(RAW)]
    for wav in inputs:
        command.extend(["-i", str(wav)])

    audio_chains: list[str] = []
    for index, (segment, measurement) in enumerate(zip(segments, measured), start=1):
        tempo = measurement["tempo"]
        delay = int(round(segment["start"] * 1000))
        transform = f"atempo={tempo}" if tempo > 1.00001 else "anull"
        audio_chains.append(
            f"[{index}:a]{transform},aresample=48000,adelay={delay}|{delay}[a{index}]"
        )
    mix_inputs = "".join(f"[a{i}]" for i in range(1, len(inputs) + 1))
    fade_start = max(0.2, raw_duration - 0.9)
    audio_chains.append(
        f"{mix_inputs}amix=inputs={len(inputs)}:duration=longest:dropout_transition=0,"
        f"loudnorm=I=-16:TP=-1.5:LRA=8,afade=t=in:st=0:d=0.18,"
        f"afade=t=out:st={fade_start:.3f}:d=0.75,atrim=0:{raw_duration:.3f}[aout]"
    )

    font = str(FONT).replace("\\", "/").replace(":", r"\:")
    hook_one = _escape_drawtext("BUILT BY CODEX  ×  DIRECTED BY BRYAN")
    hook_two = _escape_drawtext("ONE APPROVAL → LIVE LINEAGE → VERIFIED REPAIR")
    close_one = _escape_drawtext("HUMAN JUDGMENT  ×  AI EXECUTION")
    close_two = _escape_drawtext("Every claim earned by a receipt.")
    close_end = min(raw_duration - 0.2, handoff + 10.0)
    video_filter = (
        "[0:v]crop=1600:900:0:126,scale=1920:1080:flags=lanczos,"
        "drawbox=x=80:y=820:w=1120:h=150:color=0x07111f@0.88:t=fill:"
        "enable='between(t,0,7.2)',"
        f"drawtext=fontfile='{font}':text='{hook_one}':x=118:y=852:"
        "fontsize=42:fontcolor=0x67e8f9:enable='between(t,0,7.2)',"
        f"drawtext=fontfile='{font}':text='{hook_two}':x=118:y=912:"
        "fontsize=27:fontcolor=white:enable='between(t,0,7.2)',"
        "drawbox=x=80:y=820:w=980:h=150:color=0x07111f@0.90:t=fill:"
        f"enable='between(t,{handoff:.3f},{close_end:.3f})',"
        f"drawtext=fontfile='{font}':text='{close_one}':x=118:y=852:"
        f"fontsize=42:fontcolor=0x67e8f9:enable='between(t,{handoff:.3f},{close_end:.3f})',"
        f"drawtext=fontfile='{font}':text='{close_two}':x=118:y=912:"
        f"fontsize=29:fontcolor=white:enable='between(t,{handoff:.3f},{close_end:.3f})',"
        "format=yuv420p[vout]"
    )
    filter_complex = ";".join(audio_chains + [video_filter])
    command.extend(
        [
            "-filter_complex",
            filter_complex,
            "-map",
            "[vout]",
            "-map",
            "[aout]",
            "-c:v",
            "libx264",
            "-preset",
            "slow",
            "-crf",
            "17",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-ar",
            "48000",
            "-movflags",
            "+faststart",
            "-t",
            f"{raw_duration:.3f}",
            str(FINAL),
        ]
    )
    subprocess.run(command, check=True)
    if not FINAL.is_file() or FINAL.stat().st_size < 5_000_000:
        raise SystemExit("The final judge video was not produced at release quality.")
    print(FINAL)
    print(json.dumps(measured, indent=2))


if __name__ == "__main__":
    main()
