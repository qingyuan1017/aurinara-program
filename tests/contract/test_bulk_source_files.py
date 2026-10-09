"""Contract surface for the atomic bulk source-file upload operation."""

from app.main import app


def _resolve_ref(schema: dict[str, object], ref: str) -> dict[str, object]:
    assert ref.startswith("#/components/schemas/")
    name = ref.rsplit("/", 1)[-1]
    components = schema["components"]
    assert isinstance(components, dict)
    schemas = components["schemas"]
    assert isinstance(schemas, dict)
    resolved = schemas[name]
    assert isinstance(resolved, dict)
    return resolved


def test_bulk_upload_operation_is_published_with_201_items_array() -> None:
    schema = app.openapi()
    paths = schema["paths"]
    assert isinstance(paths, dict)

    bulk_path = "/api/v1/studies/{study_id}/source-files:bulk"
    assert bulk_path in paths
    operation = paths[bulk_path]["post"]

    responses = operation["responses"]
    assert "201" in responses
    content = responses["201"]["content"]["application/json"]
    body_schema = _resolve_ref(schema, content["schema"]["$ref"])

    # Response is an object with an `items` array of SourceFileResponse objects.
    items_schema = body_schema["properties"]["items"]
    assert items_schema["type"] == "array"
    item_schema = _resolve_ref(schema, items_schema["items"]["$ref"])

    # snake_case SourceFileResponse-shaped fields, no object-store locator leaked.
    properties = item_schema["properties"]
    assert {
        "id",
        "study_id",
        "artifact_id",
        "filename",
        "media_type",
        "sha256",
        "size",
        "created_by",
        "created_at",
    } <= set(properties)
    assert "object_key" not in properties
