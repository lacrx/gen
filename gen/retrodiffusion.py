"""Retro Diffusion client: the one place in this toolkit that calls a model.

Everything else in gen is deterministic. This module is the explicit boundary. It costs
money, needs a network and an API key, and what it returns is a *candidate*, never a build
artifact. Candidates land in output/ (gitignored). A chosen candidate enters the repo only
through `gen pixel trace`, which turns it into an editable character map; the map stays
canonical.

Nothing here spends without an explicit go-ahead: `submit` refuses unless confirm=True,
and `estimate` is a free dry run that reports the price first.

API contract: https://github.com/Retro-Diffusion/api-examples
"""

import base64
import io
import json
import logging
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from PIL import Image

log = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = REPO_ROOT / "output"
ENV_FILE = REPO_ROOT / ".env"

BASE_URL = "https://api.retrodiffusion.ai/v2"
KEY_VAR = "RETRODIFFUSION_API_KEY"

# Reference images are sent inline as base64; full-size phone photos make the body huge
# and buy nothing, since the model sees a small image anyway.
REFERENCE_MAX_PX = 512
MAX_REFERENCE_IMAGES = 9

TERMINAL_OK = "succeeded"
RETRYABLE_TASK_CODES = {
    "inference_failed",
    "provider_busy",
    "provider_timeout",
    "request_timeout",
}


class RetroDiffusionError(RuntimeError):
    """An API error, carrying the service's own code where one was returned."""

    def __init__(self, message: str, code: str | None = None, status: int | None = None):
        super().__init__(message)
        self.code = code
        self.status = status


def load_api_key(env_file: Path | None = None) -> str:
    """Read the key from the environment, falling back to the repo's .env.

    The value is never logged or printed by this module.
    """
    import os

    key = os.environ.get(KEY_VAR)
    if key:
        return key.strip()

    path = Path(env_file) if env_file else ENV_FILE
    if path.exists():
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            name, _, value = line.partition("=")
            if name.strip() == KEY_VAR:
                return value.strip().strip("'\"")

    raise RetroDiffusionError(
        f"No API key. Set {KEY_VAR} in the environment or add it to {path}", code="no_key"
    )


def _call(method: str, path: str, key: str, body: dict | None = None, timeout: int = 60) -> dict:
    url = f"{BASE_URL}{path}"
    data = json.dumps(body).encode() if body is not None else None
    headers = {"X-RD-Token": key, "Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/json"
        # Paid submissions must be idempotent; cost checks must not be.
        if not body.get("check_cost"):
            headers["Idempotency-Key"] = str(uuid.uuid4())

    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        raw = e.read().decode(errors="replace")
        code = message = None
        try:
            payload = json.loads(raw)
            err = payload.get("error") or payload.get("detail")
            if isinstance(err, dict):
                code, message = err.get("code"), err.get("message")
            elif isinstance(err, str):
                message = err
        except json.JSONDecodeError:
            message = raw[:300]

        hint = {
            401: "the key was rejected",
            402: "the account cannot fund this request",
            404: "no such task, request or style",
            409: "idempotency key reused with different inputs",
            429: f"rate limited; retry after {e.headers.get('Retry-After', '?')}s",
        }.get(e.code, "")
        detail = " - ".join(p for p in (message, hint) if p)
        raise RetroDiffusionError(
            f"HTTP {e.code}: {detail or 'request failed'}", code=code, status=e.code
        ) from None
    except urllib.error.URLError as e:
        raise RetroDiffusionError(f"Could not reach the API: {e.reason}", code="network") from None


def _unwrap(task: dict) -> dict:
    """V2 nests the payload under 'result'; some paths return it flat.

    Verified against a live task on 2026-11-09: a completed /inferences task carries
    base64_images, balance_cost and remaining_balance inside 'result', not at the top level.
    """
    inner = task.get("result")
    if isinstance(inner, dict) and ("base64_images" in inner or "output_urls" in inner):
        return {**inner, "task_id": task.get("task_id"), "status": task.get("status")}
    return task


def credits(key: str) -> dict:
    """Current balance. Credits cannot be bought through the API."""
    return _call("GET", "/inferences/credits", key)


def styles(key: str) -> list[dict]:
    """Available styles with their size limits and batch caps."""
    data = _call("GET", "/styles/selector", key)
    return data.get("styles", data if isinstance(data, list) else [])


def encode_image(path: str | Path, max_px: int = REFERENCE_MAX_PX) -> str:
    """Load an image, flatten to RGB, bound its size, and return raw base64 PNG.

    The API wants raw base64 with no data: prefix.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Image not found: {path}")

    img = Image.open(path)
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        flat = Image.new("RGB", img.size, (255, 255, 255))
        flat.paste(img, mask=img.split()[-1])
        img = flat
    else:
        img = img.convert("RGB")

    if max_px and max(img.size) > max_px:
        img.thumbnail((max_px, max_px), Image.Resampling.LANCZOS)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


def encode_palette(colors: list[str]) -> str:
    """Build a 1-pixel-per-colour PNG for input_palette, as raw base64."""
    from gen.pixel import _hex_to_rgb

    if not colors:
        raise ValueError("palette must contain at least one colour")
    img = Image.new("RGB", (len(colors), 1))
    img.putdata([_hex_to_rgb(c) for c in colors])
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


def build_payload(
    prompt: str,
    style: str = "rd_pro__default",
    width: int = 64,
    height: int = 64,
    num_images: int = 1,
    references: list[str | Path] | None = None,
    palette: list[str] | None = None,
    seed: int | None = None,
    remove_bg: bool = True,
    check_cost: bool = False,
) -> dict:
    """Assemble an /inferences request body."""
    if not (12 <= width <= 512 and 12 <= height <= 512):
        raise ValueError(f"width and height must be 12-512, got {width}x{height}")

    payload: dict = {
        "prompt": prompt,
        "prompt_style": style,
        "width": width,
        "height": height,
        "num_images": num_images,
    }
    if seed is not None:
        payload["seed"] = seed
    if remove_bg:
        payload["remove_bg"] = True
    if check_cost:
        payload["check_cost"] = True

    if references:
        refs = list(references)
        if len(refs) > MAX_REFERENCE_IMAGES:
            log.warning(
                "Only the first %d reference images are used; %d given",
                MAX_REFERENCE_IMAGES,
                len(refs),
            )
            refs = refs[:MAX_REFERENCE_IMAGES]
        payload["reference_images"] = [encode_image(r) for r in refs]

    if palette:
        payload["input_palette"] = encode_palette(palette)
        payload["return_pre_palette"] = True

    return payload


def estimate(payload: dict, key: str) -> dict:
    """Free dry run: what this request would cost, generating nothing."""
    probe = {**payload, "check_cost": True}
    probe.pop("return_pre_palette", None)
    return _call("POST", "/inferences", key, probe)


def submit(payload: dict, key: str, confirm: bool = False, poll_timeout: int = 900) -> dict:
    """Run a generation and wait for it. Spends money, so confirm must be True."""
    if not confirm:
        raise RetroDiffusionError(
            "submit() spends credits; pass confirm=True once the cost is understood",
            code="not_confirmed",
        )

    accepted = _call("POST", "/inferences", key, payload)
    task_id = accepted.get("task_id")
    if not task_id:
        # Some paths answer synchronously.
        if accepted.get("base64_images") or accepted.get("output_urls"):
            return accepted
        raise RetroDiffusionError(f"No task_id in response: {accepted}", code="no_task")

    log.info("Queued task %s", task_id)
    deadline = time.monotonic() + poll_timeout
    delay = 2.0

    while time.monotonic() < deadline:
        time.sleep(delay)
        task = _call("GET", f"/inferences/tasks/{task_id}", key)
        status = task.get("status")

        if status == TERMINAL_OK:
            return _unwrap(task)
        if status is None and (task.get("base64_images") or task.get("output_urls")):
            return _unwrap(task)
        if status == "failed":
            err = task.get("error") or {}
            code = err.get("code", "failed")
            retry = " (retryable)" if code in RETRYABLE_TASK_CODES else ""
            raise RetroDiffusionError(
                f"Task failed: {err.get('message', 'no detail')}{retry}", code=code
            )
        if status not in ("pending", "running", "queued", None):
            log.debug("Unrecognised task status %r, continuing to poll", status)
        delay = min(delay * 1.4, 10.0)

    raise RetroDiffusionError(
        f"Task {task_id} did not finish within {poll_timeout}s", code="poll_timeout"
    )


def save_images(result: dict, prefix: str = "candidate", out_dir: Path | None = None) -> list[Path]:
    """Write a result's images to output/, returning the paths written."""
    out_dir = Path(out_dir) if out_dir else OUTPUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    result = _unwrap(result)
    images = result.get("base64_images") or []
    paths = []
    for i, b64 in enumerate(images):
        path = out_dir / f"{prefix}-{i:02d}.png"
        path.write_bytes(base64.b64decode(b64))
        paths.append(path)

    if not paths and result.get("output_urls"):
        log.warning(
            "No inline images; the result carries %d hosted URL(s): %s",
            len(result["output_urls"]),
            ", ".join(result["output_urls"][:3]),
        )
    return paths
