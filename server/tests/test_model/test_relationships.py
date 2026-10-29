import uuid

import pytest
from pydantic import ValidationError

from magbi.model.relationships import add_relationship, remove_relationship
from magbi.model.schema import ModelSchemaError
from tests.test_model.test_schema import invoices_model, link


def test_add_and_remove_do_not_mutate_the_input() -> None:
    original = invoices_model()
    first = original.relationships[0]
    without = remove_relationship(original, first.id)
    assert without.relationships == []
    assert original.relationships[0].id == first.id
    restored = add_relationship(without, first)
    assert restored.relationships[0].from_.table == "Invoices"
    assert restored.relationships[0].to.table == "Department"


def test_unknown_relationship_cannot_be_removed() -> None:
    with pytest.raises(ModelSchemaError, match="does not exist"):
        remove_relationship(invoices_model(), uuid.uuid4())


def test_adding_a_relationship_to_a_missing_table_is_rejected() -> None:
    with pytest.raises(ValidationError, match="does not exist"):
        add_relationship(invoices_model(), link("Invoices", "Missing"))


def test_adding_a_second_active_relationship_is_rejected() -> None:
    with pytest.raises(ValidationError, match="more than one active"):
        add_relationship(invoices_model(), link("Invoices", "Department"))
