#!/usr/bin/env python3
"""
Product Forge — CLI entry point.

Usage:
    # Text-only brief
    python main.py "Build a home energy management app that..."

    # With a UI screenshot
    python main.py "Analyze this app and build something better" --image input/screenshot.png

    # Quick mode (skip cross-review and synthesis)
    python main.py "..." --quick

    # With brand knowledge
    python main.py "..." --brand knowledge/brand/my_brand.json

    # With competitor research
    python main.py "..." --competitors knowledge/competitors/

    # Analysis only (skip synthesis)
    python main.py "..." --no-synthesis
"""

import argparse
import asyncio
import sys


def main():
    parser = argparse.ArgumentParser(
        description="Product Forge — Multi-agent product development pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "prompt",
        nargs="?",
        help="Product brief or description. Can also be piped via stdin.",
    )
    parser.add_argument(
        "--image", "-i",
        help="Path to a UI screenshot or reference image",
    )
    parser.add_argument(
        "--output", "-o",
        help="Output directory (default: output/<timestamp>/)",
    )
    parser.add_argument(
        "--quick", "-q",
        action="store_true",
        help="Quick mode: skip cross-review and synthesis (Phase 1 only)",
    )
    parser.add_argument(
        "--no-synthesis",
        action="store_true",
        help="Skip synthesis phase (run Phase 1 + 2 only)",
    )
    parser.add_argument(
        "--no-review",
        action="store_true",
        help="Skip cross-review phase (run Phase 1 + 3 only)",
    )
    # Knowledge pack flags
    parser.add_argument(
        "--brand",
        help="Path to brand JSON file (e.g., knowledge/brand/my_brand.json)",
    )
    parser.add_argument(
        "--competitors",
        help="Path to competitors directory (e.g., knowledge/competitors/)",
    )
    parser.add_argument(
        "--community",
        help="Path to community voice JSON file (e.g., knowledge/community/community_voice.json)",
    )

    args = parser.parse_args()

    # Get prompt from args or stdin
    prompt = args.prompt
    if not prompt and not sys.stdin.isatty():
        prompt = sys.stdin.read().strip()

    if not prompt:
        parser.print_help()
        print("\nError: Please provide a product brief as an argument or via stdin.")
        sys.exit(1)

    print("=" * 60)
    print(" Product Forge")
    print("=" * 60)
    print(f"\nPrompt: {prompt[:200]}{'...' if len(prompt) > 200 else ''}")
    if args.image:
        print(f"Image:  {args.image}")
    if args.brand:
        print(f"Brand:  {args.brand}")
    if args.competitors:
        print(f"Competitors: {args.competitors}")
    if args.community:
        print(f"Community: {args.community}")

    skip_review = args.quick or args.no_review
    skip_synthesis = args.quick or args.no_synthesis

    phases = []
    if True:
        phases.append("Individual Analysis")
    if not skip_review:
        phases.append("Cross-Review")
    if not skip_synthesis:
        phases.append("Synthesis")
    print(f"Phases: {' -> '.join(phases)}")

    from pipeline import run_pipeline

    results = asyncio.run(run_pipeline(
        prompt=prompt,
        image_path=args.image,
        output_dir=args.output,
        skip_review=skip_review,
        skip_synthesis=skip_synthesis,
        brand_path=args.brand,
        competitors_dir=args.competitors,
        community_path=args.community,
    ))

    out_dir = results.get("output_dir", "output/")
    print(f"\n{'=' * 60}")
    print(f" Done! Output: {out_dir}/COMPLETE.md")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
