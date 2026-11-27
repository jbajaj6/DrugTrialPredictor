# Persistent execution design (H2, in progress)

This document records design choices for the Leo/Giannis research harness. It is not evidence that a persistent overnight run or a model switch has occurred. The scientific source of truth remains the checked artifacts and [task ledger](TASK_LEDGER.md), not an agent's completion message.

## Official sources inspected

- Anthropic's [effective long-running harnesses](https://www.anthropic.com/research/effective-harnesses-for-long-running-agents) and [reference repository](https://github.com/anthropics/cwc-long-running-agents) motivate small bounded tasks, explicit environment initialization, and durable handoffs across context windows.
- Anthropic's [long-running app harness](https://www.anthropic.com/research/harness-design-long-running-apps) motivates separate planning/building/evaluation roles and executable acceptance checks.
- [Building effective agents](https://www.anthropic.com/research/building-effective-agents) motivates using a deterministic workflow when the steps are known and agent judgment only for open-ended diagnosis.
- [Demystifying evals](https://www.anthropic.com/research/demystifying-evals-for-ai-agents) motivates testing environment outcomes, not just grading agent text.
- [Parallel compiler agents](https://www.anthropic.com/research/building-c-compiler), [context engineering](https://www.anthropic.com/research/effective-context-engineering-for-ai-agents), and [agent memory](https://www.anthropic.com/research/components-of-agent-memory) inform bounded concurrency, source-linked state, and concise handoffs. The compiler article's unconstrained loop and permission-bypass example are **not** adopted.
- OpenAI's [Codex SDK](https://learn.chatgpt.com/docs/codex-sdk), [App Server](https://learn.chatgpt.com/docs/app-server), [non-interactive mode](https://learn.chatgpt.com/docs/non-interactive-mode), and [model guide](https://learn.chatgpt.com/docs/models) document subscription-compatible local execution, account-rate-limit reads, and per-session model choices. They do not provide a tool to silently change this active chat's model.

## Choices

| Concern | Adopt | Reject or defer | Evidence to require |
| --- | --- | --- | --- |
| Continuity | Durable SQLite task/attempt/events and concise human handoff | One giant prompt as the only state | Restart/failure-injection test |
| Scope | Dependency-gated, immutable acceptance criteria, one bounded implementation at a time | Unbounded self-assigned changes | Evaluator checks task ID and artifact hashes |
| Execution | Documented Codex local subscription path, explicit per-session model, normal approvals | API-key charges, credential scraping, approval bypass | CLI/App Server capability and dry-run tests |
| Usage | App Server `account/rateLimits/read`: accept only a verified 10,080-minute weekly bucket; default 7% reserve and caution at 10% | Guessing a budget from tokens or a five-hour bucket | Stale/missing/threshold tests and live field check |
| Scientific ordering | Structured-data gate before text/MeMo | Moving to memory work because structured labels are hard | Dependency-gate test and independent scientific review |
| Evaluation | Builder output plus independent executable tests, source/provenance checks, and sampled records | Agent says “done” or a passing unit suite alone | Separate engineering, data, model, and scientific verdicts |
| Recovery | Up to three targeted repairs per implementation; then distinct researched strategy | Infinite retries of the same command | Failed-strategy deduplication test |

## Local starting-state check

On 2026-11-26, `leo/giannis` matched `origin/leo/giannis` and the worktree was clean before H2. `codex-cli 0.165.0` is installed. The documented App Server returned a `codex` bucket with `windowDurationMins=10080` and `usedPercent=45`, so a weekly usage field is available; no credential or account identifier is recorded here. About 35 GiB of local disk was available at the start. The prior harness only checked required files and hashes; it did not schedule or resume external sessions. The B18 linkage is descriptive, not training-ready: 442 candidate drug keys overlap chronological splits and the supported-benefit class is empty. No 2024+ final-holdout outcome should be opened to repair these issues.

The authenticated `codex debug models` catalog on this installation listed `gpt-6.1-sol` and `gpt-6-astra` with `high` reasoning, but **did not list `gpt-6.2-sol`**. The supervisor must validate a model against the live catalog before launching it and may select an available alternative; documentation that a model exists generally is not evidence this account can use it. The user subsequently changed the active overnight reserve to 5% remaining; see the ledger change request. The 7% value remains the design default, with an explicitly configured 5% run policy and a margin for in-flight usage.

## Next acceptance boundary

H2 can establish the supervisor mechanics. It cannot by itself verify drug identity, fix the B17 efficacy-label bottleneck, produce a trained model, or open the text/MeMo stage. Those require separately preregistered scientific tasks and independent real-data audits. Model-selection claims require an actual supported session launch and usage observation, not the presence of a model name in configuration.
