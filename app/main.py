from __future__ import annotations
import logging
import os
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import geopandas as gpd
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pyproj import CRS
from shapely.geometry import mapping

from app.services.file_processor import FileProcessingError, read_geospatial_file, validate_upload
from app.services.measurements import measure_features

BASE_DIR = Path(__file__).resolve().parent.parent
UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", str(BASE_DIR / "uploads"))).resolve()
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_BYTES", str(50 * 1024 * 1024)))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
app = FastAPI(
    title="Geospatial File Measurement API",
    description="Upload KML or zipped Shapefiles, inspect features, and calculate CRS-aware measurements.",
    version="1.0.0",
)

# Assignment-sized in-memory metadata store. Use a database for production/multi-worker deployments.
FILE_RECORDS: dict[str, dict[str, Any]] = {}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_safe(value: Any) -> Any:
    if value is None:
        return None
    if hasattr(value, "item"):
        try:
            return _json_safe(value.item())
        except (ValueError, TypeError):
            pass
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, float) and (value != value or value in (float("inf"), float("-inf"))):
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except (ValueError, TypeError):
            pass
    return str(value)


def _feature_records(gdf: gpd.GeoDataFrame, source_crs: str | None) -> list[dict[str, Any]]:
    features = []
    for index, (_, row) in enumerate(gdf.iterrows()):
        geometry = row.geometry
        properties = {
            str(column): _json_safe(row[column])
            for column in gdf.columns
            if column != gdf.geometry.name
        }
        features.append({
            "feature_id": index,
            "geometry_type": geometry.geom_type if geometry is not None else None,
            "geometry": _json_safe(mapping(geometry)) if geometry is not None else None,
            "crs": source_crs,
            "properties": properties,
        })
    return features


@app.get("/", tags=["Health"])
def root() -> dict[str, str]:
    return {"name": "Geospatial File Measurement API", "status": "ok", "docs": "/docs"}


@app.get("/health", tags=["Health"])
def health() -> dict[str, str]:
    return {"status": "healthy"}


@app.post("/api/files/", status_code=201, tags=["Files"])
async def upload_file(file: UploadFile = File(...)) -> dict[str, Any]:
    try:
        safe_name, file_kind = validate_upload(file.filename or "")
    except FileProcessingError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    file_id = uuid.uuid4().hex
    file_dir = UPLOAD_DIR / file_id
    file_dir.mkdir(parents=True, exist_ok=False)
    saved_path = file_dir / safe_name
    total = 0
    try:
        with saved_path.open("wb") as destination:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_UPLOAD_BYTES:
                    raise HTTPException(status_code=413, detail="Upload exceeds the configured size limit.")
                destination.write(chunk)
        if total == 0:
            raise HTTPException(status_code=400, detail="The uploaded file is empty.")

        gdf = read_geospatial_file(saved_path, file_kind)
        if gdf.empty:
            raise HTTPException(status_code=422, detail="The file contains no features.")
        source_crs = str(CRS.from_user_input(gdf.crs)) if gdf.crs else None
        features = _feature_records(gdf, source_crs)
        measurements = measure_features(gdf, source_crs)
        FILE_RECORDS[file_id] = {
            "id": file_id,
            "filename": safe_name,
            "file_kind": file_kind,
            "file_path": str(saved_path),
            "created_at": _utc_now(),
            "feature_count": len(features),
            "crs": source_crs,
            "status": "COMPLETED",
            "features": features,
            "measurements": measurements,
        }
        return {
            "id": file_id,
            "filename": safe_name,
            "feature_count": len(features),
            "crs": source_crs,
            "status": "COMPLETED",
            "measurements_url": f"/api/files/{file_id}/measurements/",
        }
    except HTTPException:
        shutil.rmtree(file_dir, ignore_errors=True)
        raise
    except FileProcessingError as exc:
        shutil.rmtree(file_dir, ignore_errors=True)
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        shutil.rmtree(file_dir, ignore_errors=True)
        logger.exception("Unexpected error processing upload %s", safe_name)
        raise HTTPException(status_code=422, detail="The file could not be processed; verify its format and CRS.") from exc
    finally:
        await file.close()


@app.get("/api/files/{file_id}/", tags=["Files"])
def get_file_info(file_id: str) -> dict[str, Any]:
    record = FILE_RECORDS.get(file_id)
    if record is None:
        raise HTTPException(status_code=404, detail="File not found.")
    return {key: record[key] for key in ("id", "filename", "feature_count", "crs", "status", "created_at", "file_kind")}


@app.get("/api/files/{file_id}/measurements/", tags=["Measurements"])
def get_measurements(file_id: str) -> dict[str, Any]:
    record = FILE_RECORDS.get(file_id)
    if record is None:
        raise HTTPException(status_code=404, detail="File not found.")
    return {
        "file_id": record["id"],
        "filename": record["filename"],
        "source_crs": record["crs"],
        "feature_count": record["feature_count"],
        "measurements": record["measurements"],
    }


@app.get("/api/files/{file_id}/features/", tags=["Files"])
def get_features(file_id: str) -> dict[str, Any]:
    record = FILE_RECORDS.get(file_id)
    if record is None:
        raise HTTPException(status_code=404, detail="File not found.")
    return {
        "file_id": record["id"],
        "filename": record["filename"],
        "crs": record["crs"],
        "feature_count": record["feature_count"],
        "features": record["features"],
    }


@app.get("/api/files/{file_id}/download/", tags=["Files"])
def download_source_file(file_id: str) -> FileResponse:
    record = FILE_RECORDS.get(file_id)
    if record is None:
        raise HTTPException(status_code=404, detail="File not found.")
    path = Path(record["file_path"])
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Stored source file is unavailable.")
    return FileResponse(path, filename=record["filename"])
