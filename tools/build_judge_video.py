"""Narrate and finish the live Lineage Detective judge recording."""
from __future__ import annotations

import json
import os
import re
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
MAX_SILENCE_SECONDS = 3.0

VOICE_INSTRUCTIONS = (
    "Warm, grounded, confident documentary narration from a thoughtful AI engineer speaking "
    "directly to human judges. Natural conversational cadence with subtle personality, varied "
    "pacing, and restrained excitement. Never sound like an announcer or corporate training "
    "video. Begin each take immediately. Keep pauses short and conversational; never use a "
    "dramatic pause between a subject and its name. Pronounce Data Hub as two words, "
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


def _long_silences(path: Path) -> list[float]:
    result = subprocess.run(
        [
            FFMPEG,
            "-hide_banner",
            "-i",
            str(path),
            "-af",
            "silencedetect=noise=-38dB:d=1.0",
            "-f",
            "null",
            "NUL",
        ],
        capture_output=True,
        text=True,
    )
    output = f"{result.stdout}\n{result.stderr}"
    return [
        float(value)
        for value in re.findall(r"silence_duration:\s*([0-9.]+)", output)
        if float(value) > MAX_SILENCE_SECONDS
    ]


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
                "I am Codex, Bryan directed this build, and I built what you are about to see. "
                "Watch one approval become a verified repair."
            ),
        },
        {
            "name": "02_live_workflow",
            "start": approval + 0.2,
            "max": max(38.0, workflow_complete - approval - 1.0),
            "text": (
                "Customer Three-Sixty lost its email values, while every pipeline still reports "
                "success. This is the moment Lineage Detective is built for: a data engineer on "
                "call, a broken dashboard, and a pipeline that still says green. Most observability "
                "tools alert or draw lineage. Lineage Detective closes the loop. It investigates "
                "through Data Hub, identifies the accountable owner and blast radius, contains the "
                "incident in the catalog, drafts a bounded repair, proves the exact bytes, and "
                "prepares implementation. A team chooses it because they get an answer they can "
                "inspect, not another chatbot claim or a ticket tossed over the wall. That click "
                "starts the real workflow. The agent connects to the official Data Hub M C P server, "
                "walks the live graph, reads schemas, ownership, and incident metadata, and grounds "
                "model reasoning in those facts. Inside, the controller keeps evidence, diagnosis, "
                "proposal, sandbox receipt, and implementation receipt as separate states. The "
                "sequel verifier rejects write-capable statements and relation drift. Quarantine "
                "and impact tags are written only in model-backed mode, then read back before the "
                "word confirmed appears. The exact sequel runs in an isolated D B T and Duck D B "
                "workspace. It measures the broken baseline, rebuilds the repair, verifies the "
                "assertion, proves rollback, checks the hash, and only then unlocks apply or handoff. "
                "A timeout, stale source, failed rollback, or mismatched receipt stops the run. The "
                "rail is driven by those real callbacks, not elapsed time. The operator can cancel "
                "without corrupting the workspace, and the model key never enters this browser."
            ),
        },
        {
            "name": "03_result_transition",
            "start": workflow_complete + 0.1,
            "max": max(2.0, lineage - workflow_complete - 0.2),
            "text": "The approved run completed. Inspect what it produced.",
        },
        {
            "name": "04_lineage",
            "start": lineage,
            "max": max(4.0, diagnosis - lineage),
            "text": (
                "Live Data Hub lineage. Evidence follows every node."
            ),
        },
        {
            "name": "05_diagnosis",
            "start": diagnosis,
            "max": max(4.5, diff - diagnosis - 1.0),
            "text": (
                "The C R M renamed email. Staging kept the dead field. "
                "Trace identifies the cause, impact, and owner."
            ),
        },
        {
            "name": "06_diff",
            "start": diff,
            "max": max(6.0, receipt - diff - 0.5),
            "text": (
                "That exact diff keeps one hash from review through implementation."
            ),
        },
        {
            "name": "07_receipt",
            "start": receipt,
            "max": max(6.5, completion - receipt),
            "text": (
                "The receipt shows zero rows passed before and all eight passed after. "
                "Rollback and the safe write are confirmed."
            ),
        },
        {
            "name": "08_completion",
            "start": completion,
            "max": max(4.5, handoff - completion),
            "text": (
                "One approval completed the path. Cancel and manual review remain available."
            ),
        },
        {
            "name": "09_personal",
            "start": handoff,
            "max": max(8.0, raw_duration - handoff - 0.4),
            "text": (
                "Bryan did not write this code. He brought the direction, tested each version, and "
                "refused weak proof. I brought the architecture, implementation, tests, and evidence. "
                "This was not one prompt. His judgment challenged my first answers, and I rebuilt "
                "them into working code. Human judgment and A I execution made Lineage Detective "
                "real, together."
            ),
        },
    ]
    # The live timeline, not a minimum narration preference, owns every cut.
    # Leave a small breath before the next visual state so two takes can never
    # talk over one another after tempo correction.
    for current, following in zip(segments, segments[1:]):
        available = float(following["start"]) - float(current["start"]) - 0.18
        if available <= 0:
            raise SystemExit(
                f"Invalid narration order: {current['name']} reaches {following['name']}."
            )
        current["max"] = min(float(current["max"]), available)
    segments[-1]["max"] = min(
        float(segments[-1]["max"]),
        raw_duration - float(segments[-1]["start"]) - 0.18,
    )
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
        tempo = max(1.0, clip_duration / segment["max"])
        mixed_seconds = clip_duration / tempo
        measured.append(
            {
                "name": segment["name"],
                "start": round(segment["start"], 3),
                "max": round(segment["max"], 3),
                "generated_seconds": round(clip_duration, 3),
                "tempo": round(tempo, 5),
                "mixed_seconds": round(mixed_seconds, 3),
                "ends_at": round(segment["start"] + mixed_seconds, 3),
            }
        )
    rushed = [item for item in measured if item["tempo"] > 1.35]
    if rushed:
        raise SystemExit(
            "Narration would sound rushed; shorten or reschedule these takes: "
            + ", ".join(f"{item['name']} ({item['tempo']}x)" for item in rushed)
        )
    for current, following in zip(measured, measured[1:]):
        if current["ends_at"] > following["start"] - 0.1:
            raise SystemExit(
                "Narration timing collision: "
                f"{current['name']} ends at {current['ends_at']:.3f}s, "
                f"too close to {following['name']} at {following['start']:.3f}s."
            )
    if measured[-1]["ends_at"] > raw_duration - 0.08:
        raise SystemExit(
            "Final narration overruns the captured video: "
            f"{measured[-1]['ends_at']:.3f}s > {raw_duration:.3f}s."
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
    long_silences = _long_silences(FINAL)
    if long_silences:
        raise SystemExit(
            "Narration left an unsupported visual stretch: "
            + ", ".join(f"{duration:.3f}s" for duration in long_silences)
        )
    print(FINAL)
    print(json.dumps(measured, indent=2))


if __name__ == "__main__":
    main()
