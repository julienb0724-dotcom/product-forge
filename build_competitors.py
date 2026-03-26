#!/usr/bin/env python3
"""
Product Forge — Competitor Dossier Builder

Uses Claude to research and populate CompetitorDossier objects for
any set of competitors in any industry.

Usage:
    python build_competitors.py --competitors "Sense,Span,Tesla Energy" --industry "home energy monitoring"
    python build_competitors.py --competitors "Fitbit,Apple Watch,Garmin" --industry "fitness wearables"
    python build_competitors.py --competitors "Notion,Obsidian,Roam" --industry "note-taking apps"

Requires: ANTHROPIC_API_KEY

Output: knowledge/competitors/{name}.json
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

try:
    import anthropic
except ImportError:
    print("pip install anthropic")
    sys.exit(1)

sys.path.insert(0, str(Path(__file__).parent))
from knowledge import CompetitorDossier

OUTPUT_DIR = Path(__file__).parent / "knowledge" / "competitors"
MODEL = "claude-sonnet-4-6"


async def research_competitor(
    client: anthropic.AsyncAnthropic,
    competitor_name: str,
    industry: str,
    product_context: str = "",
) -> dict:
    """Research a single competitor and return structured dossier data."""
    context_block = ""
    if product_context:
        context_block = f"Context: {product_context}\n\n"

    resp = await client.messages.create(
        model=MODEL,
        max_tokens=4096,
        system=(
            f"You are a competitive intelligence analyst specializing in {industry}. "
            "Produce accurate, specific competitive dossiers. Reference real products, real prices, "
            "real partnerships. Do not fabricate data — if unsure, say 'estimated' or 'unconfirmed'.\n\n"
            "Output ONLY a valid JSON object — no markdown, no explanation."
        ),
        messages=[{
            "role": "user",
            "content": (
                f"Build a competitive dossier for **{competitor_name}**.\n"
                f"Industry: {industry}\n"
                f"{context_block}"
                "Research this company and return a JSON object with these exact fields:\n"
                "```json\n"
                "{\n"
                '  "company_name": "...",\n'
                '  "website": "...",\n'
                '  "products": [{"name": "...", "price": "...", "category": "..."}],\n'
                '  "positioning": "one paragraph on their strategy",\n'
                '  "target_customer": "...",\n'
                '  "pricing_model": "...",\n'
                '  "strengths": ["specific strength 1", "..."],\n'
                '  "weaknesses": ["specific weakness 1", "..."],\n'
                '  "recent_moves": ["last 6 months: launches, partnerships, funding"],\n'
                '  "ecosystem_integrations": ["what they connect to"],\n'
                '  "data_moat": "what proprietary data advantage they have",\n'
                '  "app_store_rating": 4.2,\n'
                '  "estimated_user_base": "...",\n'
                '  "key_differentiator": "...",\n'
                '  "threat_assessment": "how this competitor threatens new entrants in the space"\n'
                "}\n"
                "```"
            ),
        }],
    )

    text = resp.content[0].text.strip()

    # Extract JSON
    import re
    json_match = re.search(r'\{[\s\S]*\}', text)
    if json_match:
        try:
            return json.loads(json_match.group())
        except json.JSONDecodeError:
            pass

    # Fallback: try the whole text
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        print(f"  Warning: could not parse JSON for {competitor_name}")
        return {"company_name": competitor_name, "website": "",
                "error": "Failed to parse research output"}


async def build_all_dossiers(
    competitor_names: list[str],
    industry: str,
    output_dir: Path,
    product_context: str = "",
):
    """Research all competitors in parallel."""
    client = anthropic.AsyncAnthropic()

    print(f"Researching {len(competitor_names)} competitors in '{industry}'...")

    tasks = [
        research_competitor(client, name, industry, product_context)
        for name in competitor_names
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    output_dir.mkdir(parents=True, exist_ok=True)

    for name, result in zip(competitor_names, results):
        name_slug = name.lower().replace(" ", "_")

        if isinstance(result, Exception):
            print(f"  {name}: FAILED — {result}")
            continue

        # Save raw JSON
        output_path = output_dir / f"{name_slug}.json"
        with open(output_path, "w") as f:
            json.dump(result, f, indent=2)

        # Validate by loading into CompetitorDossier
        try:
            dossier = CompetitorDossier(
                company_name=result.get("company_name", name),
                website=result.get("website", ""),
                products=result.get("products", []),
                positioning=result.get("positioning", ""),
                target_customer=result.get("target_customer", ""),
                pricing_model=result.get("pricing_model", ""),
                strengths=result.get("strengths", []),
                weaknesses=result.get("weaknesses", []),
                recent_moves=result.get("recent_moves", []),
                ecosystem_integrations=result.get("ecosystem_integrations", []),
                data_moat=result.get("data_moat", ""),
                app_store_rating=result.get("app_store_rating"),
                estimated_user_base=result.get("estimated_user_base"),
                key_differentiator=result.get("key_differentiator", ""),
                threat_assessment=result.get("threat_assessment", ""),
            )
            ks = dossier.to_knowledge_source()
            print(f"  {name}: {len(result.get('products', []))} products, "
                  f"{len(result.get('strengths', []))} strengths, "
                  f"{ks.token_estimate} tokens -> {output_path.name}")
        except Exception as e:
            print(f"  {name}: saved but validation failed: {e}")


def main():
    parser = argparse.ArgumentParser(
        description="Build competitor dossiers using AI research",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--competitors", "-c",
        required=True,
        help="Comma-separated list of competitor names (e.g., 'Sense,Span,Tesla Energy')",
    )
    parser.add_argument(
        "--industry", "-i",
        required=True,
        help="Industry context (e.g., 'home energy monitoring', 'fitness wearables')",
    )
    parser.add_argument(
        "--context",
        default="",
        help="Additional product context for more targeted research",
    )
    parser.add_argument(
        "--output-dir", "-o",
        default=None,
        help="Output directory for dossier JSON files (default: knowledge/competitors/)",
    )

    args = parser.parse_args()

    competitor_names = [c.strip() for c in args.competitors.split(",") if c.strip()]
    output_dir = Path(args.output_dir) if args.output_dir else OUTPUT_DIR

    asyncio.run(build_all_dossiers(
        competitor_names=competitor_names,
        industry=args.industry,
        output_dir=output_dir,
        product_context=args.context,
    ))
    print(f"\nDossiers saved to {output_dir}/")


if __name__ == "__main__":
    main()
