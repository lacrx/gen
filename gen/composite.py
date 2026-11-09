"""Composite photos into placeholder regions of an existing design."""

import logging
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

log = logging.getLogger(__name__)


def load_base(path: Path, dpi: int = 300) -> Image.Image:
    """Load a base image from a PNG/JPG or render a PDF page to an image."""
    path = Path(path)
    if path.suffix.lower() == ".pdf":
        import pymupdf

        doc = pymupdf.open(str(path))
        page = doc[0]
        pix = page.get_pixmap(dpi=dpi)
        data = pix.samples
        img = Image.frombytes("RGB", (pix.width, pix.height), data)
        doc.close()
        return img
    return Image.open(path).convert("RGB")


def detect_placeholders(
    img: Image.Image,
    color: tuple[int, int, int] | None = None,
    tolerance: int = 60,
    min_area_frac: float = 0.01,
) -> list[tuple[int, int, int, int]]:
    """Find rectangular placeholder regions in an image.

    If `color` is given (R, G, B), regions matching that color within `tolerance`
    are detected. Otherwise, regions are detected by finding large contiguous
    areas that differ from the dominant background color.

    Returns a list of (x1, y1, x2, y2) bounding boxes sorted by area descending.
    """
    arr = np.array(img)
    h, w = arr.shape[:2]
    total_pixels = h * w

    if color is not None:
        target = np.array(color, dtype=np.float32)
        diff = np.sqrt(((arr.astype(np.float32) - target) ** 2).sum(axis=2))
        mask = diff < tolerance
    else:
        mask = _detect_non_background(arr, tolerance)

    return _extract_boxes(mask, min_area_frac, total_pixels)


def _detect_non_background(arr: np.ndarray, tolerance: int) -> np.ndarray:
    """Detect regions that differ from the dominant (background) color."""
    h, w = arr.shape[:2]

    edges = np.concatenate([
        arr[0, :, :],
        arr[-1, :, :],
        arr[:, 0, :],
        arr[:, -1, :],
    ])
    bg_color = np.median(edges, axis=0).astype(np.float32)
    log.info("Detected background color: RGB(%d, %d, %d)", *bg_color.astype(int))

    diff = np.sqrt(((arr.astype(np.float32) - bg_color) ** 2).sum(axis=2))
    return diff > tolerance


def _extract_boxes(
    mask: np.ndarray, min_area_frac: float, total_pixels: int
) -> list[tuple[int, int, int, int]]:
    """Extract bounding boxes from a boolean mask using connected-component labeling."""
    from scipy import ndimage

    labeled, num_features = ndimage.label(mask)
    boxes = []

    for i in range(1, num_features + 1):
        component = labeled == i
        area = component.sum()
        if area < min_area_frac * total_pixels:
            continue

        rows = np.where(component.any(axis=1))[0]
        cols = np.where(component.any(axis=0))[0]
        box = (int(cols[0]), int(rows[0]), int(cols[-1] + 1), int(rows[-1] + 1))
        bw, bh = box[2] - box[0], box[3] - box[1]

        box_area = bw * bh
        fill_ratio = area / box_area
        if fill_ratio < 0.5:
            continue

        boxes.append(box)
        log.info(
            "Placeholder %d: %dx%d at (%d,%d), fill=%.0f%%",
            len(boxes), bw, bh, box[0], box[1], fill_ratio * 100,
        )

    boxes.sort(key=lambda b: (b[2] - b[0]) * (b[3] - b[1]), reverse=True)
    return boxes


def cover_crop(photo: Image.Image, width: int, height: int) -> Image.Image:
    """Resize and center-crop a photo to exactly fill width x height."""
    target_ratio = width / height
    photo_ratio = photo.width / photo.height

    if photo_ratio > target_ratio:
        new_h = height
        new_w = int(photo.width * height / photo.height)
    else:
        new_w = width
        new_h = int(photo.height * width / photo.width)

    resized = photo.resize((new_w, new_h), Image.LANCZOS)
    left = (new_w - width) // 2
    top = (new_h - height) // 2
    return resized.crop((left, top, left + width, top + height))


def rounded_mask(width: int, height: int, radius: int) -> Image.Image:
    """Create a rounded-rectangle alpha mask."""
    mask = Image.new("L", (width, height), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, width - 1, height - 1], radius=radius, fill=255)
    return mask


def _sample_background(img: Image.Image) -> tuple[int, int, int]:
    """Sample the dominant background color from image edges."""
    arr = np.array(img)
    edges = np.concatenate([arr[0, :, :], arr[-1, :, :], arr[:, 0, :], arr[:, -1, :]])
    return tuple(int(v) for v in np.median(edges, axis=0))


def composite(
    base: Image.Image,
    photos: list[Image.Image],
    boxes: list[tuple[int, int, int, int]],
    corner_radius: int = 20,
) -> Image.Image:
    """Paste photos into placeholder boxes on the base image.

    Photos are matched to boxes in order (first photo -> largest box, etc.).
    Each photo is cover-cropped to fit its box and masked with rounded corners.
    The placeholder area is filled with the background color first so that
    sharp-cornered originals don't peek through the rounded mask.
    """
    result = base.copy()
    bg_color = _sample_background(base)
    n = min(len(photos), len(boxes))

    for i in range(n):
        box = boxes[i]
        photo = photos[i]
        x1, y1, x2, y2 = box
        tw, th = x2 - x1, y2 - y1

        ImageDraw.Draw(result).rectangle([x1, y1, x2 - 1, y2 - 1], fill=bg_color)
        cropped = cover_crop(photo, tw, th)
        mask = rounded_mask(tw, th, corner_radius)
        result.paste(cropped, (x1, y1), mask)
        log.info("Placed photo %d into %dx%d box at (%d,%d)", i + 1, tw, th, x1, y1)

    return result


def composite_file(
    base_path: str | Path,
    photo_paths: list[str | Path],
    output_path: str | Path,
    placeholder_color: tuple[int, int, int] | None = None,
    tolerance: int = 60,
    corner_radius: int = 20,
    dpi: int = 300,
) -> Path:
    """Full pipeline: load base, detect placeholders, composite photos, save."""
    base_path = Path(base_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    base = load_base(base_path, dpi=dpi)
    boxes = detect_placeholders(base, color=placeholder_color, tolerance=tolerance)

    if not boxes:
        raise ValueError(f"No placeholder regions detected in {base_path}")

    photos = [Image.open(p).convert("RGB") for p in photo_paths]
    result = composite(base, photos, boxes, corner_radius=corner_radius)
    result.save(str(output_path), quality=95)
    log.info("Saved: %s (%dx%d)", output_path, result.width, result.height)
    return output_path
