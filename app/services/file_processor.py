from pathlib import Path
import zipfile
import geopandas as gpd


class FileProcessingError(Exception):
    """Raised when an uploaded file is invalid or cannot be parsed."""


def validate_upload(filename: str) -> tuple[str, str]:
    name = Path(filename.replace("\\", "/")).name
    if not name or name in {".", ".."}:
        raise FileProcessingError("A valid filename is required.")
    suffix = Path(name).suffix.lower()
    if suffix == ".kml":
        return name, "kml"
    if suffix == ".zip":
        return name, "shapefile_zip"
    raise FileProcessingError("Unsupported file type. Upload a .kml or .zip containing a Shapefile.")


def _check_zip(path: Path) -> None:
    try:
        with zipfile.ZipFile(path) as archive:
            bad_member = archive.testzip()
            if bad_member:
                raise FileProcessingError(f"The ZIP archive contains a corrupt member: {bad_member}")
            names = [n for n in archive.namelist() if not n.endswith("/")]
            lower_names = {n.lower() for n in names}
            shapefiles = [n for n in names if n.lower().endswith(".shp")]
            if not shapefiles:
                raise FileProcessingError("The ZIP archive does not contain a .shp file.")
            for shp in shapefiles:
                stem = shp[:-4].lower()
                if stem + ".shx" not in lower_names or stem + ".dbf" not in lower_names:
                    raise FileProcessingError("The ZIP must include matching .shp, .shx, and .dbf files.")
    except zipfile.BadZipFile as exc:
        raise FileProcessingError("The uploaded .zip file is not a valid ZIP archive.") from exc


def read_geospatial_file(path: Path, file_kind: str) -> gpd.GeoDataFrame:
    try:
        if file_kind == "shapefile_zip":
            _check_zip(path)
            gdf = gpd.read_file(f"zip://{path.as_posix()}")
        elif file_kind == "kml":
            try:
                gdf = gpd.read_file(path, driver="KML")
            except Exception:
                gdf = gpd.read_file(path)
        else:
            raise FileProcessingError("Unsupported file format.")
    except FileProcessingError:
        raise
    except Exception as exc:
        raise FileProcessingError(
            "Could not read the file. Verify it is valid and the installed geospatial driver supports it."
        ) from exc

    if not isinstance(gdf, gpd.GeoDataFrame) or gdf.geometry.name not in gdf.columns:
        raise FileProcessingError("The file does not contain a readable geometry column.")
    if gdf.crs is None:
        if file_kind == "kml":
            gdf = gdf.set_crs("EPSG:4326")
        else:
            raise FileProcessingError("The Shapefile has no CRS information. Include a valid .prj file.")
    return gdf
