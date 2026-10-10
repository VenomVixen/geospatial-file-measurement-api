from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def kml_bytes():
    return b"""<?xml version="1.0" encoding="UTF-8"?>
    <kml xmlns="http://www.opengis.net/kml/2.2"><Document>
      <Placemark><name>Test polygon</name><Polygon><outerBoundaryIs><LinearRing>
        <coordinates>0,0 0.01,0 0.01,0.01 0,0.01 0,0</coordinates>
      </LinearRing></outerBoundaryIs></Polygon></Placemark>
      <Placemark><name>Test line</name><LineString><coordinates>0,0 0.01,0.01</coordinates></LineString></Placemark>
      <Placemark><name>Test point</name><Point><coordinates>0.005,0.005</coordinates></Point></Placemark>
    </Document></kml>"""

def test_root_and_health():
    assert client.get("/").status_code == 200
    assert client.get("/health").json()["status"] == "healthy"

def test_rejects_unsupported_extension():
    response = client.post("/api/files/", files={"file": ("notes.txt", b"not geospatial", "text/plain")})
    assert response.status_code == 422

def test_rejects_invalid_kml():
    response = client.post("/api/files/", files={"file": ("broken.kml", b"<not-kml>", "application/vnd.google-earth.kml+xml")})
    assert response.status_code == 422

def test_upload_and_retrieve_kml():
    response = client.post("/api/files/", files={"file": ("sample.kml", kml_bytes(), "application/vnd.google-earth.kml+xml")})
    assert response.status_code == 201, response.text
    data = response.json()
    file_id = data["id"]
    assert data["feature_count"] == 3
    assert data["status"] == "COMPLETED"
    assert client.get(f"/api/files/{file_id}/").status_code == 200
    features = client.get(f"/api/files/{file_id}/features/").json()
    assert len(features["features"]) == 3
    measurements = client.get(f"/api/files/{file_id}/measurements/").json()["measurements"]
    assert len(measurements) == 3
    assert measurements[0]["status"] == "COMPLETED"
    assert measurements[0]["unit"] == "m²"
    assert measurements[1]["unit"] == "m"
    assert measurements[2]["status"] == "UNSUPPORTED"

def test_unknown_id_returns_404():
    assert client.get("/api/files/no-such-id/").status_code == 404
    assert client.get("/api/files/no-such-id/measurements/").status_code == 404

def test_download_source():
    response = client.post("/api/files/", files={"file": ("sample.kml", kml_bytes(), "application/vnd.google-earth.kml+xml")})
    file_id = response.json()["id"]
    download = client.get(f"/api/files/{file_id}/download/")
    assert download.status_code == 200
    assert b"<kml" in download.content
