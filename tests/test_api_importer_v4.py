import json
from pathlib import Path
from thomas.core.api_importer import ApiImporter

def test_v4_freeze_snapshot_and_deepobject_query(tmp_path: Path):
    spec = {
        "openapi": "3.0.0",
        "info": {"title": "Demo API", "version": "1.0.0"},
        "servers": [{"url": "https://example.com"}],
        "paths": {
            "/search": {
                "get": {
                    "operationId": "search",
                    "parameters": [
                        {"name": "filter", "in": "query", "required": False, "style": "deepObject", "explode": True,
                         "schema": {"type":"object", "additionalProperties": {"type":"string"}}}
                    ],
                    "responses": {"200": {"description": "ok"}}
                }
            }
        }
    }
    spec_path = tmp_path / "spec.json"
    spec_path.write_text(json.dumps(spec), encoding="utf-8")

    imp = ApiImporter(storage_path=tmp_path / "store.json")
    imp.api_name_hint = "demo"
    tools = imp.import_from_file(str(spec_path), freeze_spec=True)
    assert len(tools) == 1
    imp.save_imported_api("demo", "file://" + str(spec_path), tools)

    saved = json.loads((tmp_path / "store.json").read_text(encoding="utf-8"))
    assert saved["demo"]["spec_snapshot"]["format"] == "gzip_base64"
