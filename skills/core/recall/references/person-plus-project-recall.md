# Person plus project recall pattern

Use this reference when Nick asks to recall a named person together with a project, repo, agent, venture, or infrastructure idea.

## Trigger

Examples:
- "Gil Penchina, my relationship with him, and the personal AI infrastructure ideas"
- "Recall Alice and the product ideas we discussed"
- "What did we know about X and the repo/prototype around them?"

## Pattern

1. Search sessions for the named person and project terms, but expect noisy results.
2. Search durable entity files next, especially:
   - current profile cortex people and ventures
   - migrated OpenClaw memory people, topics, ventures, daily notes
   - adjacent specialist profiles if the person belongs to a business or financial workstream
3. Inspect local repos or project directories whose names match the person/project. Prefer README, WALKTHROUGH, AGENTS/CLAUDE.md, knowledge/, docs/, architecture/, and agent specs before source code.
4. Separate:
   - relationship context, why this person matters to Nick
   - the person's taste, trust model, and constraints
   - artifacts already built
   - concrete next actions or demos
5. Produce an actionable reconstruction, not just historical notes. If the user has a near-term meeting, include a meeting agenda, suggested demo order, and what to ask the person for next.
6. For useful multi-source syntheses, write a concise artifact under the active profile's artifacts/ directory and return its path.

## Pitfalls

- Do not treat cron/email steward hits as the answer just because they mention the person. Those are often incidental.
- Do not flatten relationship context into business facts. Nick often asks for the human/emotional context first.
- Do not present raw session archaeology. Synthesize into what Nick can actually do next.
- If there is a repo, inspect it. The repo may contain the most concrete action menu even when sessions are sparse.

## Example from Gil plus Bob Steele

Gil recall required combining:
- relationship memory files for Gil as friend, advisor, client, housemate, and negotiation support
- <agent-d> financial memory for the current arrangement
- gilpai/gilpia repos for Personal AI Infrastructure specs
- cortex venture notes for Bob Steele persona

The useful output was a launch menu: strongest near-term demos, Bob Steele voice, a 7-day read-only pilot, source paths, and a meeting agenda.