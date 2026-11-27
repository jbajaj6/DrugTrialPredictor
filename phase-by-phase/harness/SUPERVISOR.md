# Bounded supervisor foundation

`supervisor.py` is a small, external, SQLite-backed launch gate. It does not run
anything on import, `handoff`, or `run --dry-run`. The database and all attempt
outputs should be placed in a new, ignored run directory; never reuse an output
path. The CLI prints only sanitized state, not raw App Server account responses.

The quota preflight follows the documented App Server `initialize` →
`initialized` → `account/rateLimits/read` protocol. It searches both `primary`
and `secondary` for the `codex` 10,080-minute bucket, rejects absent, stale,
reached, or contradictory readings, and checks projected usage plus a separate
in-flight margin. During a running CLI session, it rechecks usage about every
30 seconds and terminates the session if the check fails. A projected percentage
is an operator-supplied conservative bound, **not** a token or time conversion;
the polling interval does not guarantee a hard quota floor against sudden usage.
The default reserve is 7% remaining, and a run may explicitly set 5% following
the user's current instruction. The stricter 10% mode uses the same option.

Before a real launch, the supervisor checks `codex login status` for ChatGPT
authentication and confirms the requested model's exact slug and optional
reasoning effort in the refreshed `codex debug models` JSON catalog. It strips API-key environment variables from
child processes, invokes `codex exec --model ... --sandbox workspace-write --json
--ephemeral`, and requires both exit zero and a `turn.completed` event. It never
passes an approval override, `--trust`, `--ignore-rules`, full-access sandbox, or
an automatic account reset. Project trust and any approval requests remain with
the ordinary Codex CLI policy. The CLI model selection does not change this
chat's model. On 2026-11-27 the supervisor completed its first real bounded
task, `B19_AUDIT`, and independently accepted the audit-only result; see
[B19 independent evaluation](B19_INDEPENDENT_EVALUATION.md). This validates
one launch/evaluation path, not unattended dispatch or actual orphan recovery.

Example, after writing a task-specific prompt in a new run directory:

```bash
python3 phase-by-phase/harness/supervisor.py --db RUN/state.sqlite add TASK_ID \
  --kind structured --prompt-file RUN/task.txt --model gpt-6.1-sol \
  --max-seconds 900 --projected-percent 3
python3 phase-by-phase/harness/supervisor.py --db RUN/state.sqlite run TASK_ID \
  --strategy initial --output RUN/attempt-1.jsonl --reserve-percent 5 --dry-run
python3 phase-by-phase/harness/supervisor.py --db RUN/state.sqlite handoff
```

Remove `--dry-run` only for an authorized, monitored launch. A real run writes
one new JSONL attempt artifact. A successful process remains
`awaiting_evaluation`; a separate evaluator supplies a nonempty evidence file
through `evaluate ... --evaluator NAME --verdict accept|reject --evidence FILE`.
`status` gives a short human summary. This foundation launches one bounded task
at a time; it does not contain an unattended queue dispatcher. It does not
request a `fast` service tier, but it also cannot verify that the CLI default
equates to a particular “Standard” speed.
Accepting `STRUCTURED_READY` specifically
requires an evaluator JSON file with `scientific_readiness: true` and a nonempty
`evidence` field; a generic engineering test pass is insufficient.
`recover` deterministically marks any in-flight attempt `interrupted_unreviewed`
after a supervisor restart and never relaunches it. Since a child process may
outlive the supervisor, the supervisor records its process-group ID immediately
after spawning, attempts to kill that group on Ctrl-C or a bounded-run stop,
and still requires the operator to inspect for an orphaned Codex process,
record a nonempty inspection file, and run `acknowledge-interruption TASK_ID
--evidence FILE` before a new attempt. A rejected, failed, or interrupted
attempt may be followed only by a distinct named strategy, with at most four
total attempts. Text and memo tasks require an independently accepted
`STRUCTURED_READY` task; scientific readiness must not be inferred from a code
test pass. Dependency tasks must be accepted first.

The App Server and non-interactive CLI interfaces are documented in the
[Codex App Server](https://learn.chatgpt.com/docs/app-server),
[non-interactive mode](https://learn.chatgpt.com/docs/non-interactive-mode), and
[CLI reference](https://learn.chatgpt.com/docs/cli/reference). This foundation
does not assert an autonomous overnight run, predictive result, or final-holdout
access.
