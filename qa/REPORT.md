# MTG Deck Builder QA Report

- Generated at: `20260418T212335Z`
- API base: `http://127.0.0.1:8010`

## Summary

- Scenario count: `10`
- Heuristic verdicts: `{'strong': 10}`
- LLM statuses: `{'completed': 10}`
- Dimension averages: `{'archetype_match_quality': 92, 'package_coherence': 97, 'recognizable_shell': 88, 'commander_plausibility': 96}`
- Retrieval failures: `[]`
- Commander failures: `[]`
- Legality failures: `[]`

## Scenario Results

### standard-aggro

- Verdict: `strong`
- Dimension scores: `{'archetype_match_quality': 100, 'package_coherence': 97, 'recognizable_shell': 90, 'commander_plausibility': 100}`
- LLM status: `completed`
- LLM verdict: `strong`
- Retrieval issues: `[]`
- Commander issues: `[]`
- Main issues: `['Role summary is too shallow.', 'Interaction density is light for the format; the deck may fold to opposing haymakers.']`

### standard-control

- Verdict: `strong`
- Dimension scores: `{'archetype_match_quality': 82, 'package_coherence': 100, 'recognizable_shell': 85, 'commander_plausibility': 100}`
- LLM status: `completed`
- LLM verdict: `strong`
- Retrieval issues: `[]`
- Commander issues: `[]`
- Main issues: `[]`

### modern-prowess

- Verdict: `strong`
- Dimension scores: `{'archetype_match_quality': 89, 'package_coherence': 100, 'recognizable_shell': 87, 'commander_plausibility': 100}`
- LLM status: `completed`
- LLM verdict: `strong`
- Retrieval issues: `[]`
- Commander issues: `[]`
- Main issues: `[]`

### modern-midrange-budget

- Verdict: `strong`
- Dimension scores: `{'archetype_match_quality': 100, 'package_coherence': 100, 'recognizable_shell': 90, 'commander_plausibility': 100}`
- LLM status: `completed`
- LLM verdict: `strong`
- Retrieval issues: `[]`
- Commander issues: `[]`
- Main issues: `['Role summary is too shallow.']`

### legacy-tempo

- Verdict: `strong`
- Dimension scores: `{'archetype_match_quality': 86, 'package_coherence': 100, 'recognizable_shell': 86, 'commander_plausibility': 100}`
- LLM status: `completed`
- LLM verdict: `strong`
- Retrieval issues: `[]`
- Commander issues: `[]`
- Main issues: `["Mana base may not support the deck's U requirements cleanly; only 6 likely sources were detected."]`

### legacy-combo

- Verdict: `strong`
- Dimension scores: `{'archetype_match_quality': 82, 'package_coherence': 90, 'recognizable_shell': 85, 'commander_plausibility': 100}`
- LLM status: `completed`
- LLM verdict: `strong`
- Retrieval issues: `[]`
- Commander issues: `[]`
- Main issues: `[]`

### commander-ramp

- Verdict: `strong`
- Dimension scores: `{'archetype_match_quality': 100, 'package_coherence': 100, 'recognizable_shell': 90, 'commander_plausibility': 85}`
- LLM status: `completed`
- LLM verdict: `strong`
- Retrieval issues: `[]`
- Commander issues: `[]`
- Main issues: `[]`

### commander-lifegain

- Verdict: `strong`
- Dimension scores: `{'archetype_match_quality': 100, 'package_coherence': 100, 'recognizable_shell': 90, 'commander_plausibility': 85}`
- LLM status: `completed`
- LLM verdict: `strong`
- Retrieval issues: `[]`
- Commander issues: `[]`
- Main issues: `[]`

### commander-tribal

- Verdict: `strong`
- Dimension scores: `{'archetype_match_quality': 100, 'package_coherence': 81, 'recognizable_shell': 90, 'commander_plausibility': 85}`
- LLM status: `completed`
- LLM verdict: `weak`
- Retrieval issues: `[]`
- Commander issues: `[]`
- Main issues: `['Role balance score is weak.', 'Commander decks usually want more ramp; this list may start too slowly.', 'Interaction density is light for the format; the deck may fold to opposing haymakers.']`

### modern-narrow-theme

- Verdict: `strong`
- Dimension scores: `{'archetype_match_quality': 82, 'package_coherence': 100, 'recognizable_shell': 85, 'commander_plausibility': 100}`
- LLM status: `completed`
- LLM verdict: `moderate`
- Retrieval issues: `[]`
- Commander issues: `[]`
- Main issues: `["Mana base may not support the deck's B requirements cleanly; only 0 likely sources were detected.", 'Estimated deck price is about $127.05, which is above the requested budget of $120.00.']`

