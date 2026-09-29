# BRIEFING — 2026-09-28T14:47:07Z

## Mission
Supervise and monitor the development of the unified Courier Integration Platform backend service, ensuring proper execution, liveness, and mandatory victory auditing.

## 🔒 My Identity
- Archetype: sentinel
- Working directory: ./.agents/teamwork/sentinel
- Orchestrator: 53fe967f-356a-4dc8-a2a1-308ee9c4c592
- Victory Auditor: to be spawned on victory claim

## 🔒 Key Constraints
- No technical decisions — relay only
- Victory Audit is MANDATORY before reporting completion
- Keep context ultra-light; never write code or make technical decisions directly

## User Context
- **Last user request**: Incorporate full exhaustive details from task.md and prompt_draft.md (covering exact SQLite table schemas, error codes, API contracts, mock simulation flags, retry policies, and test requirements).
- **Pending clarifications**: none
- **Delivered results**: none

## Project Status
- **Phase**: in progress
- **Route**: General (`teamwork_preview_orchestrator`)
- **Rationale**: Full-scope software engineering project with multiple architectural components, database models, background processing, and test suite.
- **Crons**:
  - Cron 1 (Progress Reporting, */8): task-12
  - Cron 2 (Liveness Check, */10): task-14

## Victory Audit Status
- **Triggered**: no
- **Verdict**: pending
- **Retry count**: 0

## Artifact Index
- ./.agents/teamwork/ORIGINAL_REQUEST.md — Authoritative user request
- ./.agents/teamwork/orchestrator/progress.md — Orchestrator progress log
