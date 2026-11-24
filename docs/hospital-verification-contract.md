# Hospital verification: API contract (Role 2 to Role 1)

Proposed by Role 2 (web). Role 1 owns the backend and can change anything here;
tell Role 2 so the dashboard and admin panel follow. Today `POST /api/auth/register`
accepts `name`, `location`, `phone`, `password` and the hospital can dispatch at once.
Nothing checks that the facility is real.

## Hospital states

`pending` (just registered) -> `approved` or `rejected`. `approved` -> `suspended` and back.

| State | Can sign in | Can dispatch |
| --- | --- | --- |
| `pending` | yes, sees a "waiting for review" screen | no |
| `approved` | yes | yes |
| `rejected` | yes, sees the reason and can resubmit | no |
| `suspended` | yes, sees a notice | no |

Existing hospitals in the database should be migrated to `approved` so live use is not broken.

## Registration fields (extends `HospitalRegister`)

| Field | Required | Notes |
| --- | --- | --- |
| `name`, `location`, `phone`, `password` | yes | as today |
| `official_email` | yes | verified by a link or code before review |
| `facility_type` | yes | `hospital`, `blood_bank` or `blood_centre` |
| `registration_number` | yes | clinical establishment or hospital registration number |
| `hfr_id` | no | ABDM Health Facility Registry ID |
| `blood_centre_license_number` | required for `blood_bank` and `blood_centre` | |
| `contact_person` | yes | name of the in-charge |

## Endpoints

| Method and path | Who | Purpose |
| --- | --- | --- |
| `POST /api/auth/register` | public | Create hospital in `pending`, return `id` |
| `POST /api/hospital/documents` | hospital token | Upload one document: `kind` (`registration`, `blood_licence`, `other`) plus a file. PDF, JPG or PNG, 5 MB maximum, content type checked server side |
| `GET /api/hospital/me` | hospital token | Return profile with `status`, `rejection_reason`, document list |
| `GET /api/admin/hospitals?status=pending` | admin token | List hospitals for review |
| `GET /api/admin/hospitals/{id}/documents/{doc_id}` | admin token | Short-lived signed URL to view a file |
| `POST /api/admin/hospitals/{id}/decision` | admin token | Body `{ "decision": "approve" \| "reject" \| "suspend", "reason": "..." }` |

Rules:

- Dispatch endpoints return `403` with `{ "code": "hospital_not_approved" }` unless the hospital is `approved`.
- Admin tokens carry `role: "admin"` and cannot be created through public registration.
- Every decision is written to an audit log with admin, time and reason.
- Uploaded documents live in private object storage, never in a public folder.
- Email the hospital on approval, rejection and suspension.

## What Role 2 builds against this

- Extended sign-up form with document upload and a "pending review" screen.
- Admin review panel: pending list, document viewer, approve, reject with reason, suspend.
- Clear handling of `hospital_not_approved` in the dashboard.
