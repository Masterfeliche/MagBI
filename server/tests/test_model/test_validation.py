from magbi.model.schema import DatasetDefinition
from magbi.model.validation import validate_document, validate_model
from tests.test_model.test_paths import chain, rel
from tests.test_model.test_schema import col, definition, key, table


def test_a_clean_chain_has_no_errors() -> None:
    report = validate_model(chain())
    assert report.ok and report.errors == []
    assert report.checks_deferred == ("measure_expressions", "rls_expressions")
    assert report.to_dict()["ok"] is True


def test_a_cycle_is_an_error() -> None:
    model = definition(
        table("A", key(), col("b_id")),
        table("B", key(), col("c_id")),
        table("C", key(), col("a_id")),
        relationships=[
            rel("A", "b_id", "B"),
            rel("B", "c_id", "C"),
            rel("C", "a_id", "A"),
        ],
    )
    report = validate_model(model)
    assert [e.code for e in report.errors] == ["CYCLE"]
    assert "A -> B -> C -> A" in report.errors[0].message


def test_an_ambiguous_path_is_an_error() -> None:
    model = definition(
        table("Invoices", key(), col("a_id"), col("b_id")),
        table("Channel", key(), col("region_id")),
        table("Owner", key(), col("region_id")),
        table("Region", key()),
        relationships=[
            rel("Invoices", "a_id", "Channel"),
            rel("Invoices", "b_id", "Owner"),
            rel("Channel", "region_id", "Region"),
            rel("Owner", "region_id", "Region"),
        ],
    )
    report = validate_model(model)
    assert report.errors and {e.code for e in report.errors} == {"AMBIGUOUS_PATH"}
    assert any("Invoices" in e.message and "Region" in e.message for e in report.errors)


def test_raw_document_problems_get_stable_codes() -> None:
    duplicate = validate_document(
        {"tables": [{"name": "T", "columns": []}, {"name": "T", "columns": []}]}
    )
    assert duplicate.errors[0].code == "DUPLICATE_TABLE"
    missing = {
        "tables": [
            {
                "name": "T",
                "columns": [
                    {"name": "id", "data_type": "integer", "is_primary_key": True}
                ],
            },
        ],
        "relationships": [
            {
                "from": {"table": "T", "column": "id"},
                "to": {"table": "Missing", "column": "id"},
                "cardinality": "many-to-one",
            }
        ],
    }
    assert validate_document(missing).errors[0].code == "MISSING_REFERENCE"
    many = validate_document(
        {
            "relationships": [
                {
                    "from": {"table": "A", "column": "id"},
                    "to": {"table": "B", "column": "id"},
                    "cardinality": "many-to-many",
                }
            ]
        }
    )
    assert many.errors[0].code == "UNSUPPORTED"


def test_validate_document_accepts_a_round_trip() -> None:
    raw = chain().model_dump(mode="json", by_alias=True)
    assert validate_document(raw).ok
    assert isinstance(chain(), DatasetDefinition)
