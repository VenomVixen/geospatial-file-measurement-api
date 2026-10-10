from typing import Any
import geopandas as gpd
from pyproj import CRS, Geod
from shapely.geometry.base import BaseGeometry


def _choose_measurement_crs(gdf: gpd.GeoDataFrame, source_crs: str | None) -> CRS:
    source = CRS.from_user_input(source_crs or gdf.crs)
    if source.is_projected and source.axis_info:
        units = {axis.unit_name.lower() for axis in source.axis_info if axis.unit_name}
        if units and units.issubset({"metre", "meter", "metres", "meters"}):
            return source

    try:
        estimated = gdf.estimate_utm_crs()
        if estimated is not None:
            candidate = CRS.from_user_input(estimated)
            projected = gdf.to_crs(candidate)
            bounds = projected.total_bounds
            if abs(float(bounds[2] - bounds[0])) <= 1_000_000 and abs(float(bounds[3] - bounds[1])) <= 1_000_000:
                return candidate
    except Exception:
        pass
    return CRS.from_epsg(6933)


def _geodesic_length(geometry: BaseGeometry, source: CRS) -> float | None:
    if not source.is_geographic or geometry.geom_type not in ("LineString", "MultiLineString"):
        return None
    geod = source.get_geod() if hasattr(source, "get_geod") else Geod(ellps="WGS84")
    try:
        if geometry.geom_type == "LineString":
            return float(abs(geod.geometry_length(geometry)))
        return float(sum(abs(geod.geometry_length(part)) for part in geometry.geoms))
    except Exception:
        return None


def measure_features(gdf: gpd.GeoDataFrame, source_crs: str | None) -> list[dict[str, Any]]:
    source = CRS.from_user_input(source_crs or gdf.crs)
    measurement_crs = _choose_measurement_crs(gdf, source_crs)
    projected = gdf.to_crs(measurement_crs)
    results = []

    for index, ((_, row), (_, projected_row)) in enumerate(zip(gdf.iterrows(), projected.iterrows())):
        geometry = row.geometry
        projected_geometry = projected_row.geometry
        geometry_type = geometry.geom_type if geometry is not None else None
        result = {
            "feature_id": index,
            "geometry_type": geometry_type,
            "source_crs": source.to_string(),
            "measurement_crs": measurement_crs.to_string(),
            "measurement": None,
            "unit": None,
            "status": "UNSUPPORTED",
            "message": "No measurement is defined for this geometry type.",
        }
        if geometry is None or geometry.is_empty:
            result.update(status="SKIPPED", message="Geometry is missing or empty.")
        elif geometry_type in ("Polygon", "MultiPolygon"):
            area = float(projected_geometry.area)
            result.update(measurement=area, unit="m²", status="COMPLETED", message=None)
            result["measurement_hectares"] = area / 10_000
        elif geometry_type in ("LineString", "MultiLineString"):
            length = _geodesic_length(geometry, source)
            if length is None:
                length = float(projected_geometry.length)
            result.update(measurement=length, unit="m", status="COMPLETED", message=None)
            result["measurement_km"] = length / 1_000
        results.append(result)
    return results
