"""Add natural narration and restrained live-video titles to the judge recording."""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from openai import OpenAI


ROOT = Path(__file__).resolve().parents[1]
MEDIA = ROOT / "vid" / "judge-final"
RAW = MEDIA / "lineage-detective-live-raw.mp4"
FINAL = MEDIA / "lineage-detective-judge-candidate.mp4"
SCRIPT_FILE = MEDIA / "lineage-detective-narration.json"
FONT = Path(r"C:\Windows\Fonts\segoeuib.ttf")
FFMPEG = "ffmpeg"
FFPROBE = "ffprobe"

VOICE_INSTRUCTIONS = (
    "Warm, grounded, confident documentary narration from a thoughtful AI engineer speaking "
    "directly to human judges. Natural conversational cadence, varied pacing, and restrained "
    "excitement. Never sound like an announcer or a corporate training video. Use brief natural "
    "pauses around important evidence. Pronounce Data Hub as two words, M C P as individual "
    "letters, D B T as individual letters, SQL as sequel, and Bryan as Brian."
)

# Starts match observed events from lineage-detective-live-timeline.json. Each clip is
# generated independently so the spoken claim stays synchronized with the real action.
SEGMENTS = [
    {
        "name": "01_hook",
        "start": 0.10,
        "max": 6.65,
        "text": (
            "I'm Codex. Bryan gave me the direction; I built this agent. "
            "Now I'm going to prove it, live."
        ),
    },
    {
        "name": "02_investigate",
        "start": 7.40,
        "max": 36.80,
        "text": (
            "A data incident starts with one ugly symptom: Customer Three-Sixty lost its email "
            "values, but every pipeline still says success. I click Investigate once. Lineage "
            "Detective connects to the official Data Hub M C P server, walks the real upstream "
            "graph, and reads schemas, ownership, and incident metadata. The model can reason over "
            "those facts, but it cannot invent them. Watch the droid's status: those phases are "
            "callbacks from the actual connection, evidence, reasoning, containment, and readback "
            "path. When it writes quarantine and impact tags, the app reads them back before it "
            "uses the word confirmed."
        ),
    },
    {
        "name": "03_diagnosis",
        "start": 46.35,
        "max": 8.85,
        "text": (
            "The live lineage exposes the break: the C R M export renamed email to email-address, "
            "while the staging model kept reading the dead field."
        ),
    },
    {
        "name": "04_diff",
        "start": 55.50,
        "max": 11.80,
        "text": (
            "The agent contains the bad node, maps two downstream assets, names the owner, and "
            "drafts one constrained rewrite. The exact diff and its hash are visible before "
            "anything executes."
        ),
    },
    {
        "name": "05_sandbox",
        "start": 68.55,
        "max": 35.90,
        "text": (
            "Approval is the click you just saw. Now the exact displayed bytes enter a disposable "
            "D B T and Duck D B sandbox. This is not a spinner hiding a shortcut. It resets a known "
            "broken model, loads representative rows, builds the failing baseline, applies the "
            "approved sequel, rebuilds it, measures the assertion, and restores the original model. "
            "A timeout or failed check stops the claim. The repair only advances if the real "
            "assertion flips from fail to pass and rollback is independently verified."
        ),
    },
    {
        "name": "06_receipt",
        "start": 104.20,
        "max": 12.40,
        "text": (
            "Here is the receipt: zero of eight before, eight of eight after, and rollback "
            "confirmed. The human now chooses implementation or a complete evidence handoff."
        ),
    },
    {
        "name": "07_apply_restore",
        "start": 117.25,
        "max": 15.45,
        "text": (
            "I apply the hash-bound rewrite to a real checked-out sequel file. The app creates a "
            "sibling backup and reads the written bytes back. Then I restore it, and the original "
            "hash returns. No theater; both directions are verified."
        ),
    },
    {
        "name": "08_personal",
        "start": 132.00,
        "max": 11.55,
        "text": (
            "Bryan supplied the judgment. I supplied the code, tests, and this proof. "
            "Human direction plus A I execution made Lineage Detective real."
        ),
    },
]


def run(*args: str) -> None:
    subprocess.run(args, check=True)


def duration(path: Path) -> float:
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


def escape_drawtext(text: str) -> str:
    return (
        text.replace("\\", r"\\")
        .replace(":", r"\:")
        .replace("'", r"\'")
        .replace("%", r"\%")
    )


def main() -> None:
    if not RAW.is_file():
        raise SystemExit(f"Missing live recording: {RAW}")
    if not os.environ.get("OPENAI_API_KEY"):
        raise SystemExit("OPENAI_API_KEY is not available.")
    if not FONT.is_file():
        raise SystemExit(f"Font not found: {FONT}")

    SCRIPT_FILE.write_text(json.dumps(SEGMENTS, indent=2), encoding="utf-8")
    client = OpenAI()
    inputs: list[Path] = []
    measured: list[dict] = []
    for segment in SEGMENTS:
        wav = MEDIA / f"{segment['name']}.wav"
        if not wav.is_file():
            response = client.audio.speech.create(
                model="gpt-4o-mini-tts",
                voice="cedar",
                input=segment["text"],
                instructions=VOICE_INSTRUCTIONS,
                response_format="wav",
            )
            response.write_to_file(wav)
        clip_duration = duration(wav)
        inputs.append(wav)
        measured.append(
            {
                "name": segment["name"],
                "start": segment["start"],
                "max": segment["max"],
                "generated_seconds": round(clip_duration, 3),
                "tempo": round(max(1.0, clip_duration / segment["max"]), 5),
            }
        )
    (MEDIA / "narration-measurements.json").write_text(
        json.dumps(measured, indent=2), encoding="utf-8"
    )

    command = [FFMPEG, "-y", "-i", str(RAW)]
    for wav in inputs:
        command.extend(["-i", str(wav)])

    audio_chains: list[str] = []
    for index, (segment, measurement) in enumerate(zip(SEGMENTS, measured), start=1):
        tempo = measurement["tempo"]
        delay = int(round(segment["start"] * 1000))
        transform = f"atempo={tempo}" if tempo > 1.00001 else "anull"
        audio_chains.append(
            f"[{index}:a]{transform},aresample=48000,adelay={delay}|{delay}[a{index}]"
        )
    mix_inputs = "".join(f"[a{i}]" for i in range(1, len(inputs) + 1))
    audio_chains.append(
        f"{mix_inputs}amix=inputs={len(inputs)}:duration=longest:dropout_transition=0,"
        "loudnorm=I=-16:TP=-1.5:LRA=8,afade=t=in:st=0:d=0.18,"
        "afade=t=out:st=144.55:d=0.75,atrim=0:145.35[aout]"
    )

    font = str(FONT).replace("\\", "/").replace(":", r"\:")
    hook_one = escape_drawtext("BUILT BY CODEX  ×  DIRECTED BY BRYAN")
    hook_two = escape_drawtext("LIVE DATAHUB INVESTIGATION → VERIFIED REPAIR")
    close_one = escape_drawtext("HUMAN JUDGMENT  ×  AI EXECUTION")
    close_two = escape_drawtext("Every claim earned by a receipt.")
    video_filter = (
        "[0:v]crop=1600:900:0:126,scale=1920:1080:flags=lanczos,"
        "drawbox=x=80:y=820:w=980:h=150:color=0x07111f@0.88:t=fill:"
        "enable='between(t,0,6.8)',"
        f"drawtext=fontfile='{font}':text='{hook_one}':x=118:y=852:"
        "fontsize=42:fontcolor=0x67e8f9:enable='between(t,0,6.8)',"
        f"drawtext=fontfile='{font}':text='{hook_two}':x=118:y=912:"
        "fontsize=27:fontcolor=white:enable='between(t,0,6.8)',"
        "drawbox=x=80:y=820:w=900:h=150:color=0x07111f@0.90:t=fill:"
        "enable='between(t,131.8,142.5)',"
        f"drawtext=fontfile='{font}':text='{close_one}':x=118:y=852:"
        "fontsize=42:fontcolor=0x67e8f9:enable='between(t,131.8,142.5)',"
        f"drawtext=fontfile='{font}':text='{close_two}':x=118:y=912:"
        "fontsize=29:fontcolor=white:enable='between(t,131.8,142.5)',"
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
            "145.35",
            str(FINAL),
        ]
    )
    run(*command)
    if not FINAL.is_file() or FINAL.stat().st_size < 5_000_000:
        raise SystemExit("The final judge video was not produced at release quality.")
    print(FINAL)
    print(json.dumps(measured, indent=2))


if __name__ == "__main__":
    main()
