"""CLI entry point for gen toolkit."""

import argparse
import json
import sys
from pathlib import Path

from gen.render import generate


def main():
    parser = argparse.ArgumentParser(description="Generative media toolkit")
    sub = parser.add_subparsers(dest="command")

    render = sub.add_parser("render", help="Render a template to an image")
    render.add_argument("template", help="Template path (e.g. flyer/meeting-recap.html)")
    render.add_argument("--brand", required=True, help="Brand slug (e.g. yimby-dems)")
    render.add_argument("--context", required=True, help="JSON file with template variables")
    render.add_argument("--output", default="flyer.png", help="Output filename")
    render.add_argument("--width", type=int, default=1080)
    render.add_argument("--height", type=int, default=1350)

    args = parser.parse_args()

    if args.command == "render":
        ctx = json.loads(Path(args.context).read_text())
        result = generate(
            args.template,
            args.brand,
            ctx,
            args.output,
            args.width,
            args.height,
        )
        print(f"Rendered: {result}")
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
