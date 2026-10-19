"""Compose a contact sheet from the already-rendered slide previews (review-only, no redesign)."""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).resolve().parents[1]
PREVIEWS = OUT / "output" / "previews"
FONT = "/usr/share/fonts/liberation-sans/LiberationSans-Bold.ttf"

SLIDES = [
    ("01-title", "1 — CryoStack (title)"),
    ("02-challenge", "2 — The challenge is bigger than the model"),
    ("03-introducing", "3 — Introducing CryoStack"),
    ("04-applications", "4 — One platform, different workflows"),
    ("05-architecture", "5 — Browser to compute"),
    ("06-real-science", "6 — Already running real science"),
    ("07-reproducibility", "7 — Experiment lifecycle"),
    ("08-live", "8 — CryoStack is live"),
    ("09-demo", "9 — See CryoStack in action"),
]

COLS, ROWS = 3, 3
THUMB_W, THUMB_H = 800, 450
LABEL_H = 50
PAD, MARGIN = 30, 40

canvas_w = MARGIN * 2 + THUMB_W * COLS + PAD * (COLS - 1)
canvas_h = MARGIN * 2 + (THUMB_H + LABEL_H) * ROWS + PAD * (ROWS - 1)
canvas = Image.new("RGB", (canvas_w, canvas_h), (255, 255, 255))
draw = ImageDraw.Draw(canvas)
font = ImageFont.truetype(FONT, 30)

for i, (name, label) in enumerate(SLIDES):
    col, row = i % COLS, i // COLS
    x = MARGIN + col * (THUMB_W + PAD)
    y = MARGIN + row * (THUMB_H + LABEL_H + PAD)
    im = Image.open(PREVIEWS / f"{name}.png").convert("RGB").resize((THUMB_W, THUMB_H), Image.LANCZOS)
    canvas.paste(im, (x, y))
    draw.rectangle([x, y, x + THUMB_W - 1, y + THUMB_H - 1], outline=(180, 190, 200), width=2)
    draw.text((x, y + THUMB_H + 8), label, font=font, fill=(23, 32, 51))

out_path = OUT / "output" / "CryoStack_Contact_Sheet.png"
canvas.save(out_path)
print("saved", out_path, canvas.size)
