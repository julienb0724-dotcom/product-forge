# Research Agenda: Making Emporia's App Agentic (Cortana-Inspired)

## Brief

Emporia Energy has a Flutter mobile app that monitors home energy (circuit-level via Vue), controls EV chargers, manages smart plugs, and now manages battery storage (PV+ES). The app is well-built but fundamentally REACTIVE — it shows data and lets users manually control devices.

We want to explore making it AGENTIC — an AI-powered system that autonomously optimizes energy usage, learns the home's thermal behavior, coordinates devices, and earns money through grid services. The inspiration is "Cortana," a home intelligence system built on FastAPI + Claude that already does this.

## Cortana System Architecture (what exists and works)

Cortana runs on a VPS and orchestrates:

1. **Autonomous Energy Optimizer** (`services/optimizer.py`)
   - Runs every 30 minutes via cron
   - Gathers full system state: weather forecast (12hr), thermostat status, Tesla state, Emporia circuits, COP efficiency, thermal predictions, TOU rates
   - Feeds everything to Claude Sonnet in a tool-use loop
   - Claude makes coordinated decisions: adjust thermostat, start/stop Tesla charging, shed smart plugs, adjust EV charger amps
   - Guardrails enforce safety bounds (66-74°F, max ±3°F/cycle, charge limits)
   - Falls back to rule-based scheduler if Claude API fails
   - Anti-flip-flop: cooldown + last-decision tracking prevents oscillation

2. **Thermal Learning Model** (`services/thermal.py`)
   - Logs 30-minute snapshots to Redis (indoor/outdoor temp, setpoint, HVAC calling, wind, COP)
   - Fits heat loss coefficient (k), wind factor (w), heat gain rate via least-squares
   - Predicts 12-hour indoor temperatures fed into optimizer prompt
   - Auto-refits every 6 hours after 24h bootstrap

3. **Demand Response** (`services/demand_response.py`)
   - Monitors home load during TOU peak (3-7pm weekdays)
   - Auto-sheds smart plugs when load exceeds threshold
   - Reduces EV charger amps during high-load periods
   - Restores after peak ends

4. **COP-Aware Heating** (`services/efficiency.py`)
   - Heat pump COP curve based on outdoor temperature
   - Cost-per-degree calculations injected into optimizer prompt
   - Pre-heat during high-COP hours, coast during low-COP

5. **Smart EV Charging** (`services/charge_plan.py`)
   - Departure-aware charge windows
   - TOU avoidance (shift charging to overnight)
   - Overnight preference (midnight-6am cheapest)

6. **Rate Plan Optimization** (`services/rate_advisor.py`)
   - Simulates bills across 4 Xcel rate plans using actual Emporia data
   - Recommends optimal plan + load shifting strategy

7. **Arrival Pre-conditioning** (`services/arrival.py`)
   - Geo-aware state machine: HOME → AWAY → APPROACHING → PRECONDITIONING
   - Setback when away, pre-heat when approaching

8. **Proactive Notifications** via Telegram
   - Anomaly detection (unusual circuit usage)
   - Weekly energy digest
   - Optimizer action notifications

## Emporia App Codebase (what exists)

Flutter app with BLoC pattern, event-driven architecture:
- **Battery Page** (`battery_page.dart`) — PV+ES control with energy flow diagram
- **Device monitoring** — real-time circuit-level data
- **EV Charger control** — charge rate, scheduling
- **Smart Plug control** — on/off, scheduling
- **Usage analytics** — historical charts, cost tracking
- **Energy Management** — schedules, TOU awareness
- **Brand**: Emporia Green #689B41, Roboto, warm/approachable "Innocent Sage"

## Questions for the Team

### For Maya (PM)
- What's the V1 for an "agentic" Emporia app? What's the minimum AI feature that proves value?
- How do you onboard a non-technical homeowner into trusting AI control of their thermostat/battery?
- What's the activation metric for an AI energy feature?
- What features from Cortana are most valuable for Emporia's target user (average homeowner, not techie)?

### For Kai (Architect)
- How would you architect an optimization loop in a mobile app + cloud backend?
- Edge vs cloud for the AI decision loop? Lambda on a schedule vs on-device?
- How do you handle the thermal learning model at scale (millions of homes)?
- What's the data pipeline for feeding circuit-level data into an optimization model?

### For Elena (Strategist)
- Who else is doing agentic energy management? (Lunar, Tesla, Span, etc.)
- What utility programs exist for residential demand response / VPP?
- What's the regulatory landscape for automated grid services?
- Is "AI energy optimizer" a differentiator or table stakes by 2027?

### For Jony (Designer)
- How do you show AI decisions transparently without overwhelming the user?
- What's the UX for "the app just saved you $2.40 while you slept"?
- How do you build trust in autonomous control?
- What does "set and forget" look like in the Emporia design language?

### For Dev (Engineer)
- How would you integrate a Cortana-like optimizer into the existing Flutter + BLoC architecture?
- What Dart/Flutter patterns work for real-time AI decision display?
- How do you handle offline mode for an AI-optimized system?
- What's the migration path from the current manual-control UX to AI-assisted?
