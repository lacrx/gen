"""Render HTML templates to images via Playwright."""

import asyncio
from pathlib import Path

import yaml
from jinja2 import Environment, FileSystemLoader

REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = REPO_ROOT / "templates"
BRANDS_DIR = REPO_ROOT / "brands"
OUTPUT_DIR = REPO_ROOT / "output"


def load_brand(slug: str) -> dict:
    brand_file = BRANDS_DIR / slug / "brand.yaml"
    brand = yaml.safe_load(brand_file.read_text())
    brand_dir = brand_file.parent
    if brand.get("logo", {}).get("primary"):
        logo_path = brand_dir / brand["logo"]["primary"]
        if logo_path.exists():
            brand["logo_path"] = str(logo_path.resolve())
    brand["name_short"] = brand.get("name", "").split(" ")[0:2]
    brand["name_short"] = " ".join(brand["name_short"])
    brand["text_light"] = brand.get("colors", {}).get("text-light", "#FFFFFF")
    brand["colors"]["text_light"] = brand["colors"].get("text-light", "#FFFFFF")
    return brand


def render_html(template_path: str, context: dict) -> str:
    category, name = template_path.split("/", 1)
    env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR / category)))
    template = env.get_template(name)
    return template.render(**context)


async def render_to_image(
    html: str,
    output_path: Path,
    width: int = 1080,
    height: int = 1350,
) -> Path:
    from playwright.async_api import async_playwright

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(viewport={"width": width, "height": height})
        await page.set_content(html, wait_until="networkidle")
        await page.screenshot(path=str(output_path), full_page=False)
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
    brand = load_brand(brand_slug)
    full_context = {
        "brand": brand,
        "width": width,
        "height": height,
        **context,
    }
    html = render_html(template_path, full_context)
    output_path = OUTPUT_DIR / output_name
    return asyncio.run(render_to_image(html, output_path, width, height))
