import pytest

from magbi.transforms.errors import TransformError
from magbi.transforms.steps import STEP_TYPES, parse_step

_SAMPLES: dict[str, dict[str, object]] = {
    "filterRows": {"column": "Status", "operator": "eq", "value": "Open"},
    "removeRows": {"column": "Status", "operator": "isNull"},
    "selectColumns": {"columns": ["Amount"]},
    "removeColumns": {"columns": ["Note"]},
    "renameColumn": {"oldName": "Amt", "newName": "Amount"},
    "changeType": {"column": "Amount", "toType": "decimal"},
    "addColumn": {"name": "Double", "expression": "Amount * 2"},
    "replaceValues": {"column": "Status", "find": "Open", "replaceWith": "Pending"},
    "fillDown": {"columns": ["Manager"]},
    "fillValue": {"column": "Note", "value": ""},
    "splitColumn": {
        "column": "Name",
        "delimiter": " ",
        "newColumnNames": ["First", "Last"],
    },
    "mergeColumns": {
        "columns": ["First", "Last"],
        "separator": " ",
        "newColumnName": "Name",
    },
    "trimText": {"column": "Name"},
    "uppercase": {"column": "Name"},
    "lowercase": {"column": "Name"},
    "extractDate": {"column": "sold", "part": "year"},
    "sortRows": {"columns": [{"column": "Amount", "direction": "desc"}]},
    "distinctRows": {},
    "topN": {"count": 10, "orderBy": "Amount", "direction": "desc"},
    "unpivot": {
        "idColumns": ["Id"],
        "valueColumns": ["Jan", "Feb"],
        "attributeName": "Month",
        "valueName": "Amount",
    },
    "pivot": {"keyColumn": "Month", "valueColumn": "Amount", "aggregate": "sum"},
    "groupBy": {
        "groupColumns": ["Status"],
        "aggregations": [{"column": "Amount", "function": "sum", "alias": "Total"}],
    },
}


def test_every_step_type_parses() -> None:
    assert set(_SAMPLES) == STEP_TYPES
    for name, body in _SAMPLES.items():
        step = parse_step({"type": name, **body})
        assert step.type == name


def test_an_unknown_type_and_a_missing_field_are_rejected() -> None:
    with pytest.raises(TransformError) as unknown:
        parse_step({"type": "dropTable"})
    assert unknown.value.code == "TRANSFORM_STEP"
    with pytest.raises(TransformError) as missing:
        parse_step({"type": "renameColumn", "oldName": "A"})
    assert missing.value.code == "TRANSFORM_STEP"
