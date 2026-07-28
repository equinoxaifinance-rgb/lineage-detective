"""Build the deterministic 3:2 Devpost cover from the shipped Trace mascot."""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "assets" / "lineage-detective-devpost-thumbnail.png"
MASCOT = ROOT / "assets" / "lineage-detective-mascot.png"


def font(name: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(Path(r"C:\Windows\Fonts") / name), size)


def gradient(width: int, height: int) -> Image.Image:
    image = Image.new("RGB", (width, height))
    pixels = image.load()
    for y in range(height):
        for x in range(width):
            mix = (x / width) * 0.32 + (y / height) * 0.15
            pixels[x, y] = (
                int(4 + 8 * mix),
                int(14 + 25 * mix),
                int(28 + 45 * mix),
            )
    return image


def main() -> None:
    width, height = 1200, 800
    canvas = gradient(width, height)
    draw = ImageDraw.Draw(canvas, "RGBA")

    for x in range(0, width, 48):
        draw.line((x, 0, x, height), fill=(34, 211, 238, 14), width=1)
    for y in range(0, height, 48):
        draw.line((0, y, width, y), fill=(34, 211, 238, 14), width=1)

    glow = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    glow_draw = ImageDraw.Draw(glow, "RGBA")
    glow_draw.ellipse((720, 70, 1250, 650), fill=(6, 182, 212, 110))
    glow_draw.ellipse((870, 210, 1220, 620), fill=(37, 99, 235, 100))
    glow = glow.filter(ImageFilter.GaussianBlur(95))
    canvas = Image.alpha_composite(canvas.convert("RGBA"), glow).convert("RGB")
    draw = ImageDraw.Draw(canvas, "RGBA")

    draw.rounded_rectangle(
        (54, 52, 1146, 748),
        radius=34,
        fill=(3, 12, 26, 188),
        outline=(103, 232, 249, 72),
        width=2,
    )
    draw.rounded_rectangle(
        (82, 78, 360, 120),
        radius=21,
        fill=(8, 145, 178, 54),
        outline=(103, 232, 249, 120),
        width=1,
    )
    draw.text((104, 89), "DATA INCIDENT RESPONSE AGENT", font=font("consolab.ttf", 17), fill=(165, 243, 252))

    title = font("seguisb.ttf", 76)
    draw.text((88, 168), "LINEAGE", font=title, fill=(248, 250, 252))
    draw.text((88, 245), "DETECTIVE", font=title, fill=(103, 232, 249))
    draw.text(
        (92, 354),
        "From a broken dashboard",
        font=font("seguisb.ttf", 31),
        fill=(226, 232, 240),
    )
    draw.text(
        (92, 397),
        "to a verified repair.",
        font=font("seguisb.ttf", 31),
        fill=(251, 191, 36),
    )

    trail_y = 500
    labels = ("EVIDENCE", "DIAGNOSIS", "REPAIR", "VERIFIED")
    colors = ((34, 211, 238), (96, 165, 250), (167, 139, 250), (134, 239, 172))
    x = 92
    for index, (label, color) in enumerate(zip(labels, colors)):
        box = draw.textbbox((0, 0), label, font=font("consolab.ttf", 17))
        box_width = box[2] - box[0] + 28
        draw.rounded_rectangle(
            (x, trail_y, x + box_width, trail_y + 40),
            radius=20,
            fill=(6, 18, 34, 255),
            outline=(*color, 145),
            width=1,
        )
        draw.text((x + 14, trail_y + 10), label, font=font("consolab.ttf", 17), fill=(*color, 255))
        x += box_width
        if index < len(labels) - 1:
            draw.text((x + 8, trail_y + 8), "→", font=font("seguisb.ttf", 20), fill=(148, 163, 184))
            x += 39

    draw.text(
        (92, 585),
        "Live DataHub MCP  •  controlled writeback",
        font=font("segoeui.ttf", 23),
        fill=(191, 211, 233),
    )
    draw.text(
        (92, 620),
        "sandbox proof  •  exact-byte handoff",
        font=font("segoeui.ttf", 23),
        fill=(191, 211, 233),
    )

    mascot = Image.open(MASCOT).convert("RGBA")
    mascot.thumbnail((435, 435), Image.Resampling.LANCZOS)
    shadow = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    shadow_alpha = mascot.getchannel("A").filter(ImageFilter.GaussianBlur(22))
    shadow_mask = Image.new("RGBA", mascot.size, (0, 0, 0, 180))
    shadow_mask.putalpha(shadow_alpha)
    mascot_x = 714 + (435 - mascot.width) // 2
    mascot_y = 182 + (435 - mascot.height) // 2
    shadow.alpha_composite(shadow_mask, (mascot_x + 8, mascot_y + 20))
    canvas = Image.alpha_composite(canvas.convert("RGBA"), shadow)
    canvas.alpha_composite(mascot, (mascot_x, mascot_y))

    draw = ImageDraw.Draw(canvas, "RGBA")
    draw.rounded_rectangle(
        (790, 644, 1088, 700),
        radius=28,
        fill=(5, 46, 22, 205),
        outline=(134, 239, 172, 180),
        width=2,
    )
    draw.ellipse((812, 664, 826, 678), fill=(134, 239, 172))
    draw.text((842, 659), "RECEIPT VERIFIED", font=font("consolab.ttf", 19), fill=(187, 247, 208))

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    canvas.convert("RGB").save(OUTPUT, "PNG", optimize=True)
    print(OUTPUT)


if __name__ == "__main__":
    main()
