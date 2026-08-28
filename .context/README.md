# Repository Context Engine

The append-only `sessions.jsonl` file is the authoritative cross-session record.
`CURRENT.md` is generated from that log for fast startup reading.

Record one verified session:

```text
python scripts/context_engine.py record \
  --objective "Implement a scoped change" \
  --summary "Changed the validated component." \
  --decision "Preserved the existing tenant boundary." \
  --file "path/to/file.py" \
  --verification "pytest path/to/test.py::passed::All targeted tests passed." \
  --next-step "Continue with the next acceptance gate."
```

Read or validate the context:

```text
python scripts/context_engine.py show
python scripts/context_engine.py validate
```

If the renderer changes, regenerate only the derived view with
`python scripts/context_engine.py refresh`; this never rewrites the JSONL log.

Rules:

- Record only facts verified during the session.
- Use `failed`, `skipped`, or `not_run` honestly when a gate did not pass.
- Never store credentials, tokens, raw environment values, personal data, or raw prompts.
- Do not edit `sessions.jsonl` or `CURRENT.md` manually.
- Live repository state always overrides stale context.
