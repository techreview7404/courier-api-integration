# UrbaneBolt API Specification & Integration Analysis

## 1. Executive Summary

This document provides the authoritative, empirically verified technical specification for integrating with the **UrbaneBolt Logistics Courier API** (UAT Environment). Findings were discovered from `urbanebolt_doc.json` (Postman Collection `59abb4ea-8b36-401f-85aa-77f2b776fb25`) and rigorously verified against the live UAT endpoint (`https://uat.urbanebolt.in`).

All 12 endpoints discovered in the Postman collection have been probed. Specific focus is placed on the core lifecycle: Authentication (`getToken`), Shipment Manifesting (`manifest`), Shipment Tracking (`tracking-pub`), and Order Cancellation (`cancel`), along with comprehensive mapping to the normalized internal platform schema.

---

## 2. Environment & Endpoints Overview

- **Base URL (UAT)**: `https://uat.urbanebolt.in`
- **Default Customer Code**: `UEBCUS0008`
- **Default Test Credentials**:
  - `username`: `info@urbanebolt.com`
  - `password`: `EKIcygsLVV5RCtPZ`
- **SSL / TLS**: Server uses self-signed / enterprise certificate chain; HTTP clients must configure certificate validation or custom CA trust.
- **Protocol**: HTTP/2, REST over HTTPS, JSON payloads.

---

## 3. Features Discovered

| # | Category | Feature | Description | Inputs | Outputs | Error Behavior | Discovered Via |
|---|----------|---------|-------------|--------|---------|----------------|----------------|
| 1 | Auth | `getToken` API | Authenticates API client and returns a Bearer access token | `POST /api/v1/auth/getToken/`<br>JSON: `username`, `password` | HTTP 200: `{"access_token": "...", "expires_in": 86400, "token_type": "Bearer", "expires": "...", "status": "Success"}` | Invalid creds: HTTP 200 `{"status": "Failed", "message": "Incorrect username/password!"}`.<br>Missing fields: HTTP 200 `{"status": "Failed", "message": "Username and Password not provided!"}`.<br>Malformed JSON: HTTP 400. | `urbanebolt_doc.json` Item 1 & Live UAT probe |
| 2 | Orders | Manifest API (Single/Batch) | Registers and manifests one or more shipments, generates AWB numbers and route codes | `POST /api/v1/services/manifest/`<br>Headers: `Authorization: Bearer <token>`, `Content-Type: application/json`<br>JSON: List of order objects | HTTP 200: `{"status": "Success", "successResponse": [{"status": "Success", "orderNumber": "...", "awbNumber": 200000007935, "routeCode": "GGN/DLHH", "shippingLabel": "...", "customerCode": "UEBCUS0008"}], "errorResponse": []}` | Missing auth: HTTP 401 `{"status": "Failed", "message": "Authentication required."}`.<br>Duplicate order: HTTP 200 with object in `errorResponse`: `{"orderNumber": "...", "customerCode": "...", "status": "Failed", "message": "orderNumber already shipped!"}`.<br>Empty list: HTTP 200 `{"status": "Failed", "message": "Payload Not Found!"}`.<br>Missing fields: HTTP 200 with schema error string in `errorResponse`. | `urbanebolt_doc.json` Item 4 & Live UAT probe |
| 3 | Tracking | Tracking API (`tracking-pub`) | Retrieves real-time shipment status, destination, package metadata, and complete audit scan history | `GET /api/v1/services/tracking-pub/?awb=<awb_number>`<br>Headers: `Authorization: Bearer <token>` | HTTP 200: `{"status": "Success", "message": "Tracking", "data": {"awbNumber": ..., "orderNumber": "...", "currentStatusCode": "...", "currentStatusCodeDescription": "...", "scans": [...]}}` | Invalid/expired auth: HTTP 401 `{"detail": "Authentication credentials were not provided."}`.<br>Non-existent AWB: HTTP 200 `{"status": "Failed", "message": "Data Not Found", "data": []}`.<br>Missing/multiple AWBs: HTTP 200 `{"status": "Failed", "message": "Invalid Tracking Details Provided", "data": []}`. | `urbanebolt_doc.json` Item 6 & Live UAT probe |
| 4 | Orders | Cancellation API | Cancels an unpicked shipment by AWB number before courier pickup | `POST /api/v1/services/cancel/`<br>Headers: `Authorization: Bearer <token>`, `Content-Type: application/json`<br>JSON: `{"awbs": "<awb_number>"}` (single or comma-separated) | HTTP 200: `{"status": "Success", "message": "Cancellation Proccess", "successResponse": [{"orderNumber": "...", "awb": "...", "message": "Cancelled"}], "failureResponse": []}` | Already cancelled: HTTP 200 with entry in `failureResponse`: `{"message": "Shipment already cancelled!"}`.<br>Non-existent AWB: HTTP 200 with entry in `failureResponse`: `{"message": "Requested AWB not found..."}`.<br>Missing `awbs`: HTTP 200 `{"status": "Failed", "message": "Input not provided!", "data": []}`. | `urbanebolt_doc.json` Item 7 & Live UAT probe |
| 5 | Services | Print Label API | Fetches structured shipping label details for label printing | `GET /api/v1/services/label/?awbs=<awb>`<br>Headers: `Authorization: Bearer <token>` | HTTP 200: `{"status": "Success", "message": "Shipments", "data": [{"awb": ..., "order_number": "...", "consignee": {...}}]}` | Invalid AWB returns empty data. | `urbanebolt_doc.json` Item 5 & Live UAT probe |
| 6 | Location | Pincode Serviceability API | Checks serviceable operations (inbound, outbound, return) for comma-separated pincodes | `GET /api/v1/location/pincodes/?pincodes=122001,122017`<br>Headers: `Authorization: Bearer <token>` | HTTP 200: `{"status": "Success", "message": "Pincodes", "data": [{"pincode": 122001, "inbound": true, "outbound": true, "rtn": true, "serviceCenter": "..."}]}` | Unknown pincode returns empty data list. | `urbanebolt_doc.json` Item 2 & Live UAT probe |
| 7 | Location | Pincode Bulk API | Exports all active/serviceable pincodes in the network | `GET /api/v1/location/pincodes/?type=ex`<br>Headers: `Authorization: Bearer <token>` | HTTP 200: `{"status": "Success", "message": "Pincodes", "data": [...]}` | Invalid params ignored; returns bulk list. | `urbanebolt_doc.json` Item 3 & Live UAT probe |
| 8 | Post-Order | Electronic Proof of Delivery (ePOD) | Retrieves proof of delivery image URLs and delivery timestamp | `GET /api/v1/services/epod/?awbs=<awb>`<br>Headers: `Authorization: Bearer <token>` | HTTP 200: `{"status": "Success", "message": "EPod's", "successResponse": [{"awb": "...", "status": "Delivered", "podUrl": "..."}]}` | Undelivered shipment returns empty `successResponse` or failed list. | `urbanebolt_doc.json` Item 10 & Live UAT probe |
| 9 | Post-Order | PayMode Change API | Converts payment mode (e.g. COD to Prepaid) for shipments before delivery | `POST /api/v1/services/update-paymode/`<br>JSON: `{"awbs": "..."}` | HTTP 200: `{"status": "Success", "message": "PayMode Change", "successResponse": [...], "failedResponse": [...]}` | Disallowed states return in `failedResponse` with `"You can't change pay mode at this moment!"`. | `urbanebolt_doc.json` Item 9 & Live UAT probe |
| 10 | Exception | NDR API - RTO Lock | Directs shipment to Return-To-Origin after failed delivery attempts | `POST /api/v1/services/ndr/?type=rtoLock`<br>JSON: `{"awbs": "..."}` | HTTP 200: `{"status": "Success", "message": "NDR", "successResponse": [...], "failedResponse": [...]}` | Already closed shipment returns `"Shipment already in closed stage!"` in `failedResponse`. | `urbanebolt_doc.json` Item 8 & Live UAT probe |
| 11 | Exception | NDR API - Re-Attempt | Requests re-attempt of delivery with updated consignee contact/address | `POST /api/v1/services/ndr/?type=reAttempt`<br>JSON: List of objects `[{"awb": "...", "name": "...", "address": "...", "mobile": "..."}]` | HTTP 200: `{"status": "Success", "message": "NDR", "successResponse": [{"awb": "...", "message": "Updated"}], "failedResponse": []}` | Invalid AWB or closed stage returns error in `failedResponse`. | `urbanebolt_doc.json` Item 11 & Live UAT probe |
| 12 | Orders | Global Manifest API | Postman template for cross-border/global manifests | `POST /api/v1/services/global-manifest/`<br>JSON: List of global order objects | N/A (UAT route not deployed) | HTTP 404 Not Found in UAT environment. Domestic `services/manifest/` is the standard endpoint. | `urbanebolt_doc.json` Item 12 & Live UAT probe |

---

## 4. Edge Cases Observed During Live Probing

| # | Feature | Input / Condition | Observed Behavior |
|---|---------|-------------------|-------------------|
| 1 | `getToken` | Wrong username or password | HTTP 200 with `{"status":"Failed","message":"Incorrect username/password!"}` (Does NOT return HTTP 401). |
| 2 | `getToken` | Missing username in payload | HTTP 200 with `{"status":"Failed","message":"Username and Password not provided!"}`. |
| 3 | `getToken` | Malformed JSON string | HTTP 400 with `{"detail":"JSON parse error - ..."}`. |
| 4 | `getToken` | HTTP GET method on `getToken` | HTTP 200 with `{"status":"Failed","message":"Incorrect username/password!"}`. |
| 5 | `manifest` | Missing `Authorization` header | HTTP 401 with `{"status": "Failed", "message": "Authentication required."}`. |
| 6 | `manifest` | Invalid or expired Bearer token | HTTP 401 with `{"detail":"Authentication credentials were not provided."}`. |
| 7 | `manifest` | Empty list `[]` or dict `{}` payload | HTTP 200 with `{"status":"Failed","message":"Payload Not Found!"}`. |
| 8 | `manifest` | Duplicate `orderNumber` | HTTP 200 with `successResponse: []` and `errorResponse: [{"orderNumber":"...","customerCode":"...","status":"Failed","message":"orderNumber already shipped!"}]`. |
| 9 | `manifest` | Address < 10 characters (shipper/rtn/cons) | HTTP 200 with `errorResponse: [{"message": "rtnAddress should not be less than 10 charcters..."}]`. |
| 10 | `manifest` | Invalid service type | HTTP 200 with `errorResponse: [{"message": "...serviceType 'UNKNOWN' is not one of ['SSDD', 'SDD', 'NDD', 'ATA', 'PTP', '2HR']"}]`. |
| 11 | `manifest` | Unserviceable destination pincode | HTTP 200 with `errorResponse: [{"message": "Pickup Pincode (999999) is not serviceable"}]`. |
| 12 | `manifest` | Batch submission (e.g. 2 orders, 1 new + 1 duplicate) | HTTP 200 with partial results: valid order in `successResponse`, duplicate in `errorResponse`. |
| 13 | `tracking-pub` | Missing AWB query param (`?awb=`) | HTTP 200 with `{"status":"Failed","message":"Invalid Tracking Details Provided","data":[]}`. |
| 14 | `tracking-pub` | Non-existent AWB number | HTTP 200 with `{"status":"Failed","message":"Data Not Found","data":[]}`. |
| 15 | `tracking-pub` | Comma-separated multiple AWBs | HTTP 200 with `{"status":"Failed","message":"Invalid Tracking Details Provided","data":[]}` (Only single AWB supported). |
| 16 | `tracking-pub` | POST request to GET endpoint | HTTP 405 Method Not Allowed `{"detail":"Method \"POST\" not allowed."}`. |
| 17 | `cancel` | Already cancelled AWB | HTTP 200 with `successResponse: []` and `failureResponse: [{"orderNumber":"...","awb":"...","message":"Shipment already cancelled!"}]`. |
| 18 | `cancel` | Non-existent AWB | HTTP 200 with `successResponse: []` and `failureResponse: [{"orderNumber":"","awb":"...","message":"Requested AWB not found or may be not belong to your account"}]`. |
| 19 | `cancel` | Non-numeric AWB string (e.g. "INVALID_AWB") | HTTP 200 with `failureResponse: [{"orderNumber":"","awb":"INVALID_AWB","message":"Requested AWB not found!"}]`. |
| 20 | `cancel` | Missing `awbs` key or empty string `{"awbs": ""}` | HTTP 200 with `{"status":"Failed","message":"Input not provided!","data":[]}`. |
| 21 | `global-manifest`| Valid payload to `global-manifest/` | HTTP 404 HTML response; route is not registered on UAT gateway. |

---

## 5. Detailed Component Specifications

### 5.1 Authentication Endpoint (`getToken`)

- **URL**: `POST https://uat.urbanebolt.in/api/v1/auth/getToken/`
- **Headers**:
  - `Content-Type: application/json`
- **Request Payload**:
  ```json
  {
    "username": "info@urbanebolt.com",
    "password": "EKIcygsLVV5RCtPZ"
  }
  ```
- **Success Response** (`HTTP 200 OK`):
  ```json
  {
    "access_token": "JMSDpOl9hIvBhaDCTZEAlFiiZgA3rf",
    "expires_in": 86400,
    "token_type": "Bearer",
    "expires": "2026-09-29T17:16:00.524125",
    "status": "Success"
  }
  ```
- **Token Characteristics**:
  - **Type**: Bearer token (opaque random string, 30 chars).
  - **Lifetime (`expires_in`)**: 86,400 seconds (24 hours).
  - **Expiry header format**: `Authorization: Bearer <access_token>`.
  - **Caching Strategy**: Cache the token in memory with an expiration timestamp (`expires_in - 300` seconds buffer).
  - **Token Refresh**: On receiving `HTTP 401 Unauthorized` on any service endpoint, invalidate the cached token, authenticate anew via `getToken`, and retry the original call once.
- **Error Response** (`HTTP 200 OK` with failure status):
  ```json
  {
    "status": "Failed",
    "message": "Incorrect username/password!"
  }
  ```

---

### 5.2 Order Creation / Manifest Endpoint (`manifest`)

- **URL**: `POST https://uat.urbanebolt.in/api/v1/services/manifest/`
- **Headers**:
  - `Authorization: Bearer <access_token>`
  - `Content-Type: application/json`
- **Request Format**: A JSON **Array** of shipment objects: `[ { ... } ]`.
- **Field Constraints & Types**:
  - `customerCode` (string, required): e.g. `"UEBCUS0008"`.
  - `orderNumber` (string, required, unique per account): e.g. `"ORD-12345"`.
  - `shprName` (string, required): Shipper contact name.
  - `shprAddress` (string, required, min 10 chars): Shipper street address.
  - `shprAddressType` (string, required): Allowed values include `"Seller"`, `"Warehouse"`.
  - `shprCity` (string, required): e.g. `"Govindpura"` or `"Gurgaon"`.
  - `shprState` (string, required): e.g. `"BHOPAL"` or `"HARYANA"`.
  - `shprPincode` (integer or string, required, 6 digits): Must be serviceable for outbound.
  - `shprMobile` (integer or string, required, 10 digits): Shipper phone number.
  - `shprCountry` (string, required): e.g. `"INDIA"`.
  - `shprEmail` (string, optional/recommended): Shipper email.
  - `rtnName`, `rtnAddress`, `rtnAddressType`, `rtnCity`, `rtnState`, `rtnPincode`, `rtnMobile`, `rtnCountry`: Return origin details (can mirror shipper fields).
  - `consName` (string, required): Consignee / customer name.
  - `consAddress` (string, required, min 10 chars): Consignee address.
  - `consAddressType` (string, required): e.g. `"Home"`, `"Office"`.
  - `consCity` (string, required): Consignee city.
  - `consState` (string, required): Consignee state.
  - `consPincode` (integer or string, required, 6 digits): Must be serviceable for inbound.
  - `consMobile` (integer or string, required, 10 digits): Customer phone.
  - `consCountry` (string, required): e.g. `"INDIA"`.
  - `consEmail` (string, optional/recommended): Customer email.
  - `payMode` (string, required): `"PPD"` (Prepaid) or `"COD"` (Cash on Delivery).
  - `collectableValue` (number, required): `0` for prepaid, or amount to collect for COD.
  - `declaredValue` (number, required): Insured/declared parcel value (e.g. `100`).
  - `invoiceValue` (number, required): Total invoice value (e.g. `100`).
  - `invoiceNumber` (string, required): e.g. `"INV-ORD-12345"`.
  - `invoiceDate` (string, required): `"YYYY-MM-DD"`.
  - `itemDescription` (string, required): Description of items (e.g. `"Books"`).
  - `itemQuantity` (integer, required): Total item count.
  - `pieces` (integer, required): Number of parcels/boxes (typically `1`).
  - `weight` (number, required): Weight in kilograms (e.g. `0.5`).
  - `length`, `breadth`, `height` (number, required): Dimensions in cm (e.g. `10`, `10`, `10`).
  - `serviceType` (string, required): Allowed values: `['SSDD', 'SDD', 'NDD', 'ATA', 'PTP', '2HR']`. Default for standard parcel: `"SDD"` or `"NDD"`.

- **Success Response** (`HTTP 200 OK`):
  ```json
  {
    "status": "Success",
    "successResponse": [
      {
        "status": "Success",
        "orderNumber": "ORD-12345",
        "awbNumber": 200000007936,
        "routeCode": "GGN/DLHH",
        "shippingLabel": "https://api.uat.urbanebolt.in/api/v1/services/print-label/?key=...",
        "customerCode": "UEBCUS0008"
      }
    ],
    "errorResponse": []
  }
  ```
- **Key Output Identifiers**:
  - `courier_order_id`: Maps to `orderNumber` (string).
  - `awb_number`: Maps to `str(awbNumber)` (e.g. `"200000007936"`).
  - `shipping_label_url`: Extracted from `shippingLabel`.

- **Failure / Duplicate Response** (`HTTP 200 OK` with non-empty `errorResponse`):
  ```json
  {
    "status": "Success",
    "successResponse": [],
    "errorResponse": [
      {
        "orderNumber": "ORD-12345",
        "customerCode": "UEBCUS0008",
        "status": "Failed",
        "message": "orderNumber already shipped!"
      }
    ]
  }
  ```

---

### 5.3 Tracking Endpoint (`tracking-pub`)

- **URL**: `GET https://uat.urbanebolt.in/api/v1/services/tracking-pub/?awb=<awb_number>`
- **Headers**:
  - `Authorization: Bearer <access_token>`
  - `Content-Type: application/json`
- **Success Response** (`HTTP 200 OK`):
  ```json
  {
    "status": "Success",
    "message": "Tracking",
    "data": {
      "awbNumber": 200000007935,
      "orderNumber": "ORD-12345",
      "pieces": 1,
      "addedOn": "28 Sep 2026",
      "invoiceDate": "02 Oct 2024",
      "invoiceNumber": "INV0002",
      "remarks": null,
      "shipperName": "Warehouse Hub",
      "origin": "Gurgaon",
      "destination": "Gurgaon",
      "currentLocation": "Gurgaon",
      "edd": "2026-09-29",
      "currentStatusDateTime": "28 Sep 2026, 20:17",
      "currentStatusCode": "MAN",
      "currentStatusCodeDescription": "Shipment Manifested",
      "currentReasonCode": "",
      "currentReasonCodeDescription": "",
      "isRto": false,
      "weight": 1.1,
      "referenceAwb": null,
      "lat": 0.0,
      "lng": 0.0,
      "productType": "COD",
      "delOtpVerified": false,
      "pickupOtpVerified": false,
      "rtoOtpVerified": false,
      "delPod": "",
      "pickupPod": "",
      "rto_status": 0,
      "scans": [
        {
          "statusDateTime": "28 Sep 2026, 20:17",
          "statusCode": "MAN",
          "statusCodeDescription": "Shipment Manifested",
          "reasonCode": "",
          "reasonCodeDescription": "",
          "currentLocation": "Gurgaon"
        }
      ]
    }
  }
  ```

- **Observed UrbaneBolt Status Codes**:
  - `MAN`: "Shipment Manifested"
  - `PKD`: "Picked Up"
  - `RDC`: "Reached at DC" (Reached Distribution Center)
  - `DDS`: "Delivery Scheduled"
  - `OFD`: "Out for Delivery"
  - `DDL`: "Delivered"
  - `UDD`: "Un-delivered"
  - `CAN`: "Cancelled"
  - `RTL`: "RTO Lock" (Return To Origin)

- **Not Found Response** (`HTTP 200 OK`):
  ```json
  {
    "status": "Failed",
    "message": "Data Not Found",
    "data": []
  }
  ```

---

### 5.4 Cancellation Endpoint (`cancel`)

- **URL**: `POST https://uat.urbanebolt.in/api/v1/services/cancel/`
- **Headers**:
  - `Authorization: Bearer <access_token>`
  - `Content-Type: application/json`
- **Request Payload**:
  ```json
  {
    "awbs": "200000007936"
  }
  ```
  *(Note: Accepts a single AWB string or comma-separated string of AWBs)*.

- **Success Response** (`HTTP 200 OK`):
  ```json
  {
    "status": "Success",
    "message": "Cancellation Proccess",
    "successResponse": [
      {
        "orderNumber": "ORD-12345",
        "awb": "200000007936",
        "message": "Cancelled"
      }
    ],
    "failureResponse": []
  }
  ```
  *(Crucial observation: in cancel response, key is `"awb"`, whereas in manifest and tracking it is `"awbNumber"`! Furthermore, failure list key is `"failureResponse"`, whereas in manifest it is `"errorResponse"`!)*

- **Already Cancelled Response** (`HTTP 200 OK`):
  ```json
  {
    "status": "Success",
    "message": "Cancellation Proccess",
    "successResponse": [],
    "failureResponse": [
      {
        "orderNumber": "ORD-12345",
        "awb": "200000007936",
        "message": "Shipment already cancelled!"
      }
    ]
  }
  ```

- **Not Found / Invalid AWB Response** (`HTTP 200 OK`):
  ```json
  {
    "status": "Success",
    "message": "Cancellation Proccess",
    "successResponse": [],
    "failureResponse": [
      {
        "orderNumber": "",
        "awb": "999999999999",
        "message": "Requested AWB not found or may be not belong to your account"
      }
    ]
  }
  ```

---

## 6. Schema Mapping Specifications

### 6.1 Order Creation Mapping: Internal Schema → UrbaneBolt Manifest

The platform receives normalized requests at `POST /api/v1/orders`:

```json
{
  "order_id": "ORD-001",
  "courier_partner": "urbanebolt",
  "customer": {
    "name": "John Doe",
    "phone": "9999999999",
    "address": "Flat 101, Om Nagar Society, Sumbhal, Surat, Gujarat"
  },
  "items": [
    {
      "name": "Product A",
      "quantity": 1,
      "price": 500
    }
  ]
}
```

The `UrbaneboltAdapter` transforms this normalized structure into the UrbaneBolt manifest list `[ { ... } ]` applying intelligent defaults and configuration:

| Internal Field | UrbaneBolt Manifest Field | Type | Transformation / Default Rule |
|----------------|---------------------------|------|-------------------------------|
| `order_id` | `orderNumber` | string | Direct mapping (`order.order_id`) |
| N/A | `customerCode` | string | `config.URBANEBOLT_CUSTOMER_CODE` (default `"UEBCUS0008"`) |
| `customer.name` | `consName` | string | Direct mapping (`order.customer.name`) |
| `customer.phone` | `consMobile` | integer/str | Cleaned digits from `order.customer.phone` (e.g. `9999999999`) |
| `customer.address` | `consAddress` | string | Direct mapping. Ensure minimum 10 characters (pad if needed) |
| N/A | `consAddressType` | string | Fixed default `"Home"` |
| `customer.address` (parsed) | `consCity` | string | Parsed city, or default `"Surat"` / `"Gurgaon"` |
| `customer.address` (parsed) | `consState` | string | Parsed state, or default `"GUJRAT"` / `"HARYANA"` |
| `customer.address` (parsed) | `consPincode` | integer | Extracted 6-digit pincode, or default `122001` (serviceable UAT pin) |
| N/A | `consCountry` | string | Fixed default `"INDIA"` |
| N/A | `consEmail` | string | Customer email or default `"customer@example.com"` |
| N/A | `shprName` | string | `config.URBANEBOLT_SHIPPER_NAME` or `"Warehouse Hub"` |
| N/A | `shprAddress` | string | `config.URBANEBOLT_SHIPPER_ADDRESS` (min 10 chars, e.g. `"Plot 137 Sector 1 Industrial Area"`) |
| N/A | `shprAddressType`| string | Fixed default `"Seller"` |
| N/A | `shprCity` | string | `config.URBANEBOLT_SHIPPER_CITY` or `"Govindpura"` |
| N/A | `shprState` | string | `config.URBANEBOLT_SHIPPER_STATE` or `"BHOPAL"` |
| N/A | `shprPincode` | integer | `config.URBANEBOLT_SHIPPER_PINCODE` or `122001` |
| N/A | `shprMobile` | integer | `config.URBANEBOLT_SHIPPER_MOBILE` or `9425018023` |
| N/A | `shprCountry` | string | Fixed default `"INDIA"` |
| N/A | `shprEmail` | string | `config.URBANEBOLT_SHIPPER_EMAIL` or `"shipper@urbanebolt.com"` |
| N/A | `rtn*` fields | various | Mirrors `shpr*` fields |
| `items` | `itemDescription` | string | `", ".join(i.name for i in items)` or `"General Merchandise"` |
| `items` | `itemQuantity` | integer | `sum(i.quantity for i in items)` |
| `items` | `declaredValue` | number | `sum(i.price * i.quantity for i in items)` |
| `items` | `invoiceValue` | number | Same as `declaredValue` |
| `order_id` | `invoiceNumber` | string | `"INV-" + order.order_id` |
| N/A | `invoiceDate` | string | Current date in `"YYYY-MM-DD"` format |
| N/A | `payMode` | string | `"PPD"` (Prepaid) or `"COD"` |
| N/A | `collectableValue`| number | `0` for PPD; total amount for COD |
| N/A | `serviceType` | string | `"SDD"` (Same Day Delivery) or `"NDD"` |
| N/A | `pieces` | integer | `1` |
| N/A | `weight` | number | `0.5` (kg) |
| N/A | `length`, `breadth`, `height` | number | `10`, `10`, `10` (cm) |

---

### 6.2 Response Mapping: UrbaneBolt Manifest → Internal Order Creation Response

Internal Unified Response:
```json
{
  "order_id": "ORD-001",
  "courier_partner": "urbanebolt",
  "courier_order_id": "ORD-001",
  "awb_number": "200000007936",
  "status": "CREATED"
}
```

| Internal Field | UrbaneBolt Manifest Field | Mapping Logic |
|----------------|---------------------------|---------------|
| `order_id` | `successResponse[0].orderNumber` | Matched with submitted internal `order_id` |
| `courier_partner` | N/A | Constant `"urbanebolt"` |
| `courier_order_id` | `successResponse[0].orderNumber` | Courier's stored order identifier |
| `awb_number` | `str(successResponse[0].awbNumber)` | Formatted string AWB |
| `status` | Normalized status | Maps to `"CREATED"` |

---

### 6.3 Tracking Status Mapping: UrbaneBolt → Internal Normalized Status

Internal domain defines six normalized statuses:
`CREATED`, `PICKED_UP`, `IN_TRANSIT`, `DELIVERED`, `CANCELLED`, `FAILED`.

| UrbaneBolt `currentStatusCode` | UrbaneBolt Description | Internal Normalized Status | Semantic Meaning |
|--------------------------------|------------------------|----------------------------|------------------|
| `MAN` | Shipment Manifested | `CREATED` | Order created and label generated; waiting for courier pickup |
| `PKD` | Picked Up | `PICKED_UP` | Package collected by courier rider/van |
| `RDC` | Reached at DC | `IN_TRANSIT` | Arrived at distribution center / hub |
| `DDS` | Delivery Scheduled | `IN_TRANSIT` | Delivery run scheduled |
| `OFD` | Out for Delivery | `IN_TRANSIT` | Package is with the delivery executive on route |
| `DDL` | Delivered | `DELIVERED` | Package successfully handed over to customer |
| `CAN` | Cancelled | `CANCELLED` | Shipment cancelled prior to delivery |
| `RTL` | RTO Lock | `FAILED` | Delivery aborted, returning to origin |
| `UDD` | Un-delivered | `FAILED` | Delivery attempt failed |
| Any unmapped code | Unknown | `FAILED` | Safe fallback for unrecognized states |

---

### 6.4 Error Mapping: UrbaneBolt Errors → Internal Normalized Error Envelope

Standard Error Envelope:
```json
{
  "error": {
    "code": "ERROR_CODE",
    "message": "Human readable message",
    "request_id": "req-123",
    "details": {}
  }
}
```

| UrbaneBolt Condition / Response | HTTP Status Code from Courier | Normalized Error Code | Platform HTTP Status | Handling / Retry Behavior |
|---------------------------------|-------------------------------|-----------------------|----------------------|---------------------------|
| HTTP 401 Unauthorized (`Authentication credentials were not provided.`) | 401 | `COURIER_AUTH_ERROR` | 502 Bad Gateway | Trigger automatic token refresh via `getToken` and retry once. If refresh fails, return `COURIER_AUTH_ERROR`. |
| `getToken` returns `status: "Failed"` (`Incorrect username/password!`) | 200 | `COURIER_AUTH_ERROR` | 502 Bad Gateway | Invalid courier credentials configured. No retry. |
| Duplicate `orderNumber already shipped!` in `errorResponse` | 200 | `DUPLICATE_ORDER` | 409 Conflict | Order already created in courier system. Idempotency layer prevents duplicate dispatch. |
| Missing properties / Address < 10 chars / Pincode not serviceable in `errorResponse` | 200 | `VALIDATION_ERROR` | 422 Unprocessable Entity | Client request failed validation against courier constraints. |
| Non-existent AWB in tracking (`Data Not Found`) | 200 | `ORDER_NOT_FOUND` | 404 Not Found | Order/AWB not found on courier network. |
| Non-existent AWB in cancel (`Requested AWB not found...`) | 200 | `ORDER_NOT_FOUND` | 404 Not Found | AWB does not exist or belong to account. |
| Already cancelled in cancel (`Shipment already cancelled!`) | 200 | Success / Idempotent | 200 OK | Already cancelled; return normalized `CANCELLED` status. |
| Network Timeout / HTTP ConnectError / ReadTimeout | Timeout | `COURIER_TIMEOUT` | 504 Gateway Timeout | Retry with exponential backoff (`MAX_RETRIES=2`, `RETRY_DELAY=1s`). |
| HTTP 500 / 502 / 503 / 504 | 5xx | `COURIER_ERROR` | 502 Bad Gateway | Retry with exponential backoff. |

---

## 7. Implementation Recommendations for `couriers/urbanebolt.py`

1. **Authentication Token Management**:
   - Maintain an in-adapter cache: `_cached_token: str | None` and `_token_expiry: float | None`.
   - On request: If `_cached_token` is None or current timestamp > `_token_expiry - 300`, call `_authenticate()`.
   - On HTTP 401: Clear `_cached_token`, call `_authenticate()`, and retry the operation once.

2. **HTTP Client Configuration**:
   - Use `httpx.AsyncClient` or `httpx.Client` with `verify=False` (or configurable SSL cert bundle) to handle the UAT self-signed certificate chain.
   - Configure `timeout=float(config.REQUEST_TIMEOUT)`.

3. **Field Defensive Normalization**:
   - Always ensure `consAddress` and `shprAddress` are >= 10 characters long.
   - Always wrap manifest body as a JSON array (`[payload]`).
   - Extract `awbNumber` safely from `successResponse[0]["awbNumber"]` converting to string.
   - For tracking: extract `currentStatusCode` from `data["currentStatusCode"]` and map using the status mapping dictionary.
   - For cancellation: send `{"awbs": str(tracking_id)}`. Note the response check: inspect `successResponse` and `failureResponse`. If message contains `"already cancelled"`, treat gracefully as cancelled.
