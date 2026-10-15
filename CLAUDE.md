# Gen

General-purpose generative media toolkit. Jinja2 HTML templates + real assets rendered to production images via Playwright.

## Structure

- `brands/` - Brand configs (colors, fonts, logos) as YAML. One dir per brand.
- `templates/` - Jinja2 HTML templates organized by type (flyer/, social/, etc.)
- `assets/` - Shared assets (photos, icons). Brand-specific assets go in `brands/<slug>/`
- `output/` - Rendered output (gitignored)
- `gen/` - Python package: render engine, CLI

## Usage

```bash
pip install -e .
playwright install chromium
gen render flyer/meeting-recap.html --brand yimby-dems --context context.json
gen render flyer/meeting-recap.html --brand yimby-dems --context '{"subtitle": "test"}'
```

Context accepts a JSON file path or inline JSON string.

## Adding a brand

Create `brands/<slug>/brand.yaml` with colors, fonts, logo references. Drop logo files in the same directory. Required keys: `name`, `slug`, `colors` (primary, secondary, accent, background, text, text-light), `fonts` (display, heading, body), `logo` (primary).

## Adding a template

HTML + Jinja2 in `templates/<category>/<name>.html`. Templates receive `brand` (from YAML), `width`, `height`, plus whatever context vars they declare. Hyphenated color keys are also available as underscored (e.g. `brand.colors.text_light`).

Asset paths in context (photos, speaker photos) are resolved to absolute paths for `file://` URLs. The rendered HTML is saved alongside the image output for debugging.

## Design principles

- AI does layout and composition. Real photos, logos, fonts only.
- Every template must work with just a brand config + content inputs.
- Output should be indistinguishable from human-designed work.
