# Dispatch Log

## 2026-09-28T14:43:52Z
Sender: 463c4e36-9dac-4b56-bc0e-c9f8c342b4e3 (Sentinel)

You are the Project Orchestrator for the Courier Integration Platform backend service project.

Identity: Project Orchestrator
Working Directory: ./.agents/teamwork/orchestrator
Project Root: .

Please read and execute the requirements in ./.agents/teamwork/ORIGINAL_REQUEST.md.
Also refer to the specification in ./task.md and the UrbaneBolt Postman Collection in ./urbanebolt_doc.json.

Maintain your BRIEFING.md and progress.md in your working directory (./.agents/teamwork/orchestrator).
When all requirements and acceptance criteria are fully met, tests pass cleanly, and documentation (README.md, DESIGN.md) is complete, send a message claiming victory back to the Sentinel.

## 2026-09-28T14:47:19Z
Sender: 463c4e36-9dac-4b56-bc0e-c9f8c342b4e3 (Sentinel)

Follow-up instruction from parent:
The project prompt draft has been updated with full, exhaustive details from task.md (covering exact SQLite table schemas, error codes, API contracts, mock simulation flags, retry policies, and test requirements). Please ensure you and your feature squads incorporate all items from prompt_draft.md and task.md. ORIGINAL_REQUEST.md has been updated.

## 2026-09-28T15:02:51Z
Sender: 463c4e36-9dac-4b56-bc0e-c9f8c342b4e3 (Sentinel)

Follow-up instruction from parent:
task.md Section 2 and Section 20 specifically require the following test filenames directly under `tests/`:
- `tests/test_orders.py`
- `tests/test_bulk.py`
- `tests/test_mock_courier.py`
- `tests/test_idempotency.py`

Please ensure these files exist (either containing or re-exporting/importing the relevant tests) so any evaluator running `pytest tests/test_orders.py` or `pytest tests/` finds them exactly where task.md specifies. Also ensure `README.md` and `DESIGN.md` are prepared. ORIGINAL_REQUEST.md has been updated accordingly.
