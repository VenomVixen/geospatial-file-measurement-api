# Geospatial File Measurement API

A FastAPI service that accepts KML files and ZIP archives containing Shapefiles, extracts feature information, and calculates polygon areas and line lengths with CRS awareness.

## Features

- `POST /api/files/` — upload and process `.kml` or `.zip` containing a Shapefile.
- `GET /api/files/{id}/` — retrieve file metadata and processing status.
- `GET /api/files/{id}/features/` — retrieve feature geometry, type, CRS, and properties.
- `GET /api/files/{id}/measurements/` — retrieve per-feature measurements.
- `GET /api/files/{id}/download/` — optional download of the original upload.
- `GET /health` — health check.
- Interactive docs at `/docs`.

## Requirements

Python 3.10+ (Python 3.11 recommended). KML driver support depends on the installed GDAL/GeoPandas I/O engine.

## Setup on Windows PowerShell

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
uvicorn app.main:app --reload
```

If PowerShell blocks activation, run `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` in that terminal and activate again.

## Setup on macOS/Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000/docs for Swagger UI.

## API usage

Upload KML:

```bash
curl -X POST "http://127.0.0.1:8000/api/files/" -F "file=@sample.kml"
```

Upload zipped Shapefile:

```bash
curl -X POST "http://127.0.0.1:8000/api/files/" -F "file=@survey.zip"
```

Example upload response:

```json
{
  "id": "generated-file-id",
  "filename": "sample.kml",
  "feature_count": 3,
  "crs": "EPSG:4326",
  "status": "COMPLETED",
  "measurements_url": "/api/files/generated-file-id/measurements/"
}
```

Retrieve file information with `GET /api/files/{id}/`, extracted features with `GET /api/files/{id}/features/`, and measurements with `GET /api/files/{id}/measurements/`.

A polygon measurement contains area in square metres and hectares. A line measurement contains length in metres and kilometres. Point features have `UNSUPPORTED` status because no measurement is required. Missing/empty geometries are marked `SKIPPED`.

## Architecture

```text
Upload endpoint -> validate extension/size -> save file
 -> parse KML or zipped Shapefile -> extract features and CRS
 -> transform geometries -> calculate measurements -> store results
 -> metadata/features/measurements endpoints
```

FastAPI provides the REST API and OpenAPI docs. GeoPandas reads files and transforms CRS, Shapely provides geometry operations, and PyProj interprets coordinate systems and calculates geodesic line lengths.

## CRS and measurement strategy

Area and distance should not be calculated directly from longitude/latitude degree coordinates. The service uses an existing projected CRS in metres when possible. For local data it attempts to estimate a UTM CRS. For broad or unsuitable extents it falls back to EPSG:6933, a global equal-area projection. When the source CRS is geographic, line length uses geodesic calculations; otherwise the projected geometry's length is used.

KML coordinates use WGS 84, so missing KML CRS metadata is treated as EPSG:4326. A Shapefile without CRS metadata is rejected rather than guessing; include a `.prj` file in the ZIP. Automatic CRS selection is a practical default, not a guarantee of survey-grade accuracy for every dataset.

## Validation and error handling

- Unsupported extensions, corrupt ZIPs, missing Shapefile components, empty uploads and files with no features are rejected.
- Default upload limit is 50 MiB (`MAX_UPLOAD_BYTES` environment variable).
- Invalid geospatial data returns HTTP 422; oversized uploads return 413; unknown IDs return 404.
- Unsupported geometries receive a per-feature status instead of crashing measurement generation.

## Testing

```bash
pytest -q
```

Tests cover health endpoints, invalid formats, KML upload, metadata, feature and measurement retrieval, unknown IDs, and source downloads.

## Configuration

- `UPLOAD_DIR`: upload storage directory (default: project `uploads/`).
- `MAX_UPLOAD_BYTES`: upload size limit in bytes (default: 50 MiB).

## Design decisions and limitations

- **Synchronous processing:** keeps the assignment simple to run and inspect. Large files could block a worker; a production version could use a task queue and explicit PENDING/PROCESSING/COMPLETED/FAILED states.
- **In-memory metadata/results:** no database was required. Records are lost on restart and this store is not suitable for multi-worker production; PostgreSQL/PostGIS and durable object storage would be the next step.
- **File safety:** generated IDs avoid trusting client paths. Production hardening should include archive expansion limits, authentication, rate limits, retention policies and observability.
- **KML support:** KML reading depends on installed geospatial driver support; verify your local GDAL/GeoPandas driver availability if reading KML fails.

## Future improvements

- Persist metadata and job state in PostgreSQL/PostGIS.
- Add background processing for large files.
- Add pagination and measurement export.
- Add domain-specific CRS accuracy checks, authentication, and CI.
