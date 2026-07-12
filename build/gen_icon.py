"""Genera build/icon.ico para ITVLocal (llave inglesa + check sobre navy)."""

from pathlib import Path
from PIL import Image, ImageDraw

NAVY = (30, 58, 95, 255)
NAVY2 = (21, 48, 77, 255)
TERRA = (206, 110, 97, 255)
GREEN = (22, 163, 74, 255)
WHITE = (255, 255, 255, 255)


def make(size: int) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    r = int(size * 0.22)
    d.rounded_rectangle([0, 0, size - 1, size - 1], radius=r, fill=NAVY)
    d.rounded_rectangle([0, int(size * 0.5), size - 1, size - 1], radius=r, fill=NAVY2)
    # esfera tipo "nota de la ITV" (dial)
    cx, cy = int(size * 0.5), int(size * 0.52)
    rad = int(size * 0.30)
    d.ellipse([cx - rad, cy - rad, cx + rad, cy + rad], outline=WHITE,
              width=max(2, size // 26))
    d.pieslice([cx - rad + 4, cy - rad + 4, cx + rad - 4, cy + rad - 4],
               start=150, end=300, fill=TERRA)
    # aguja del dial
    d.line([cx, cy, int(cx + rad * 0.62), int(cy - rad * 0.55)], fill=WHITE,
           width=max(2, size // 22))
    d.ellipse([cx - size // 24, cy - size // 24, cx + size // 24, cy + size // 24], fill=WHITE)
    # check de aprobado
    ck = int(size * 0.16)
    ox, oy = int(size * 0.66), int(size * 0.70)
    d.line([ox, oy + ck // 2, ox + ck // 2, oy + ck], fill=GREEN, width=max(3, size // 16))
    d.line([ox + ck // 2, oy + ck, ox + ck + ck // 3, oy], fill=GREEN, width=max(3, size // 16))
    return img


def main() -> None:
    out = Path(__file__).resolve().parent / "icon.ico"
    sizes = [16, 24, 32, 48, 64, 128, 256]
    imgs = [make(s) for s in sizes]
    imgs[-1].save(out, format="ICO", sizes=[(s, s) for s in sizes])
    make(256).save(out.with_name("icon_preview.png"))
    print("icono ->", out)


if __name__ == "__main__":
    main()
