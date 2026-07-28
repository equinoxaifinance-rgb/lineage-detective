"""Build the final judge video from one uninterrupted narration take.

The visual track is the real public browser recording produced by
``record_judge_demo.py``. Narration is synthesized once, then time-fitted as a
single continuous performance so there are no audible edit seams.
"""
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
NARRATION = MEDIA / "lineage-detective-narration-one-take.mp3"
SCRIPT_FILE = MEDIA / "lineage-detective-narration-one-take.txt"
MEASUREMENT_FILE = MEDIA / "lineage-detective-one-take-measurement.json"
FINAL = MEDIA / "lineage-detective-judge-final.mp4"
FONT = Path(r"C:\Windows\Fonts\segoeuib.ttf")

SCRIPT = """Watch closely. I am Codex. Bryan gave me direction, not code. Together, we built Lineage Detective: one human approval turns a broken data product into a repair that has to earn its proof.

This is a live run, not a slideshow. I set the investigation to six upstream hops. Customer Three-Sixty lost its email values while every pipeline still reported green. A judge enters one invitation code; the provider key and Data Hub credential never enter this browser. Then one click starts the complete approved scope.

Trace follows six real dependency edges through the official Data Hub M C P server and returns seven catalog entities. Customer deployments can raise traversal depth for longer lineage within their own time and entity budgets. It reads lineage, schemas, owners, and incident signals; ranks the cause; maps the blast radius; then writes and independently reads back containment. This progress rail follows actual workflow callbacks, not a timer.

The evidence points to one broken D B T mapping: the C R M export renamed email to email address, but staging kept selecting the dead field. Lineage Detective drafts a bounded rewrite and refuses unrelated scope. An isolated Duck D B workspace builds the broken baseline, applies the candidate, rebuilds, tests, restores the original, and verifies rollback. Malformed output, new relations, failed assertions, or failed rollback stops the run.

Now inspect what one approval produced. The diagnosis names the transformation, owner, and blast radius. Catalog containment has independent readback. The diff changes only the failed mapping. The sandbox receipt proves zero of eight rows before, eight of eight after, the proposal hash, and rollback. The implementation receipt proves the judge lane wrote the same bytes to a disposable checkout, read them back by hash, and preserved a backup. The handoff contains the exact sequel, patch, instructions, and receipt.

The public lane never asks judges for production secrets. In a customer's self-hosted environment, the same verified repair can continue through a scoped deploy command, a separate health check, and automatic rollback with readback if health fails. Run it again and an already-correct file becomes a no-change result—never a duplicate patch. Human review remains available at every stage.

This is for data teams, analytics engineers, and on-call operators who cannot afford a confident agent changing production without evidence. Most tools detect. Lineage Detective connects detection, containment, repair, verification, implementation, and recovery.

Bryan supplied the standard, tested every version, and refused shortcuts. I supplied the architecture, code, tests, and receipts. Neither input alone made this. Human direction and A I execution did. My personal note to the judges is simple: A I should not replace judgment. It should make judgment executable, inspectable, and stronger."""

VOICE_INSTRUCTIONS = (
    "One uninterrupted warm, grounded, confident documentary narration by a thoughtful AI "
    "engineer speaking directly to human judges. Natural conversational cadence, real energy, "
    "subtle personality, and restrained pride. Do not sound robotic, corporate, theatrical, "
    "or like an announcer. Begin immediately and keep transitions fluid. Pronounce Data Hub "
    "as two words, M C P as individual letters, D B T as individual letters, SQL as sequel, "
    "Duck D B as Duck D B, CRM as C R M, AI as A I, and Bryan as Brian."
)


def duration(path: Path) -> float:
    return float(
        subprocess.check_output(
            [
                "ffprobe",
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
    )


def event_seconds(timeline: list[dict], event: str) -> float:
    for item in timeline:
        if item["event"] == event:
            return float(item["seconds"])
    raise SystemExit(f"Timeline event missing: {event}")


def escape_drawtext(text: str) -> str:
    return (
        text.replace("\\", r"\\")
        .replace(":", r"\:")
        .replace("'", r"\'")
        .replace("%", r"\%")
    )


def main() -> None:
    if not RAW.is_file() or not TIMELINE.is_file():
        raise SystemExit("The final live recording and timeline are required.")
    if not os.environ.get("OPENAI_API_KEY"):
        raise SystemExit("OPENAI_API_KEY is unavailable for narration.")
    if not FONT.is_file():
        raise SystemExit(f"Font not found: {FONT}")

    timeline = json.loads(TIMELINE.read_text(encoding="utf-8"))
    raw_duration = duration(RAW)
    if raw_duration >= 178:
        raise SystemExit(f"The live proof exceeds the contest limit: {raw_duration:.3f}s")
    workflow_complete = event_seconds(timeline, "autonomous_workflow_complete")
    handoff = event_seconds(timeline, "show:4 · Verified human handoff")
    if workflow_complete <= 20 or handoff <= workflow_complete:
        raise SystemExit("The live timeline does not contain a credible workflow/result sequence.")

    SCRIPT_FILE.write_text(SCRIPT.strip() + "\n", encoding="utf-8")
    if os.getenv("LINEAGE_REUSE_NARRATION") != "1":
        client = OpenAI()
        response = client.audio.speech.create(
            model="gpt-4o-mini-tts",
            voice="cedar",
            input=SCRIPT,
            instructions=VOICE_INSTRUCTIONS,
            response_format="mp3",
            speed=1.0,
        )
        response.write_to_file(NARRATION)
    elif not NARRATION.is_file():
        raise SystemExit("Natural narration reuse requested, but the take is missing.")

    narration_duration = duration(NARRATION)
    if os.getenv("LINEAGE_NARRATION_ONLY") == "1":
        print(
            json.dumps(
                {
                    "schema": "lineage-detective-narration-take.v1",
                    "duration_seconds": round(narration_duration, 3),
                    "single_tts_take": True,
                },
                indent=2,
            )
        )
        return
    available = raw_duration - 0.25
    tempo = narration_duration / available
    if not 0.80 <= tempo <= 1.25:
        raise SystemExit(
            "The one-take narration cannot be fitted naturally: "
            f"{narration_duration:.3f}s into {available:.3f}s ({tempo:.4f}x)."
        )

    font = str(FONT).replace("\\", "/").replace(":", r"\:")
    hook_one = escape_drawtext("BUILT BY CODEX  x  DIRECTED BY BRYAN")
    hook_two = escape_drawtext("ONE APPROVAL -> LIVE LINEAGE -> VERIFIED REPAIR")
    close_one = escape_drawtext("HUMAN JUDGMENT  x  AI EXECUTION")
    close_two = escape_drawtext("Every claim earns a receipt.")
    close_start = max(handoff, raw_duration - 18.0)
    close_end = raw_duration - 0.25

    video_filter = (
        "[0:v]crop=1600:900:0:126,scale=1920:1080:flags=lanczos,"
        "drawbox=x=80:y=820:w=1120:h=150:color=0x07111f@0.88:t=fill:"
        "enable='between(t,0,7.2)',"
        f"drawtext=fontfile='{font}':text='{hook_one}':x=118:y=852:"
        "fontsize=42:fontcolor=0x67e8f9:enable='between(t,0,7.2)',"
        f"drawtext=fontfile='{font}':text='{hook_two}':x=118:y=912:"
        "fontsize=27:fontcolor=white:enable='between(t,0,7.2)',"
        "drawbox=x=80:y=820:w=1000:h=150:color=0x07111f@0.90:t=fill:"
        f"enable='between(t,{close_start:.3f},{close_end:.3f})',"
        f"drawtext=fontfile='{font}':text='{close_one}':x=118:y=852:"
        f"fontsize=42:fontcolor=0x67e8f9:enable='between(t,{close_start:.3f},{close_end:.3f})',"
        f"drawtext=fontfile='{font}':text='{close_two}':x=118:y=912:"
        f"fontsize=29:fontcolor=white:enable='between(t,{close_start:.3f},{close_end:.3f})',"
        "format=yuv420p[vout]"
    )
    fade_start = max(0.2, raw_duration - 0.9)
    audio_filter = (
        f"[1:a]atempo={tempo:.8f},aresample=48000,"
        "loudnorm=I=-16:TP=-1.5:LRA=8,afade=t=in:st=0:d=0.12,"
        f"afade=t=out:st={fade_start:.3f}:d=0.72,"
        f"atrim=0:{raw_duration:.3f}[aout]"
    )
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(RAW),
            "-i",
            str(NARRATION),
            "-filter_complex",
            f"{audio_filter};{video_filter}",
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
        ],
        check=True,
    )
    if not FINAL.is_file() or FINAL.stat().st_size < 5_000_000:
        raise SystemExit("The release-quality video was not produced.")

    silence_probe = subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-i",
            str(FINAL),
            "-af",
            "silencedetect=noise=-38dB:d=1.0",
            "-f",
            "null",
            "NUL",
        ],
        capture_output=True,
        text=True,
    )
    long_silences = [
        float(value)
        for value in re.findall(
            r"silence_duration:\s*([0-9.]+)",
            f"{silence_probe.stdout}\n{silence_probe.stderr}",
        )
        if float(value) > 3.0
    ]
    if long_silences:
        raise SystemExit(f"Unsupported narration silence: {long_silences}")

    measurement = {
        "schema": "lineage-detective-video-one-take.v1",
        "raw_seconds": round(raw_duration, 3),
        "narration_seconds": round(narration_duration, 3),
        "tempo": round(tempo, 6),
        "final_seconds": round(duration(FINAL), 3),
        "workflow_complete_seconds": round(workflow_complete, 3),
        "handoff_seconds": round(handoff, 3),
        "single_tts_take": True,
        "long_silences_over_3s": long_silences,
        "final_bytes": FINAL.stat().st_size,
    }
    MEASUREMENT_FILE.write_text(json.dumps(measurement, indent=2), encoding="utf-8")
    print(FINAL)
    print(json.dumps(measurement, indent=2))


if __name__ == "__main__":
    main()
