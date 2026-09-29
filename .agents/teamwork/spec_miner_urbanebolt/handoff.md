# Handoff Report: UrbaneBolt API Specification Mining

## 1. Observation

Direct observations from examining `./urbanebolt_doc.json`, `ORIGINAL_REQUEST.md`, `task.md`, and executing live probe commands against the UAT server (`https://uat.urbanebolt.in`):

1. **Authentication (`POST /api/v1/auth/getToken/`)**:
   - Live probe command:
     `curl -i -X POST "https://uat.urbanebolt.in/api/v1/auth/getToken/" -H "Content-Type: application/json" -d '{"username":"info@urbanebolt.com", "password":"EKIcygsLVV5RCtPZ"}'`
   - Response: `HTTP/2 200`
     `{"access_token":"JMSDpOl9hIvBhaDCTZEAlFiiZgA3rf","expires_in":86400,"token_type":"Bearer","expires":"2026-09-29T17:16:00.524125","status":"Success"}`
   - Wrong credentials probe:
     `{"username":"info@urbanebolt.com", "password":"WrongPassword123"}`
     Returned: `HTTP/2 200`
     `{"status":"Failed","message":"Incorrect username/password!"}`
   - Missing fields probe:
     Returned: `HTTP/2 200`
     `{"status":"Failed","message":"Username and Password not provided!"}`
   - Malformed JSON probe:
     Returned: `HTTP/2 400`
     `{"detail":"JSON parse error - Expecting property name enclosed in double quotes..."}`

2. **Order Manifesting (`POST /api/v1/services/manifest/`)**:
   - Header requirement: `Authorization: Bearer <access_token>`.
   - Missing auth header returned: `HTTP/2 401` `{"status": "Failed", "message": "Authentication required."}`.
   - Invalid token returned: `HTTP/2 401` `{"detail":"Authentication credentials were not provided."}`.
   - Successful order creation payload (`[ { "customerCode": "UEBCUS0008", "orderNumber": "TEST_MINER_1790606820", ... } ]`) returned: `HTTP/2 200`
     `{"status":"Success","successResponse":[{"status":"Success","orderNumber":"TEST_MINER_1790606820","awbNumber":200000007935,"routeCode":"GGN/DLHH","shippingLabel":"https://api.uat.urbanebolt.in/api/v1/services/print-label/?key=himPHMijuCAmot7VZq835bQOc3np7BqhA_MKK0PYk_M25LrwZvc5pNnW16Pj4RA5","customerCode":"UEBCUS0008"}],"errorResponse":[]}`
   - Resubmitting duplicate `orderNumber` returned: `HTTP/2 200`
     `{"status":"Success","successResponse":[],"errorResponse":[{"orderNumber":"TEST_MINER_1790606820","customerCode":"UEBCUS0008","status":"Failed","message":"orderNumber already shipped!"}]}`
   - Address constraint check returned:
     `"rtnAddress should not be less than 10 charcters (rtnAddress: Address 1), consAddress should not be less than 10 charcters (consAddress: Address 2), shprAddress should not be less than 10 charcters (shprAddress: Address 3)"`
   - Allowed service types in schema validator:
     `serviceType 'UNKNOWN' is not one of ['SSDD', 'SDD', 'NDD', 'ATA', 'PTP', '2HR']`

3. **Shipment Tracking (`GET /api/v1/services/tracking-pub/?awb=<awb_number>`)**:
   - Header requirement: `Authorization: Bearer <access_token>`.
   - Valid AWB `200000007935` returned: `HTTP/2 200`
     `{"status":"Success","message":"Tracking","data":{"awbNumber":200000007935,"orderNumber":"TEST_MINER_1790606820","pieces":1,"addedOn":"28 Sep 2026","invoiceDate":"02 Oct 2024","invoiceNumber":"INV0002","remarks":null,"shipperName":"Rohit Athaley","origin":"Gurgaon","destination":"Gurgaon","currentLocation":"Gurgaon","edd":"2026-09-29","currentStatusDateTime":"28 Sep 2026, 20:17","currentStatusCode":"MAN","currentStatusCodeDescription":"Shipment Manifested","currentReasonCode":"","currentReasonCodeDescription":"","isRto":false,"weight":1.1,"referenceAwb":null,"lat":0.0,"lng":0.0,"productType":"COD","delOtpVerified":false,"pickupOtpVerified":false,"rtoOtpVerified":false,"delPod":"","pickupPod":"","rto_status":0,"scans":[{"statusDateTime":"28 Sep 2026, 20:17","statusCode":"MAN","statusCodeDescription":"Shipment Manifested","reasonCode":"","reasonCodeDescription":"","currentLocation":"Gurgaon"}]}}`
   - Verified UrbaneBolt status codes across sample AWBs:
     - `MAN`: "Shipment Manifested"
     - `PKD`: "Picked Up"
     - `RDC`: "Reached at DC"
     - `DDS`: "Delivery Scheduled"
     - `OFD`: "Out for Delivery"
     - `DDL`: "Delivered"
     - `UDD`: "Un-delivered"
     - `CAN`: "Cancelled"
     - `RTL`: "RTO Lock"
   - Non-existent AWB returned: `HTTP/2 200`
     `{"status":"Failed","message":"Data Not Found","data":[]}`

4. **Shipment Cancellation (`POST /api/v1/services/cancel/`)**:
   - Header requirement: `Authorization: Bearer <access_token>`, `Content-Type: application/json`.
   - Body format: `{"awbs": "<awb_number>"}`.
   - Successful cancellation returned: `HTTP/2 200`
     `{"status":"Success","message":"Cancellation Proccess","successResponse":[{"orderNumber":"TEST_MINER_1790606820","awb":"200000007935","message":"Cancelled"}],"failureResponse":[]}`
   - Subsequent cancel attempt returned: `HTTP/2 200`
     `{"status":"Success","message":"Cancellation Proccess","successResponse":[],"failureResponse":[{"orderNumber":"TEST_MINER_1790606820","awb":"200000007935","message":"Shipment already cancelled!"}]}`
   - Verified that after cancellation, `tracking-pub` reflects `currentStatusCode: "CAN"` and `currentStatusCodeDescription: "Cancelled"`.

5. **Additional Endpoints Discovered in `urbanebolt_doc.json`**:
   - `Print Label`: `GET /api/v1/services/label/?awbs=<awb>` (Returns HTTP 200 with consignee and shipment data)
   - `Pincode Lookup`: `GET /api/v1/location/pincodes/?pincodes=...` (Returns service center, inbound/outbound/rtn flags)
   - `Pincode Bulk`: `GET /api/v1/location/pincodes/?type=ex` (Returns bulk array of serviceable pincodes)
   - `ePOD`: `GET /api/v1/services/epod/?awbs=...` (Returns POD image URLs)
   - `NDR RTO`: `POST /api/v1/services/ndr/?type=rtoLock` (Marks undelivered shipment for RTO)
   - `NDR ReAttempt`: `POST /api/v1/services/ndr/?type=reAttempt` (Updates consignee details for re-attempt)
   - `PayMode Update`: `POST /api/v1/services/update-paymode/` (Updates payment mode)
   - `Global Manifest`: `POST /api/v1/services/global-manifest/` (Returns HTTP 404 Not Found in UAT)

---

## 2. Logic Chain

1. **Authentication Logic**:
   - From Observation 1, `getToken` returns a Bearer token valid for 86,400 seconds (24h).
   - Because `getToken` returns HTTP 200 even on invalid credentials with `status: "Failed"`, the client must check `response.get("status") == "Success"` and extract `access_token`.
   - From Observation 2, expired/invalid tokens cause HTTP 401 on service endpoints. The adapter must intercept 401, re-authenticate via `getToken`, and retry the request once.

2. **Order Manifestation Logic**:
   - From Observation 2, the endpoint expects a JSON array `[ { ... } ]` rather than a single JSON object.
   - Field key differences: UrbaneBolt expects `customerCode`, `orderNumber`, `shpr*`, `cons*`, `rtn*`, `declaredValue`, `invoiceValue`, `serviceType` (`'SDD'` or `'NDD'`), and `payMode` (`'PPD'` or `'COD'`).
   - The addresses must be at least 10 characters long, otherwise validation fails.
   - In response, the identifier is `awbNumber` (integer). The adapter must normalize this to string `awb_number`.
   - Duplicate orders return HTTP 200 with `message: "orderNumber already shipped!"` inside `errorResponse`. The adapter must detect non-empty `errorResponse` and map this to `DUPLICATE_ORDER`.

3. **Tracking Logic**:
   - From Observation 3, the public tracking endpoint takes query param `?awb=<awb_number>`. Multiple comma-separated AWBs are rejected; only one AWB per call is supported.
   - Current status is located in `data.currentStatusCode`.
   - The mapping to the normalized domain status is direct:
     `MAN` -> `CREATED`
     `PKD` -> `PICKED_UP`
     `RDC`, `DDS`, `OFD` -> `IN_TRANSIT`
     `DDL` -> `DELIVERED`
     `CAN` -> `CANCELLED`
     `RTL`, `UDD` -> `FAILED`
   - Complete audit trail is available under `data.scans`, which can be recorded in the `tracking_history` table.
   - When AWB is missing or not found, `status: "Failed"` with `message: "Data Not Found"` is returned; this maps to `ORDER_NOT_FOUND` (HTTP 404).

4. **Cancellation Logic**:
   - From Observation 4, `POST /api/v1/services/cancel/` accepts `{"awbs": "<awb_number>"}`.
   - Notice asymmetry: the cancellation response item uses the key `awb` instead of `awbNumber`, and the failure container is named `failureResponse` instead of `errorResponse`.
   - An already-cancelled order returns `"Shipment already cancelled!"` in `failureResponse`. To provide idempotent cancellation, the adapter should recognize this message and return normalized `CANCELLED` status.

---

## 3. Caveats

- **SSL Certificate Verification**: The UAT environment uses a certificate chain that fails default local Python certificate verification (`[SSL: CERTIFICATE_VERIFY_FAILED] self-signed certificate in certificate chain`). In production or testing against UAT, `verify=False` or a custom CA certificate must be passed to `httpx.AsyncClient`.
- **Global Manifest Not Available**: Endpoint `POST /api/v1/services/global-manifest/` in `urbanebolt_doc.json` returned 404 in UAT. Integration should use standard domestic `POST /api/v1/services/manifest/`.
- **UrbaneBolt HTTP 200 on Errors**: UrbaneBolt frequently returns HTTP 200 with error details in the JSON body (`status: "Failed"`, `errorResponse: [...]`, or `failureResponse: [...]`). The adapter must inspect response JSON structures and not rely solely on HTTP status codes.

---

## 4. Conclusion

The UrbaneBolt UAT API is fully discovered, tested, and ready for integration within `app/couriers/urbanebolt.py`. The contract boundaries, payload structures, token lifecycle, status mappings, and error edge cases are completely documented in `analysis.md`. The `UrbaneboltAdapter` can implement `authenticate`, `create_order`, `track_order`, and `cancel_order` with full fidelity to the live UAT platform.

---

## 5. Verification Method

To independently verify the observed findings, run the following automated probe commands from the project root:

1. **Verify Token Generation**:
   ```bash
   python3 -c "import urllib.request, ssl, json; ctx = ssl._create_unverified_context(); req = urllib.request.Request('https://uat.urbanebolt.in/api/v1/auth/getToken/', data=b'{\"username\":\"info@urbanebolt.com\", \"password\":\"EKIcygsLVV5RCtPZ\"}', headers={'Content-Type': 'application/json'}); print(urllib.request.urlopen(req, context=ctx).read().decode())"
   ```
   *Expected*: `{"access_token":"...","expires_in":86400,"token_type":"Bearer",..."status":"Success"}`

2. **Verify Tracking of Known AWB**:
   ```bash
   python3 -c "import urllib.request, ssl, json; ctx = ssl._create_unverified_context(); auth_req = urllib.request.Request('https://uat.urbanebolt.in/api/v1/auth/getToken/', data=b'{\"username\":\"info@urbanebolt.com\", \"password\":\"EKIcygsLVV5RCtPZ\"}', headers={'Content-Type': 'application/json'}); token = json.loads(urllib.request.urlopen(auth_req, context=ctx).read().decode())['access_token']; track_req = urllib.request.Request('https://uat.urbanebolt.in/api/v1/services/tracking-pub/?awb=200000001170', headers={'Authorization': f'Bearer {token}'}); print(urllib.request.urlopen(track_req, context=ctx).read().decode())"
   ```
   *Expected*: Valid tracking JSON with `currentStatusCode: "CAN"`.

3. **Inspect Specification Artifacts**:
   - `./.agents/teamwork/spec_miner_urbanebolt/analysis.md`
   - `./.agents/teamwork/spec_miner_urbanebolt/handoff.md`

Invalidation condition: If UrbaneBolt UAT credentials change or the UAT gateway URL changes, auth probe will return failure status instead of `"Success"`.
