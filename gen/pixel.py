"""Pixel sprites: character-map sources rendered to images, and images traced back to maps.

A sprite lives in sprites/<slug>/sprite.yaml and holds a fixed palette plus one or more
named frames. Each frame is a square block of characters, one character per pixel, so a
sprite is plain text: diffable, reviewable, and editable one pixel at a time.

Rendering is deterministic. Nothing here calls a model. `trace` exists so that art from
somewhere else (a generator, a drawing app) can be converted into an editable map and then
corrected by hand, which keeps the sprite source the single source of truth.
"""

import logging
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import yaml
from PIL import Image

log = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent
SPRITES_DIR = REPO_ROOT / "sprites"
OUTPUT_DIR = REPO_ROOT / "output"

TRANSPARENT = "."


@dataclass
class Sprite:
    """A pixel sprite: a fixed palette plus named square frames of characters."""

    name: str
    size: int
    palette: dict[str, str]
    frames: dict[str, list[str]]
    source: Path | None = None

    def frame(self, name: str | None = None) -> list[str]:
        """Return a frame's rows. Defaults to the first frame defined."""
        if not self.frames:
            raise ValueError(f"Sprite '{self.name}' has no frames")
        if name is None:
            return next(iter(self.frames.values()))
        if name not in self.frames:
            available = ", ".join(self.frames)
            raise KeyError(f"Frame '{name}' not in sprite '{self.name}'. Available: {available}")
        return self.frames[name]

    @property
    def frame_names(self) -> list[str]:
        return list(self.frames)


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    h = str(value).lstrip("#").strip()
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    if len(h) != 6:
        raise ValueError(f"Invalid hex color: {value!r}")
    try:
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
    except ValueError:
        raise ValueError(f"Invalid hex color: {value!r}") from None


def _rgb_to_hex(rgb) -> str:
    return "#{:02X}{:02X}{:02X}".format(*(int(c) for c in rgb))


def validate_frame(rows: list[str], size: int, palette: dict[str, str], label: str = "frame"):
    """Raise ValueError if a frame is not a square grid using only known characters."""
    if len(rows) != size:
        raise ValueError(f"{label}: expected {size} rows, got {len(rows)}")
    bad_width = [(i, len(r)) for i, r in enumerate(rows) if len(r) != size]
    if bad_width:
        detail = ", ".join(f"row {i} has {w}" for i, w in bad_width[:5])
        raise ValueError(f"{label}: every row must be {size} chars ({detail})")
    known = set(palette) | {TRANSPARENT}
    stray = sorted({c for r in rows for c in r} - known)
    if stray:
        raise ValueError(f"{label}: characters not in palette: {''.join(stray)}")


def load_sprite(ref: str | Path) -> Sprite:
    """Load a sprite by slug (sprites/<slug>/sprite.yaml) or by explicit path."""
    path = Path(ref)
    if not path.suffix:
        path = SPRITES_DIR / str(ref) / "sprite.yaml"
    if not path.exists():
        raise FileNotFoundError(f"Sprite not found: {path}")

    data = yaml.safe_load(path.read_text())
    if not isinstance(data, dict):
        raise ValueError(f"Sprite file must be a YAML mapping: {path}")

    for key in ("size", "palette", "frames"):
        if key not in data:
            raise ValueError(f"Sprite {path} is missing required key: {key}")

    size = int(data["size"])
    palette = {str(k): str(v) for k, v in data["palette"].items()}
    for char, color in palette.items():
        if len(char) != 1:
            raise ValueError(f"Palette keys must be single characters, got {char!r}")
        if char == TRANSPARENT:
            raise ValueError(f"'{TRANSPARENT}' is reserved for transparency and cannot be mapped")
        _hex_to_rgb(color)

    frames: dict[str, list[str]] = {}
    for frame_name, block in data["frames"].items():
        rows = [ln for ln in str(block).splitlines() if ln.strip()]
        validate_frame(rows, size, palette, label=f"{path.name}:{frame_name}")
        frames[str(frame_name)] = rows

    return Sprite(
        name=str(data.get("name", path.parent.name)),
        size=size,
        palette=palette,
        frames=frames,
        source=path,
    )


def save_sprite(sprite: Sprite, path: str | Path) -> Path:
    """Write a sprite back out as YAML with frames as readable text blocks."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    lines = [f"name: {sprite.name}", f"size: {sprite.size}", "", "palette:"]
    lines += [f'  "{c}": "{h}"' for c, h in sprite.palette.items()]
    lines += ["", "frames:"]
    for frame_name, rows in sprite.frames.items():
        lines.append(f"  {frame_name}: |")
        lines += [f"    {r}" for r in rows]
        lines.append("")

    path.write_text("\n".join(lines).rstrip() + "\n")
    return path


def frame_to_image(
    sprite: Sprite,
    frame: str | None = None,
    scale: int = 1,
    background: str | None = None,
) -> Image.Image:
    """Render one frame to a PIL image, upscaled by nearest neighbour."""
    rows = sprite.frame(frame)
    n = sprite.size
    arr = np.zeros((n, n, 4), dtype=np.uint8)
    if background:
        arr[:, :, :3] = _hex_to_rgb(background)
        arr[:, :, 3] = 255

    lut = {c: _hex_to_rgb(h) for c, h in sprite.palette.items()}
    for y, row in enumerate(rows):
        for x, char in enumerate(row):
            if char == TRANSPARENT:
                continue
            arr[y, x, :3] = lut[char]
            arr[y, x, 3] = 255

    img = Image.fromarray(arr, "RGBA")
    if scale != 1:
        if scale < 1:
            raise ValueError(f"scale must be >= 1, got {scale}")
        img = img.resize((n * scale, n * scale), Image.Resampling.NEAREST)
    return img


def frame_to_svg(
    sprite: Sprite,
    frame: str | None = None,
    scale: int = 8,
    background: str | None = None,
) -> str:
    """Render one frame to SVG, merging horizontal runs into single rects.

    Useful for embedding a sprite in a web page where it must stay crisp at any size.
    """
    rows = sprite.frame(frame)
    n = sprite.size
    parts = []
    if background:
        parts.append(f'<rect width="{n}" height="{n}" fill="{background}"/>')

    for y, row in enumerate(rows):
        x = 0
        while x < n:
            char = row[x]
            if char == TRANSPARENT:
                x += 1
                continue
            run = 1
            while x + run < n and row[x + run] == char:
                run += 1
            parts.append(
                f'<rect x="{x}" y="{y}" width="{run}" height="1" fill="{sprite.palette[char]}"/>'
            )
            x += run

    px = n * scale
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {n} {n}" '
        f'width="{px}" height="{px}" shape-rendering="crispEdges">' + "".join(parts) + "</svg>"
    )


def contact_sheet(
    sprite: Sprite,
    scale: int = 4,
    columns: int = 4,
    gap: int = 8,
    background: str = "#F7F3EC",
) -> Image.Image:
    """Lay every frame out in a grid, so a whole sprite can be reviewed in one look."""
    names = sprite.frame_names
    if not names:
        raise ValueError(f"Sprite '{sprite.name}' has no frames")

    cell = sprite.size * scale
    cols = max(1, min(columns, len(names)))
    rows_n = (len(names) + cols - 1) // cols
    width = cols * cell + (cols + 1) * gap
    height = rows_n * cell + (rows_n + 1) * gap

    sheet = Image.new("RGB", (width, height), _hex_to_rgb(background))
    for i, name in enumerate(names):
        tile = frame_to_image(sprite, name, scale=scale, background=background)
        col, row = i % cols, i // cols
        x = gap + col * (cell + gap)
        y = gap + row * (cell + gap)
        sheet.paste(tile.convert("RGB"), (x, y))
    return sheet


def snap_to_grid(img: Image.Image, size: int) -> Image.Image:
    """Downsample to size x size by taking the most common colour in each cell.

    Averaging muddies pixel art; the dominant colour keeps flat regions flat.
    """
    if size < 1:
        raise ValueError(f"size must be >= 1, got {size}")
    arr = np.asarray(img.convert("RGB"))
    h, w = arr.shape[:2]
    out = np.zeros((size, size, 3), dtype=np.uint8)

    for gy in range(size):
        y0 = gy * h // size
        y1 = max((gy + 1) * h // size, y0 + 1)
        for gx in range(size):
            x0 = gx * w // size
            x1 = max((gx + 1) * w // size, x0 + 1)
            cell = arr[y0:y1, x0:x1].reshape(-1, 3)
            colors, counts = np.unique(cell, axis=0, return_counts=True)
            out[gy, gx] = colors[counts.argmax()]

    return Image.fromarray(out, "RGB")


def quantize_to_palette(img: Image.Image, colors: list[str]) -> Image.Image:
    """Map every pixel to its nearest colour from an exact palette, with no dithering.

    Pillow's own quantize picks its own palette; this forces the one you specify.
    """
    if not colors:
        raise ValueError("palette must contain at least one colour")
    pal = np.array([_hex_to_rgb(c) for c in colors], dtype=np.int32)
    arr = np.asarray(img.convert("RGB"), dtype=np.int32)
    h, w = arr.shape[:2]
    dist = ((arr.reshape(-1, 1, 3) - pal[None, :, :]) ** 2).sum(axis=2)
    out = pal[dist.argmin(axis=1)].reshape(h, w, 3).astype(np.uint8)
    return Image.fromarray(out, "RGB")


def trace(
    image_path: str | Path,
    size: int,
    palette: dict[str, str],
    alpha_threshold: int = 128,
    background: str | None = None,
) -> list[str]:
    """Convert an image into a character map using a fixed palette.

    Cells below `alpha_threshold` become '.'. If `background` is given it competes with the
    palette and the nearest colour wins, so a cell only becomes transparent when the
    background is a better match than any palette entry. A plain distance threshold does not
    work here: pure white sits close enough to a cream background to be swallowed by it.

    This is the bridge that turns art made elsewhere into an editable sprite frame.
    """
    path = Path(image_path)
    if not path.exists():
        raise FileNotFoundError(f"Image not found: {path}")

    img = Image.open(path).convert("RGBA")
    alpha = Image.fromarray(np.asarray(img)[:, :, 3], "L")
    small_alpha = np.asarray(alpha.resize((size, size), Image.Resampling.BOX))
    small = np.asarray(snap_to_grid(img.convert("RGB"), size), dtype=np.int32)

    chars = list(palette)
    candidates = np.array([_hex_to_rgb(palette[c]) for c in chars], dtype=np.int32)
    if background:
        candidates = np.vstack([candidates, np.array(_hex_to_rgb(background), dtype=np.int32)])

    rows = []
    for y in range(size):
        row = []
        for x in range(size):
            if small_alpha[y, x] < alpha_threshold:
                row.append(TRANSPARENT)
                continue
            nearest = int(((small[y, x] - candidates) ** 2).sum(axis=1).argmin())
            row.append(TRANSPARENT if nearest >= len(chars) else chars[nearest])
        rows.append("".join(row))
    return rows


def palette_from_image(image_path: str | Path, max_colors: int = 8) -> dict[str, str]:
    """Suggest a palette from an image, most common colours first.

    Characters are assigned from a readable alphabet so the map stays legible.
    """
    alphabet = "owgpdlkbrymc"
    arr = np.asarray(Image.open(image_path).convert("RGB")).reshape(-1, 3)
    colors, counts = np.unique(arr, axis=0, return_counts=True)
    order = counts.argsort()[::-1][:max_colors]
    return {alphabet[i]: _rgb_to_hex(colors[c]) for i, c in enumerate(order)}


def render_sprite(
    ref: str | Path,
    frame: str | None = None,
    scale: int = 8,
    background: str | None = None,
    output_name: str | None = None,
    svg: bool = False,
) -> Path:
    """Full pipeline: load a sprite, render one frame, write it to output/."""
    sprite = load_sprite(ref)
    frame_name = frame or sprite.frame_names[0]

    if output_name is None:
        ext = "svg" if svg else "png"
        output_name = f"{sprite.name}-{frame_name}.{ext}"

    out = OUTPUT_DIR / output_name
    out.parent.mkdir(parents=True, exist_ok=True)

    if svg:
        out.write_text(frame_to_svg(sprite, frame_name, scale=scale, background=background))
    else:
        frame_to_image(sprite, frame_name, scale=scale, background=background).save(out)

    log.debug("Rendered %s frame '%s' at %dx", sprite.name, frame_name, scale)
    return out
