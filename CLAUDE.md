# Gen

General-purpose generative media toolkit. Source files in, production images out, deterministically.

Three pipelines, one per module:

- **render** - Jinja2 HTML templates + real assets to images via Playwright
- **composite** - photos dropped into placeholder regions of an existing design
- **pixel** - character-map sprites to images, and images back to character maps
- **generate** - sprite candidates from Retro Diffusion (the only module that calls a model)

## Structure

- `brands/` - Brand configs (colors, fonts, logos) as YAML. One dir per brand.
- `templates/` - Jinja2 HTML templates organized by type (flyer/, social/, etc.)
- `sprites/` - Pixel sprites as YAML. One dir per sprite, same shape as `brands/`.
- `assets/` - Shared assets (photos, icons). Brand-specific assets go in `brands/<slug>/`
- `output/` - Rendered output (gitignored)
- `gen/` - Python package: one module per pipeline, plus the CLI

## Usage

```bash
pip install -e .
playwright install chromium
gen render flyer/meeting-recap.html --brand yimby-dems --context context.json
gen render flyer/meeting-recap.html --brand yimby-dems --context '{"subtitle": "test"}'

gen pixel render geoff --scale 10 --bg "#F7F3EC"
gen pixel sheet geoff --scale 6
gen pixel trace photo.png --size 32 --sprite geoff -o sprites/geoff/sprite.yaml
```

Context accepts a JSON file path or inline JSON string.

Use a virtualenv: `python3 -m venv .venv && .venv/bin/pip install -e .`. On Debian or Ubuntu
this needs `python3.12-venv` from apt.

## Adding a brand

Create `brands/<slug>/brand.yaml` with colors, fonts, logo references. Drop logo files in the same directory. Required keys: `name`, `slug`, `colors` (primary, secondary, accent, background, text, text-light), `fonts` (display, heading, body), `logo` (primary).

## Adding a template

HTML + Jinja2 in `templates/<category>/<name>.html`. Templates receive `brand` (from YAML), `width`, `height`, plus whatever context vars they declare. Hyphenated color keys are also available as underscored (e.g. `brand.colors.text_light`).

Asset paths in context (photos, speaker photos) are resolved to absolute paths for `file://` URLs. The rendered HTML is saved alongside the image output for debugging.

## Adding a sprite

Create `sprites/<slug>/sprite.yaml` with `name`, `size`, `palette` and `frames`. The palette
maps single characters to hex colors; `.` is reserved for transparency. Each frame is a block
of `size` lines of `size` characters. Frames are validated on load, so a typo is a clear error
rather than a wrong picture.

The source of truth is the character map, not a binary. Sprites are plain text: diffable,
reviewable, and editable one pixel at a time.

`gen pixel trace` converts an image into a character map using a fixed palette, which is how
art made elsewhere enters the repo. Correct it by hand afterwards; the map stays canonical.

Iterating on a sprite works best as a loop: edit the map, `gen pixel render`, look at the PNG,
correct. Writing a 32x32 grid blind does not work, for people or for models.

## Generating sprite candidates

`gen generate` is the only thing here that calls a model. It needs
`RETRODIFFUSION_API_KEY` in the environment or in `.env`, and it spends real money.

```bash
gen generate credits                      # balance
gen generate styles                       # styles, size limits, reference support
gen generate sprite "<prompt>" --refs a.png b.png --size 64 --count 8
gen generate sprite "<prompt>" --refs a.png b.png --size 64 --count 8 --yes
```

Without `--yes` it runs the free `check_cost` dry run, prints the price, and generates
nothing. `submit()` refuses outright unless `confirm=True`, so the library cannot spend by
accident.

Candidates land in `output/`, which is gitignored. They are never build artifacts. A chosen
candidate enters the repo only through `gen pixel trace`, and the resulting character map is
canonical from then on: correct it by hand, do not regenerate over it.

What was learned doing this for the `geoff` sprite, on 2026-11-09:

- **Only RD Pro accepts reference images.** RD Fast, Mini and Plus support zero across 43
  styles. Without references there is no likeness, so there is no cheap tier for this job.
- **Do not pass `--palette` at generation time.** Constraining the model to a small palette
  forces it to shade with whatever is available; a five-colour set whose spare entries were
  eye-green and nose-pink produced cats with pink chests and green backgrounds. Generate
  unconstrained and quantize locally, where iteration is free.
- **64x64, not 32.** At 32 the silhouette survives but the face does not, and for an animal
  the identity is in the face.
- **Check the traced map's colour counts.** Small accents (eyes, nose) can vanish into
  nearest-neighbour matching, and two near-identical palette entries will split a region
  arbitrarily between them.

## Design principles

- AI does layout and composition. Real photos, logos, fonts only.
- Rendering is deterministic. No module here calls a model, and output for a given input
  does not drift. Anything generative belongs behind an explicit, separate boundary.
- Every template must work with just a brand config + content inputs.
- Output should be indistinguishable from human-designed work.
