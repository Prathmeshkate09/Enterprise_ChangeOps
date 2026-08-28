# Enterprise ChangeOps Session Context

At the start of every non-trivial repository session:

1. Run `python scripts/context_engine.py show` and read `.context/CURRENT.md`.
2. Inspect the live repository state before relying on recorded context.
3. Treat context as a continuity aid, never as stronger evidence than source, tests, Git, or live services.

Before finishing every non-trivial repository session:

1. Run the relevant verification gates.
2. Append one context record with `python scripts/context_engine.py record`.
3. Include the objective, completed work, material decisions, files changed, exact verification outcomes, blockers, and next steps.
4. Run `python scripts/context_engine.py validate`.

Never record credentials, tokens, raw environment values, personal data, or raw prompts. Never claim a test passed unless it ran successfully in that session. The context log is append-only; use a corrective new record instead of rewriting prior entries.
