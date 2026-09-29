## 2026-09-28T14:45:01Z
You are the Architecture and Integration Explorer for the Courier Integration Platform backend service project.

Your Working Directory: ./.agents/teamwork/explorer_arch
Project Root: .

MANDATORY INPUTS TO READ:
1. ./.agents/teamwork/ORIGINAL_REQUEST.md
2. ./task.md
3. Environment inspection (Python environment, available packages, sqlite3, fastapi, pytest, etc.)

YOUR OBJECTIVE:
Investigate and design the architectural foundation:
- Project structure and file layout adhering to Python/FastAPI best practices
- Recommended dependencies (FastAPI, SQLAlchemy, SQLite, Pydantic v2, httpx/aiohttp, pytest, any background execution helpers)
- Database schema and migrations/initialization strategy
- Decoupled adapter layer design (Base CourierAdapter interface, dynamic CourierRegistry)
- Error handling architecture (custom exception hierarchy, global exception handlers, standardized error envelope)
- Resiliency patterns (retry decorator/helper, exponential backoff, auth refresh wrapper)
- Background processing architecture (FastAPI BackgroundTasks or asyncio concurrency without external broker)
- Test architecture and strategy (unit, integration, mock failure modes, e2e)

OUTPUT REQUIREMENTS:
- Write your comprehensive analysis to: ./.agents/teamwork/explorer_arch/analysis.md
- Write your structured handoff to: ./.agents/teamwork/explorer_arch/handoff.md
- Update progress.md in your working directory.
- Send a completion message to parent upon finishing.
