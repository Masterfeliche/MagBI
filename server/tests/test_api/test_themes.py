"""Built-in themes are complete and served from their one JSON copy."""

from __future__ import annotations

from magbi.themes import (
    DEFAULT_THEME,
    load_theme,
    missing_tokens,
    theme_colours,
    theme_ids,
    token_names,
    tokenise_definition,
)
from tests.test_api.conftest import ApiEnv


def test_every_built_in_theme_is_complete() -> None:
    assert DEFAULT_THEME in theme_ids()
    for theme_id in theme_ids():
        assert missing_tokens(load_theme(theme_id)) == [], theme_id


def test_enterprise_light_keeps_the_erp_native_colours() -> None:
    theme = load_theme("enterprise-light")
    assert theme["data"]["categorical"] == ["#3F6FB0", "#5F8BC9", "#82A6D6", "#B3C3D8"]
    assert theme["surface"]["page"] == "#EEF2F7"
    assert {"#4E9E77", "#D49A55", "#C76E6C", "#9EABBC"} <= theme_colours(theme)
    assert token_names(theme)["frame"] == "#F8FAFC"
    assert "overlay" not in token_names(theme)


def test_themes_are_served(api: ApiEnv) -> None:
    listed = api.client.get("/api/v1/themes")
    assert listed.status_code == 200, listed.text
    assert DEFAULT_THEME in [theme["id"] for theme in listed.json()]
    one = api.client.get(f"/api/v1/themes/{DEFAULT_THEME}")
    assert one.json()["name"] == "Enterprise Light"
    assert api.client.get("/api/v1/themes/nope").status_code == 404


def test_frame_colours_become_token_names() -> None:
    definition = {
        "theme": {"colors": ["#3F6FB0"]},
        "pages": [{"visuals": [
            {"type": "frame", "properties": {"fill": "#f8fafc", "border": "#D3DCE6"}},
            {"type": "frame", "properties": {"fill": "#123456", "border": "line"}},
            {"type": "kpi", "properties": {"fill": "#F8FAFC"}},
        ]}],
    }
    theme = load_theme("enterprise-light")
    assert tokenise_definition(definition, theme) == 3
    visuals = definition["pages"][0]["visuals"]
    assert visuals[0]["properties"] == {"fill": "frame", "border": "line"}
    assert visuals[1]["properties"] == {"fill": "#123456", "border": "line"}
    assert visuals[2]["properties"] == {"fill": "#F8FAFC"}
    assert definition["theme"]["id"] == "enterprise-light"
    assert tokenise_definition(definition, theme) == 0
