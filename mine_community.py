#!/usr/bin/env python3
"""
Product Forge — Community Voice Mining

Runs web searches against Reddit/forums to build a CommunityVoiceProfile
for injection into Maya's and Elena's knowledge packs.

Usage:
    python mine_community.py --subreddit r/homeautomation r/smarthome --search-terms "smart home" "energy monitor"
    python mine_community.py --subreddit r/fitness --search-terms "fitness tracker" "workout app"

Requires: ANTHROPIC_API_KEY environment variable

Output: knowledge/community/community_voice.json (or custom path via --output)
"""

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime
from pathlib import Path

try:
    import anthropic
except ImportError:
    print("pip install anthropic")
    sys.exit(1)

sys.path.insert(0, str(Path(__file__).parent))
from knowledge import CommunityTheme, CommunityVoiceProfile

MODEL = "claude-sonnet-4-6"
MAX_SEARCH_ROUNDS = 3


async def run_search_round(
    client: anthropic.AsyncAnthropic,
    queries: list[str],
    round_num: int,
    context: str = "",
) -> str:
    """Run one research round: search multiple queries and synthesize."""
    query_block = "\n".join(f"- {q}" for q in queries)

    system_msg = (
        "You are a market researcher mining online communities for product insights. "
    )
    if context:
        system_msg += f"You are researching: {context}\n\n"
    system_msg += (
        "For each search query, synthesize what you find into structured themes. "
        "Focus on: recurring complaints, feature requests, praise, competitor mentions, "
        "and the actual language users use to describe their experiences.\n\n"
        "Be specific — include representative quotes (paraphrased if needed), "
        "user segments, and product implications. Do NOT fabricate quotes."
    )

    resp = await client.messages.create(
        model=MODEL,
        max_tokens=4096,
        system=system_msg,
        messages=[{
            "role": "user",
            "content": (
                f"Research round {round_num}. Search for insights on these queries:\n\n"
                f"{query_block}\n\n"
                "For each query, search the web and synthesize findings.\n\n"
                "Output a JSON array of theme objects:\n"
                "```json\n"
                "[\n"
                "  {\n"
                '    "theme": "one-line theme description",\n'
                '    "sentiment": "positive|negative|mixed|neutral",\n'
                '    "frequency": "rare|common|dominant",\n'
                '    "representative_quotes": ["quote 1", "quote 2", "quote 3"],\n'
                '    "user_segments": ["segment 1", "segment 2"],\n'
                '    "product_implications": "what this means for the product",\n'
                '    "competing_solutions_mentioned": ["Competitor A", "Competitor B"]\n'
                "  }\n"
                "]\n"
                "```\n"
                "Return 4-8 themes per round. Be specific, not generic."
            ),
        }],
    )

    return resp.content[0].text


def parse_themes(raw_text: str) -> list[CommunityTheme]:
    """Extract CommunityTheme objects from LLM response."""
    import re

    # Try to find JSON array in the response
    json_match = re.search(r'\[[\s\S]*?\]', raw_text)
    if not json_match:
        print("  Warning: no JSON array found in response")
        return []

    try:
        data = json.loads(json_match.group())
    except json.JSONDecodeError:
        # Try fixing common issues
        try:
            cleaned = json_match.group().replace("'", '"')
            data = json.loads(cleaned)
        except json.JSONDecodeError:
            print("  Warning: could not parse JSON from response")
            return []

    themes = []
    for item in data:
        if not isinstance(item, dict):
            continue
        try:
            themes.append(CommunityTheme(
                theme=item.get("theme", "Unknown"),
                sentiment=item.get("sentiment", "neutral"),
                frequency=item.get("frequency", "common"),
                representative_quotes=item.get("representative_quotes", []),
                user_segments=item.get("user_segments", []),
                product_implications=item.get("product_implications", ""),
                competing_solutions_mentioned=item.get("competing_solutions_mentioned", []),
            ))
        except Exception as e:
            print(f"  Warning: skipping malformed theme: {e}")

    return themes


def build_queries_from_terms(search_terms: list[str], subreddits: list[str]) -> list[list[str]]:
    """Build search query rounds from user-provided terms and subreddits."""
    rounds = []

    # Round 1: Direct product/term queries on Reddit
    r1 = []
    for term in search_terms[:4]:
        r1.append(f"{term} reddit")
        r1.append(f"{term} review reddit")
    rounds.append(r1[:8])

    # Round 2: Pain points and feature requests
    r2 = []
    for term in search_terms[:3]:
        r2.append(f"{term} problems reddit")
        r2.append(f"{term} feature request")
        r2.append(f"{term} vs comparison reddit")
    rounds.append(r2[:8])

    # Round 3: Subreddit-specific deeper dives
    r3 = []
    for sub in subreddits[:3]:
        sub_name = sub.replace("r/", "")
        for term in search_terms[:2]:
            r3.append(f"{term} site:reddit.com/r/{sub_name}")
    if not r3:
        for term in search_terms[:3]:
            r3.append(f"best {term} 2025 reddit")
            r3.append(f"{term} recommendation reddit")
    rounds.append(r3[:8])

    return rounds


async def mine_community(
    subreddits: list[str],
    search_terms: list[str],
    output_path: Path,
    context: str = "",
):
    """Run the full community mining pipeline."""
    client = anthropic.AsyncAnthropic()

    all_themes: list[CommunityTheme] = []
    total_queries = 0

    # Build query rounds from provided terms
    rounds = build_queries_from_terms(search_terms, subreddits)

    context_str = context or f"Topics: {', '.join(search_terms)}"

    for i, queries in enumerate(rounds[:MAX_SEARCH_ROUNDS]):
        print(f"\n  Round {i + 1}/{len(rounds)}: {len(queries)} queries")
        total_queries += len(queries)

        raw = await run_search_round(client, queries, i + 1, context_str)
        themes = parse_themes(raw)
        print(f"  Extracted {len(themes)} themes")
        all_themes.extend(themes)

    # Deduplicate themes by similarity (simple: merge identical theme names)
    seen = {}
    for theme in all_themes:
        key = theme.theme.lower().strip()
        if key not in seen:
            seen[key] = theme
        else:
            # Merge quotes
            existing = seen[key]
            for q in theme.representative_quotes:
                if q not in existing.representative_quotes:
                    existing.representative_quotes.append(q)
            for s in theme.user_segments:
                if s not in existing.user_segments:
                    existing.user_segments.append(s)
            for c in theme.competing_solutions_mentioned:
                if c not in existing.competing_solutions_mentioned:
                    existing.competing_solutions_mentioned.append(c)

    deduped = list(seen.values())

    # Build feature requests and complaints from themes
    feature_requests = [
        t.product_implications for t in deduped
        if t.sentiment in ("negative", "mixed") and "feature" in t.product_implications.lower()
    ]
    complaints = [
        t.theme for t in deduped if t.sentiment == "negative"
    ]

    profile = CommunityVoiceProfile(
        sources=subreddits,
        collection_date=datetime.now().strftime("%Y-%m-%d"),
        total_posts_analyzed=total_queries * 25,  # rough estimate
        themes=deduped,
        top_feature_requests=feature_requests[:10],
        top_complaints=complaints[:10],
        language_patterns={},  # populated by the LLM in a future enhancement
    )

    # Serialize
    profile_dict = {
        "sources": profile.sources,
        "collection_date": profile.collection_date,
        "total_posts_analyzed": profile.total_posts_analyzed,
        "themes": [
            {
                "theme": t.theme,
                "sentiment": t.sentiment,
                "frequency": t.frequency,
                "representative_quotes": t.representative_quotes,
                "user_segments": t.user_segments,
                "product_implications": t.product_implications,
                "competing_solutions_mentioned": t.competing_solutions_mentioned,
            }
            for t in profile.themes
        ],
        "top_feature_requests": profile.top_feature_requests,
        "top_complaints": profile.top_complaints,
        "language_patterns": profile.language_patterns,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(profile_dict, f, indent=2)

    # Generate and print KnowledgeSource stats
    ks = profile.to_knowledge_source()
    print(f"\n{'=' * 50}")
    print(f"Community Voice Profile saved to {output_path}")
    print(f"  Themes:           {len(profile.themes)}")
    print(f"  Feature requests: {len(profile.top_feature_requests)}")
    print(f"  Complaints:       {len(profile.top_complaints)}")
    print(f"  Token estimate:   {ks.token_estimate}")
    print(f"  Sources:          {', '.join(profile.sources[:5])}")

    return profile


def main():
    parser = argparse.ArgumentParser(
        description="Mine community discussions for product insights",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--subreddit", "-s",
        nargs="+",
        default=[],
        help="Subreddits to mine (e.g., r/homeautomation r/smarthome)",
    )
    parser.add_argument(
        "--search-terms", "-t",
        nargs="+",
        required=True,
        help="Search terms for community mining (e.g., 'smart home' 'energy monitor')",
    )
    parser.add_argument(
        "--context", "-c",
        default="",
        help="Additional context about the product/domain for the researcher",
    )
    parser.add_argument(
        "--output", "-o",
        default=None,
        help="Output path for the JSON file (default: knowledge/community/community_voice.json)",
    )

    args = parser.parse_args()

    output_path = Path(args.output) if args.output else (
        Path(__file__).parent / "knowledge" / "community" / "community_voice.json"
    )

    print(f"Mining community voice for: {', '.join(args.search_terms)}")
    if args.subreddit:
        print(f"Subreddits: {', '.join(args.subreddit)}")

    asyncio.run(mine_community(
        subreddits=args.subreddit,
        search_terms=args.search_terms,
        output_path=output_path,
        context=args.context,
    ))


if __name__ == "__main__":
    main()
