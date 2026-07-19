"""make_video.py — compose the demo video from REAL captured UI frames + AI narration.
Streams frames to the encoder (no giant in-memory list), muxes narration with the bundled ffmpeg.
Output: vid/lineage_detective_demo.mp4
"""
import os, subprocess
from PIL import Image, ImageDraw, ImageFont
import numpy as np, imageio.v2 as imageio
from mutagen.mp3 import MP3
import imageio_ffmpeg
from openai import OpenAI

W, H, FPS = 1280, 720, 24
os.makedirs("vid", exist_ok=True)

SEGS = [
    ("s1_intro", "When a dashboard breaks, data teams lose hours on one question: where did this go wrong? "
                 "Lineage Detective answers it autonomously — and it works entirely through DataHub's official MCP Server."),
    ("s1b_mcp", "Every fact the agent reads and every action it takes goes through DataHub's MCP Server: "
                "get lineage and get entities to investigate, add tags to act — and each write is read back to confirm it stuck."),
    ("s2_a", "Describe the symptom in plain English: revenue dropped forty percent, no errors. "
             "The agent walks DataHub's lineage upstream through the MCP get-lineage tool, reads the real metadata at every step, and pinpoints the cause: "
             "the raw orders table, a silent partial load, at high confidence, with the owner to contact. "
             "Then it acts — quarantining that node through the MCP add-tags tool, and mapping the full blast radius, tagging every downstream table and dashboard the bad data touched."),
    ("s3_b", "It's no one-trick script. A schema change that nulled customer emails? Traced to the source through the same MCP tools, and contained."),
    ("s4_c", "A stale exchange-rate feed freezing revenue? Same story. Found, and quarantined."),
    ("s5_close", "Diagnose. Contain. Map the damage. Autonomously, through DataHub's MCP Server, in the catalog your team already uses. Lineage Detective."),
]

# ---- 1. narration (cache) --------------------------------------------------------
client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
durs = {}
for name, text in SEGS:
    mp3 = f"vid/{name}.mp3"
    if not os.path.exists(mp3):
        client.audio.speech.create(model="tts-1", voice="onyx", input=text).stream_to_file(mp3)
    durs[name] = MP3(mp3).info.length
print("narration durations:", {k: round(v, 1) for k, v in durs.items()}, "total", round(sum(durs.values()), 1), "s")


def font(sz, bold=False):
    for f in (("segoeuib.ttf" if bold else "segoeui.ttf"), "arial.ttf"):
        try:
            return ImageFont.truetype("C:/Windows/Fonts/" + f, sz)
        except Exception:
            pass
    return ImageFont.load_default()


def _center(d, y, text, fnt, fill):
    w = d.textbbox((0, 0), text, font=fnt)[2]
    d.text(((W - w) // 2, y), text, font=fnt, fill=fill)


def card_frame(title, sub, accent=(34, 197, 94)):
    img = Image.new("RGB", (W, H), (15, 23, 42))
    d = ImageDraw.Draw(img)
    _center(d, 250, title, font(64, True), (241, 245, 249))
    _center(d, 350, sub, font(30), (148, 163, 184))
    d.rectangle([(W // 2 - 90, 430), (W // 2 + 90, 436)], fill=accent)
    return np.array(img)


def load_ui(path):
    im = Image.open(path).convert("RGB")
    if im.width != W:
        im = im.resize((W, int(im.height * W / im.width)))
    return np.array(im)


def write_segment(writer, kind, dur, **kw):
    n = max(1, int(dur * FPS))
    if kind == "card":
        frame = card_frame(kw["title"], kw["sub"], kw.get("accent", (34, 197, 94)))
        for _ in range(n):
            writer.append_data(frame)
    else:  # scroll a tall UI capture top->bottom
        arr = kw["arr"]
        ih = arr.shape[0]
        maxoff = max(0, ih - H)
        hold = int(0.10 * n)  # brief hold on top before scrolling
        for i in range(n):
            prog = 0 if i < hold else (i - hold) / max(1, (n - hold - 1))
            y = int(maxoff * min(1.0, prog))
            crop = arr[y:y + H, 0:W]
            if crop.shape[0] < H:
                pad = np.zeros((H, W, 3), dtype="uint8"); pad[:crop.shape[0]] = crop; crop = pad
            writer.append_data(crop)


# ---- 2. stream frames to a silent video ------------------------------------------
a_arr = load_ui("cap/01_A_revenue.png")
b_arr = load_ui("cap/02_B_customer.png")
c_arr = load_ui("cap/03_C_finance.png")

wr = imageio.get_writer("vid/silent.mp4", fps=FPS, codec="libx264", macro_block_size=1, quality=8)
write_segment(wr, "card", durs["s1_intro"], title="Lineage Detective",
              sub="Autonomous data-incident root cause  ·  via the DataHub MCP Server")
write_segment(wr, "card", durs["s1b_mcp"], title="DataHub MCP Server",
              sub="get_lineage   ·   get_entities   ·   add_tags", accent=(59, 130, 246))
write_segment(wr, "scroll", durs["s2_a"], arr=a_arr)
write_segment(wr, "scroll", durs["s3_b"], arr=b_arr)
write_segment(wr, "scroll", durs["s4_c"], arr=c_arr)
write_segment(wr, "card", durs["s5_close"], title="Built by AI.  Built with DataHub.",
              sub="Diagnose  ->  Contain  ->  Map the blast radius", accent=(59, 130, 246))
wr.close()
print("silent video written")

# ---- 3. mux narration (concat mp3s, then attach) ---------------------------------
ff = imageio_ffmpeg.get_ffmpeg_exe()
with open("vid/audio_list.txt", "w") as f:
    for name, _ in SEGS:
        f.write(f"file '{name}.mp3'\n")
subprocess.run([ff, "-y", "-f", "concat", "-safe", "0", "-i", "audio_list.txt", "-c", "copy", "narration.mp3"],
               cwd="vid", check=True, capture_output=True)
subprocess.run([ff, "-y", "-i", "vid/silent.mp4", "-i", "vid/narration.mp3",
                "-c:v", "copy", "-c:a", "aac", "-shortest", "vid/lineage_detective_demo.mp4"],
               check=True, capture_output=True)
sz = os.path.getsize("vid/lineage_detective_demo.mp4")
print(f"DONE: vid/lineage_detective_demo.mp4  ({sz} bytes, ~{round(sum(durs.values()),1)}s)")
