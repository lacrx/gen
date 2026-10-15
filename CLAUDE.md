# Gen

General-purpose generative media toolkit. Templates + real assets rendered to production images. No AI-generated pixels in final output.

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
```

## Adding a brand

Create `brands/<slug>/brand.yaml` with colors, fonts, logo references. Drop logo files in the same directory.

## Adding a template

HTML + Jinja2 in `templates/<category>/<name>.html`. Templates receive `brand` (from YAML) plus whatever context vars they declare.

## Design principles

- AI does layout and composition. Real photos, logos, fonts only.
- Every template must work with just a brand config + content inputs.
- Output should be indistinguishable from human-designed work.
