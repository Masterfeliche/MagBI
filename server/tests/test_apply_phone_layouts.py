import json

from scripts.apply_phone_layouts import DEFAULT, with_phone


def test_adds_only_the_phone_layout_to_matching_pages() -> None:
    definition = {"name": "r", "pages": [{"name": "p1", "visuals": [{"id": "a", "x": 0}]}, {"name": "p2", "visuals": []}]}
    phone = {"visuals": [{"id": "a", "x": 10, "y": 10, "width": 340, "height": 120}]}
    out = with_phone(definition, [{"name": "p1", "phone": phone}])
    assert out["pages"][0] == {"name": "p1", "visuals": [{"id": "a", "x": 0}], "phone": phone}
    assert "phone" not in out["pages"][1]
    assert "phone" not in definition["pages"][0]


def test_warehouse_layouts_fit_the_phone_canvas() -> None:
    plan = json.loads(DEFAULT.read_text(encoding="utf-8"))
    assert len(plan["reports"]) == 3
    for report in plan["reports"].values():
        for page in report["pages"]:
            boxes = page["phone"]["visuals"]
            assert boxes
            for box in boxes:
                assert 0 <= box["x"] and box["x"] + box["width"] <= 360
