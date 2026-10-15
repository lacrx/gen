"""Render HTML templates to images via Playwright."""

import asyncio
import logging
from pathlib import Path

import yaml
from jinja2 import Environment, FileSystemLoader, TemplateNotFound

log = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = REPO_ROOT / "templates"
BRANDS_DIR = REPO_ROOT / "brands"
OUTPUT_DIR = REPO_ROOT / "output"


def load_brand(slug: str) -> dict:
    """Load a brand config from brands/<slug>/brand.yaml."""
    brand_dir = BRANDS_DIR / slug
    brand_file = brand_dir / "brand.yaml"
    if not brand_file.exists():
        raise FileNotFoundError(f"Brand config not found: {brand_file}")

    brand = yaml.safe_load(brand_file.read_text())
    if not isinstance(brand, dict):
        raise ValueError(f"Brand config must be a YAML mapping: {brand_file}")

    # Resolve logo to absolute path for file:// URLs in templates
    logo_ref = brand.get("logo", {}).get("primary")
    if logo_ref:
        logo_path = brand_dir / logo_ref
        if logo_path.exists():
            brand["logo_path"] = str(logo_path.resolve())
        else:
            log.warning("Logo file not found: %s", logo_path)

    # Convenience fields for templates
    name = brand.get("name", "")
    brand["name_short"] = " ".join(name.split()[:2])

    # Normalize hyphenated color keys to underscored for Jinja2 attribute access
    colors = brand.get("colors", {})
    for key in list(colors):
        if "-" in key:
            colors[key.replace("-", "_")] = colors[key]
    brand["colors"] = colors

    return brand


def render_html(template_path: str, context: dict) -> str:
    """Render a Jinja2 template with the given context.

    template_path is relative to TEMPLATES_DIR, e.g. "flyer/meeting-recap.html".
    """
    if "/" not in template_path:
        raise ValueError(
            f"Template path must include a category: 'category/name.html', got '{template_path}'"
        )

    category, name = template_path.split("/", 1)
    template_dir = TEMPLATES_DIR / category
    if not template_dir.is_dir():
        raise FileNotFoundError(f"Template category directory not found: {template_dir}")

    env = Environment(loader=FileSystemLoader(str(template_dir)))
    try:
        template = env.get_template(name)
    except TemplateNotFound:
        raise FileNotFoundError(f"Template not found: {TEMPLATES_DIR / template_path}")
    return template.render(**context)


async def render_to_image(
    html: str,
    output_path: Path,
    width: int = 1080,
    height: int = 1350,
) -> Path:
    """Render an HTML string to a screenshot via Playwright."""
    from playwright.async_api import async_playwright

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        try:
            page = await browser.new_page(viewport={"width": width, "height": height})
            await page.set_content(html, wait_until="networkidle")

            if output_path.suffix.lower() == ".pdf":
                await page.pdf(path=str(output_path), width=f"{width}px", height=f"{height}px")
            else:
                await page.screenshot(path=str(output_path), full_page=False)
        finally:
            await browser.close()

    return output_path


def generate(
    template_path: str,
    brand_slug: str,
    context: dict,
    output_name: str = "flyer.png",
    width: int = 1080,
    height: int = 1350,
) -> Path:
    """Full pipeline: load brand, render template, screenshot to file."""
    brand = load_brand(brand_slug)

    # Resolve any relative asset paths in context to absolute for file:// URLs
    if "photos" in context:
        context["photos"] = [
            str(Path(p).resolve()) if not Path(p).is_absolute() else p for p in context["photos"]
        ]
    if "speakers" in context:
        for speaker in context["speakers"]:
            if speaker.get("photo") and not Path(speaker["photo"]).is_absolute():
                speaker["photo"] = str(Path(speaker["photo"]).resolve())

    full_context = {
        "brand": brand,
        "width": width,
        "height": height,
        **context,
    }

    html = render_html(template_path, full_context)

    # Also save the rendered HTML for debugging
    html_stem = output_name.rsplit(".", 1)[0]
    html_output = OUTPUT_DIR / f"{html_stem}.html"
    html_output.parent.mkdir(parents=True, exist_ok=True)
    html_output.write_text(html)
    log.info("Saved HTML: %s", html_output)

    output_path = OUTPUT_DIR / output_name
    return asyncio.run(render_to_image(html, output_path, width, height))
