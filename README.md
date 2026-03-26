# Product Forge

Multi-agent product development system. 5 specialist AI agents (Design, PM, Architecture, Strategy, Engineering) analyze your product brief through independent research, cross-review deliberation, and synthesized recommendations.

## Quick Start

```bash
pip install anthropic
export ANTHROPIC_API_KEY=your_key

# Run with just a prompt
python main.py "Build a fitness tracking app for seniors"

# Quick mode (Phase 1 only, faster)
python main.py "..." --quick

# With brand knowledge
python main.py "..." --brand knowledge/brand/my_brand.json

# With competitor research
python main.py "..." --competitors knowledge/competitors/
```

## API Mode

```bash
uvicorn api:app --port 8100

# Sync call
curl -X POST http://localhost:8100/forge \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Build a ...", "quick": true}'

# Async call
curl -X POST http://localhost:8100/forge/async \
  -d '{"prompt": "Build a ..."}'
curl http://localhost:8100/forge/{job_id}
```

## Agents

| Agent | Role | Focus |
|-------|------|-------|
| **Jony** | Design | UI/UX, design systems, interaction patterns |
| **Maya** | PM | User research, JTBD, requirements, prioritization |
| **Kai** | Architect | Technical architecture, scalability, trade-offs |
| **Elena** | Strategist | Go-to-market, positioning, business model |
| **Dev** | Engineer | Implementation plan, testing, deployment |

## Knowledge Packs

Optional domain knowledge to improve agent outputs:

- `knowledge/brand/` — Brand guidelines, voice, visual identity
- `knowledge/community/` — User feedback, forum insights, pain points
- `knowledge/competitors/` — Competitor analysis, feature matrices
- `knowledge/regulatory/` — Industry regulations, compliance requirements
- `knowledge/technical/` — API specs, platform constraints, integrations

## Pipeline Phases

1. **Individual Analysis** — Each agent produces their deliverable independently
2. **Cross-Review** — Agents challenge each other's work (2-3 rounds)
3. **Revision** — Agents incorporate feedback
4. **Synthesis** — Combined into a unified product brief

Use `--quick` for Phase 1 only. Use `--no-synthesis` or `--no-review` to skip phases.
