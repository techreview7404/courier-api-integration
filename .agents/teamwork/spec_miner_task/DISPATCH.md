## 2026-09-28T14:45:01Z

You are the Task Requirements Spec Miner for the Courier Integration Platform backend service project.

Your Working Directory: ./.agents/teamwork/spec_miner_task
Project Root: .

MANDATORY INPUTS TO READ:
1. ./.agents/teamwork/ORIGINAL_REQUEST.md
2. ./task.md

YOUR OBJECTIVE:
Thoroughly read and extract all functional, non-functional, domain, API, and architectural requirements from task.md and ORIGINAL_REQUEST.md.
Enumerate:
- All required endpoints and exact request/response schemas
- Data models (Orders, Tracking History, Bulk Batches, etc.) and constraints (idempotency, immutability of tracking history)
- Courier abstraction requirements (Adapter pattern, CourierRegistry, MockCourierAdapter failure modes, UrbaneboltAdapter)
- Error handling envelope and error code mappings
- Bulk processing asynchronous execution rules (in-process concurrency, polling, summary counts, partial failure handling)
- Retry and resiliency logic (exponential backoff, configurable parameters, 401 token refresh)
- Testing requirements and documentation deliverables (README.md, DESIGN.md)

OUTPUT REQUIREMENTS:
- Write your comprehensive analysis to: ./.agents/teamwork/spec_miner_task/analysis.md
- Write your structured handoff to: ./.agents/teamwork/spec_miner_task/handoff.md
- Update progress.md in your working directory.
- Send a completion message to parent upon finishing.
