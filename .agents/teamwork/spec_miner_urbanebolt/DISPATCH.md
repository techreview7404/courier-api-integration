## 2026-09-28T14:45:01Z
You are the UrbaneBolt API Spec Miner for the Courier Integration Platform backend service project.

Your Working Directory: ./.agents/teamwork/spec_miner_urbanebolt
Project Root: .

MANDATORY INPUTS TO READ:
1. ./.agents/teamwork/ORIGINAL_REQUEST.md
2. ./urbanebolt_doc.json

YOUR OBJECTIVE:
Thoroughly examine urbanebolt_doc.json (Postman collection) and extract the exact specifications for the UrbaneBolt courier integration:
- Authentication endpoint (getToken), payload, response structure, token lifetime/expiry, auth header format
- Manifest / order creation endpoint, request schema, mandatory/optional fields, sample payload, response schema (tracking ID, waybill, etc.)
- Tracking endpoint (tracking-pub), request params/body, response schema, status values and their semantic meanings
- Cancellation endpoint, request format, response schema
- Error response structures, HTTP status codes, error codes
- Mapping between UrbaneBolt schemas and the normalized internal platform schema

OUTPUT REQUIREMENTS:
- Write your comprehensive analysis to: ./.agents/teamwork/spec_miner_urbanebolt/analysis.md
- Write your structured handoff to: ./.agents/teamwork/spec_miner_urbanebolt/handoff.md
- Update progress.md in your working directory.
- Send a completion message to parent upon finishing.

## 2026-09-28T14:50:15Z
**Context**: UrbaneBolt API Spec Mining
**Content**: Checking in on your progress with the UrbaneBolt API specification analysis and Postman collection review.
**Action**: Please provide a brief status update or finalize your analysis.md and handoff.md when ready.
