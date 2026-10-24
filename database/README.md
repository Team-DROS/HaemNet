# HaemNet data layer

**MongoDB is the default database.** MongoDB Atlas is the hosted option;
a local MongoDB can be used for development. PyMongo's async client connects
the FastAPI backend to the configured database.

The original Neo4j implementation is retained behind `DB_BACKEND=neo4j`.
The `database/` directory documents storage; runtime MongoDB queries live in
[`backend/db_services/mongo_repo.py`](../backend/db_services/mongo_repo.py).

## Collections

| Collection | Identity and purpose |
| --- | --- |
| `donors` | UUID `_id`; profile, phone, group, language, location, last donation |
| `hospitals` | Hospital ID `_id`; hospital details and password hash |
| `dispatches` | Dispatch UUID `_id`; hospital, requested group/units, urgency, location, timestamps, fulfillment |
| `calls` | `<dispatch_id>:<donor_id>`; donor response state, distance, ETA, Twilio SID |
| `donor_logins` | Phone `_id`; donor password hash, separate from the profile |

Dates are stored as UTC BSON datetimes and returned through the API as ISO
strings. Public profile responses do not include password hashes.

## Locations and recruitment

Donor locations use GeoJSON with **longitude first**:

```json
{
  "type": "Point",
  "coordinates": [80.2519, 13.0626]
}
```

The donor query uses `$geoNear` and a `2dsphere` index. It matches a requested
blood group, limits distance to a default 10 km, and excludes donors whose
last donation is inside the configured 56-day cooldown.

The recruitment layer can expand `All positive` and `All negative` into
individual blood-group queries. It does not calculate clinical blood
compatibility or replace screening and cross-matching.

Startup creates indexes for donor location, unique donor phone, blood group,
hospital/creation time on dispatches, completion state, and call lookups.
Collection `_id` fields use MongoDB's built-in uniqueness.

## Local configuration

Set these in the root `.env` when launching from the repository root:

```dotenv
DB_BACKEND=mongodb
MONGODB_URI=mongodb://localhost:27017
MONGODB_DATABASE=haemnet
```

For Atlas, use its connection string and configure database-user permissions
and network access. Keep credentials out of source files and frontend variables.

Start the backend with `--loop asyncio`. `GET /api/health` reports the
selected database and connection status. A healthy database does not verify
Twilio or Sarvam access.

## Development and integration tests

`python -m backend.tools.seed_demo` writes demo records to the configured
database. Use an isolated development database. Its production-environment
guard is not a substitute for checking the connection string. Generated donor
numbers are test data and must not be called.

MongoDB integration tests use `haemnet_test`, with the server selected by
`MONGODB_TEST_URI` (or the documented test fallback). Use a disposable local
test server. CI supplies MongoDB; tests skip if no server is available.

## Legacy Neo4j

Set `DB_BACKEND=neo4j` and provide `NEO4J_URI`, `NEO4J_USER`, and
`NEO4J_PASSWORD` to select the retained repository. Switching this setting
does not migrate records between databases.

For deployment and operational settings, see [DEPLOY.md](../DEPLOY.md).
