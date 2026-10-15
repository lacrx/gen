"""CLI entry point for gen toolkit."""

import argparse
import json
import sys
from pathlib import Path

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

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    if args.command == "render":
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


if __name__ == "__main__":
    main()
