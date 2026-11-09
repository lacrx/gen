"""CLI entry point for gen toolkit."""

import argparse
import json
import sys
from pathlib import Path

from gen.composite import composite_file
from gen.pixel import (
    contact_sheet,
    load_sprite,
    palette_from_image,
    quantize_to_palette,
    render_sprite,
    trace,
)
from gen.render import generate


def main():
    parser = argparse.ArgumentParser(
        description="Gen: render Jinja2 HTML templates to images via Playwright",
    )
    sub = parser.add_subparsers(dest="command")

    render = sub.add_parser("render", help="Render a template to an image")
    render.add_argument(
        "template",
        help="Template path relative to templates/ (e.g. flyer/meeting-recap.html)",
    )
    render.add_argument("--brand", required=True, help="Brand slug (directory name under brands/)")
    render.add_argument(
        "--context",
        required=True,
        help="Template variables as a JSON file path or inline JSON string",
    )
    render.add_argument(
        "--output", default="flyer.png", help="Output filename (default: flyer.png)"
    )
    render.add_argument(
        "--width", type=int, default=1080, help="Viewport width in px (default: 1080)"
    )
    render.add_argument(
        "--height", type=int, default=1350, help="Viewport height in px (default: 1350)"
    )

    comp = sub.add_parser(
        "composite",
        help="Drop photos into placeholder regions of an existing design",
    )
    comp.add_argument("base", help="Base image or PDF file with placeholder regions")
    comp.add_argument("photos", nargs="+", help="Photos to place (largest placeholder first)")
    comp.add_argument(
        "--output", "-o", default="composite.png", help="Output filename (default: composite.png)"
    )
    comp.add_argument(
        "--color",
        help="Placeholder color as 'R,G,B' (e.g. '255,105,180' for pink). Auto-detects if omitted.",
    )
    comp.add_argument(
        "--tolerance", type=int, default=60, help="Color matching tolerance (default: 60)"
    )
    comp.add_argument("--radius", type=int, default=20, help="Corner radius in px (default: 20)")
    comp.add_argument("--dpi", type=int, default=300, help="PDF render DPI (default: 300)")

    pixel = sub.add_parser("pixel", help="Render and convert pixel sprites")
    psub = pixel.add_subparsers(dest="pixel_command")

    p_render = psub.add_parser("render", help="Render one frame of a sprite")
    p_render.add_argument("sprite", help="Sprite slug (sprites/<slug>/) or path to sprite.yaml")
    p_render.add_argument("--frame", help="Frame name (default: the first frame defined)")
    p_render.add_argument("--scale", type=int, default=8, help="Pixels per cell (default: 8)")
    p_render.add_argument("--bg", help="Background as hex, e.g. '#F7F3EC' (default: transparent)")
    p_render.add_argument("--svg", action="store_true", help="Write SVG instead of PNG")
    p_render.add_argument("--output", "-o", help="Output filename (default: <name>-<frame>.<ext>)")

    p_sheet = psub.add_parser("sheet", help="Render every frame to one contact sheet")
    p_sheet.add_argument("sprite", help="Sprite slug or path to sprite.yaml")
    p_sheet.add_argument("--scale", type=int, default=4, help="Pixels per cell (default: 4)")
    p_sheet.add_argument("--columns", type=int, default=4, help="Frames per row (default: 4)")
    p_sheet.add_argument("--bg", default="#F7F3EC", help="Sheet background (default: #F7F3EC)")
    p_sheet.add_argument("--output", "-o", help="Output filename (default: <name>-sheet.png)")

    p_trace = psub.add_parser("trace", help="Convert an image into an editable character map")
    p_trace.add_argument("image", help="Source image")
    p_trace.add_argument("--size", type=int, default=32, help="Grid size (default: 32)")
    p_trace.add_argument("--sprite", help="Sprite slug or path to borrow the palette from")
    p_trace.add_argument("--colors", type=int, default=6, help="Palette size if no --sprite given")
    p_trace.add_argument("--bg", help="Background hex; cells nearest to it become transparent")
    p_trace.add_argument("--output", "-o", help="Write a sprite.yaml here instead of printing")

    p_quant = psub.add_parser("quantize", help="Force an image onto an exact palette")
    p_quant.add_argument("image", help="Source image")
    p_quant.add_argument("--sprite", help="Sprite slug or path to borrow the palette from")
    p_quant.add_argument("--colors", type=int, default=6, help="Palette size if no --sprite given")
    p_quant.add_argument("--output", "-o", default="quantized.png", help="Output filename")

    p_pal = psub.add_parser("palette", help="Suggest a palette from an image")
    p_pal.add_argument("image", help="Source image")
    p_pal.add_argument("--colors", type=int, default=6, help="How many colours (default: 6)")

    gener = sub.add_parser(
        "generate",
        help="Generate sprite candidates via Retro Diffusion (costs credits)",
    )
    gsub = gener.add_subparsers(dest="generate_command")

    gsub.add_parser("credits", help="Show the remaining API balance")
    gsub.add_parser("styles", help="List available styles with their size limits")

    g_sprite = gsub.add_parser("sprite", help="Generate sprite candidates into output/")
    g_sprite.add_argument("prompt", help="What to draw")
    g_sprite.add_argument("--refs", nargs="*", default=[], help="Reference photos (max 9)")
    g_sprite.add_argument("--palette", help="Sprite slug whose palette constrains the output")
    g_sprite.add_argument("--size", type=int, default=64, help="Square size, 12-512 (default: 64)")
    g_sprite.add_argument("--count", type=int, default=4, help="How many candidates (default: 4)")
    g_sprite.add_argument(
        "--style", default="rd_pro__default", help="Style id (default: rd_pro__default)"
    )
    g_sprite.add_argument("--seed", type=int, help="Seed for repeatable output")
    g_sprite.add_argument("--prefix", default="candidate", help="Output filename prefix")
    g_sprite.add_argument(
        "--yes",
        action="store_true",
        help="Actually spend credits. Without this the cost is estimated and nothing runs.",
    )

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    if args.command == "pixel":
        if not getattr(args, "pixel_command", None):
            pixel.print_help()
            sys.exit(1)
        _do_pixel(args)
    elif args.command == "generate":
        if not getattr(args, "generate_command", None):
            gener.print_help()
            sys.exit(1)
        _do_generate(args)
    elif args.command == "composite":
        _do_composite(args)
    elif args.command == "render":
        # Accept context as a file path or inline JSON
        ctx_arg = args.context
        ctx_path = Path(ctx_arg)
        if ctx_path.is_file():
            try:
                ctx = json.loads(ctx_path.read_text())
            except json.JSONDecodeError as e:
                print(f"Error: invalid JSON in {ctx_path}: {e}", file=sys.stderr)
                sys.exit(1)
        else:
            try:
                ctx = json.loads(ctx_arg)
            except json.JSONDecodeError:
                print(
                    f"Error: '{ctx_arg}' is not a valid file path or JSON string",
                    file=sys.stderr,
                )
                sys.exit(1)

        if not isinstance(ctx, dict):
            print("Error: context must be a JSON object, not a list or scalar", file=sys.stderr)
            sys.exit(1)

        try:
            result = generate(
                args.template,
                args.brand,
                ctx,
                args.output,
                args.width,
                args.height,
            )
            print(f"Rendered: {result}")
        except FileNotFoundError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)
        except Exception as e:
            print(f"Error during render: {e}", file=sys.stderr)
            sys.exit(1)


def _palette_for(args) -> dict:
    """Palette from a named sprite, else suggested from the image itself."""
    if getattr(args, "sprite", None):
        return load_sprite(args.sprite).palette
    return palette_from_image(args.image, args.colors)


def _do_pixel(args):
    import logging

    from PIL import Image

    from gen.pixel import OUTPUT_DIR, Sprite, save_sprite

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    try:
        if args.pixel_command == "render":
            out = render_sprite(
                args.sprite,
                frame=args.frame,
                scale=args.scale,
                background=args.bg,
                output_name=args.output,
                svg=args.svg,
            )
            print(f"Rendered: {out}")

        elif args.pixel_command == "sheet":
            sprite = load_sprite(args.sprite)
            sheet = contact_sheet(
                sprite, scale=args.scale, columns=args.columns, background=args.bg
            )
            out = OUTPUT_DIR / (args.output or f"{sprite.name}-sheet.png")
            out.parent.mkdir(parents=True, exist_ok=True)
            sheet.save(out)
            print(f"Saved: {out} ({len(sprite.frame_names)} frames)")

        elif args.pixel_command == "trace":
            palette = _palette_for(args)
            rows = trace(args.image, args.size, palette, background=args.bg)
            if args.output:
                sprite = Sprite(
                    name=Path(args.image).stem,
                    size=args.size,
                    palette=palette,
                    frames={"idle": rows},
                )
                print(f"Saved: {save_sprite(sprite, args.output)}")
            else:
                print("\n".join(rows))

        elif args.pixel_command == "quantize":
            palette = _palette_for(args)
            result = quantize_to_palette(Image.open(args.image), list(palette.values()))
            out = OUTPUT_DIR / args.output
            out.parent.mkdir(parents=True, exist_ok=True)
            result.save(out)
            print(f"Saved: {out}")

        elif args.pixel_command == "palette":
            for char, value in palette_from_image(args.image, args.colors).items():
                print(f'  "{char}": "{value}"')

    except (FileNotFoundError, ValueError, KeyError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def _do_generate(args):
    """Retro Diffusion is imported lazily: it is the one module that calls a model."""
    import logging

    from gen.retrodiffusion import (
        RetroDiffusionError,
        build_payload,
        credits,
        estimate,
        load_api_key,
        save_images,
        styles,
        submit,
    )

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    try:
        key = load_api_key()

        if args.generate_command == "credits":
            info = credits(key)
            print(f"Balance: {info.get('balance')} (credits: {info.get('credits')})")
            return

        if args.generate_command == "styles":
            for style in styles(key):
                sid = style.get("style_id") or style.get("id") or "?"
                print(f"  {sid:28} {style.get('name', '')}")
            return

        palette = None
        if args.palette:
            palette = list(load_sprite(args.palette).palette.values())

        for ref in args.refs:
            if not Path(ref).is_file():
                print(f"Error: reference not found: {ref}", file=sys.stderr)
                sys.exit(1)

        payload = build_payload(
            prompt=args.prompt,
            style=args.style,
            width=args.size,
            height=args.size,
            num_images=args.count,
            references=args.refs,
            palette=palette,
            seed=args.seed,
        )

        cost = estimate(payload, key)
        price = cost.get("balance_cost")
        remaining = cost.get("remaining_balance")
        print(
            f"Estimated cost: {price} for {args.count} image(s) at {args.size}x{args.size} "
            f"({args.style}). Balance: {remaining}"
        )

        if not args.yes:
            print("Nothing generated. Re-run with --yes to spend credits.")
            return

        result = submit(payload, key, confirm=True)
        paths = save_images(result, prefix=args.prefix)
        if not paths:
            print("Warning: no images returned", file=sys.stderr)
        for path in paths:
            print(f"Saved: {path}")
        print(f"Spent: {result.get('balance_cost')} | remaining: {result.get('remaining_balance')}")
        print("Bring the best one in with: gen pixel trace <file> --size N --sprite <slug>")

    except RetroDiffusionError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except (FileNotFoundError, ValueError, KeyError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def _do_composite(args):
    import logging

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    color = None
    if args.color:
        try:
            color = tuple(int(c.strip()) for c in args.color.split(","))
            if len(color) != 3:
                raise ValueError
        except ValueError:
            print("Error: --color must be 'R,G,B' (e.g. '255,105,180')", file=sys.stderr)
            sys.exit(1)

    for p in args.photos:
        if not Path(p).is_file():
            print(f"Error: photo not found: {p}", file=sys.stderr)
            sys.exit(1)

    try:
        result = composite_file(
            args.base,
            args.photos,
            args.output,
            placeholder_color=color,
            tolerance=args.tolerance,
            corner_radius=args.radius,
            dpi=args.dpi,
        )
        print(f"Saved: {result}")
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
