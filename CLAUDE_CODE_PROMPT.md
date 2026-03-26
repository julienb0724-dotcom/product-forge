# Product Forge v2 — Claude Code Bootstrap Prompt

## Context

You are setting up **Product Forge v2**, a multi-agent product development system with three modules:

1. **`agents.py`** — Five specialist agents (Jony/Design, Maya/PM, Kai/Architect, Elena/Strategist, Dev/Engineer) with deep personas, operational heuristics, anti-patterns, cross-agent awareness, and calibrated confidence
2. **`deliberation.py`** — Two systems:
   - **Mailbox Deliberation**: Typed inter-agent messages (challenge, question, dependency_flag, scope_concern, risk_escalation, endorsement) with priority routing, response tracking, and revision cycles. Agents post challenges -> recipients respond -> senders accept/reject -> unresolved items escalate to synthesis.
   - **AutoResearch Loop**: Adapted from Karpathy's autoresearch pattern. Maya runs autonomous web research rounds before producing her PRD. Research state tracks coverage across 8 dimensions (market_validation, competitive_intel, user_pain_confirmation, pricing_signals, regulatory_landscape, technology_landscape, distribution_channels, business_model_evidence). Each round targets the biggest gap, runs searches, synthesizes findings, keeps/discards based on quality bar, and loops until coverage thresholds are met or max rounds hit.
3. **`knowledge.py`** — Runtime knowledge injection system. Structured domain knowledge loaded per-agent via KnowledgePacks. Includes:
   - **CommunityVoiceProfile**: Synthesized Reddit/forum/app review themes with representative quotes, feature requests, complaints, and user language patterns
   - **BrandSystem**: Structured brand guidelines (colors, typography, spacing, tone of voice, terminology) injected as hard constraints for Jony and Dev
   - **CompetitorDossier**: Deep competitor profiles for Elena and Maya
   - **Technical specs**: Hardware/API documentation for Kai and Dev
   - **Generic directory-based loading**: All knowledge loaded from `knowledge/` subdirectories (brand, community, competitors, regulatory, technical)

## Project Structure

```
product-forge/
├── agents.py              # Agent personas, expertise, output formats, prompt builders
├── deliberation.py        # Mailbox system + AutoResearch loop + pipeline orchestration
├── knowledge.py           # Knowledge packs, community voice, brand system, competitor dossiers
├── pipeline.py            # Multi-phase pipeline runner (Phase 1-3)
├── main.py                # CLI entry point with knowledge pack flags
├── api.py                 # FastAPI wrapper for the pipeline
├── mine_community.py      # Community voice mining script (configurable)
├── build_competitors.py   # Competitor dossier builder (configurable)
├── knowledge/             # Runtime knowledge files (loaded by knowledge.py)
│   ├── brand/             # Brand guidelines JSON files
│   ├── community/         # Community voice profile JSON files
│   ├── competitors/       # Competitor dossier JSON files
│   ├── regulatory/        # Regulatory briefing JSON files
│   └── technical/         # Technical specification JSON files
├── research_agendas/      # Human-authored research strategies
└── output/                # Pipeline outputs per run
    └── {timestamp}/
        ├── phase1_*.md
        ├── phase2_reviews.md
        ├── phase3_synthesis.md
        └── COMPLETE.md
```

## Knowledge Pack System

Knowledge is loaded generically from the `knowledge/` directory structure. Any JSON file placed in the appropriate subdirectory will be loaded and injected into the relevant agents' prompts.

### Loading Priority
- `knowledge/brand/` -> Jony (designer) and Dev (engineer)
- `knowledge/community/` -> Maya (PM) and Elena (strategist)
- `knowledge/competitors/` -> Elena (strategist), Maya (PM), and Jony (designer)
- `knowledge/regulatory/` -> Elena (strategist)
- `knowledge/technical/` -> Kai (architect) and Dev (engineer)

### CLI Overrides
- `--brand path/to/brand.json` — Override brand knowledge source
- `--competitors path/to/dir/` — Override competitors directory
- `--community path/to/community.json` — Override community voice source

## Architecture Notes

- **Prompt injection order**: persona -> knowledge_pack -> AGENT_META -> output_format -> brief
- **Knowledge packs are per-agent**: see `AGENT_KNOWLEDGE_ASSIGNMENTS` in knowledge.py
- **Token budget**: 8K tokens max per knowledge pack to avoid context window pressure
- **Research loop cap**: 5 rounds max, 60% coverage threshold per dimension
- **Deliberation cap**: 3 rounds max, BLOCKING messages must resolve or escalate
- **All JSON parsing should be fault-tolerant**: agents may produce slightly malformed JSON — use regex extraction as fallback

## Files

The module files (`agents.py`, `deliberation.py`, `knowledge.py`, `pipeline.py`, `main.py`, `api.py`) are production-ready Python — do not restructure them, extend them.
