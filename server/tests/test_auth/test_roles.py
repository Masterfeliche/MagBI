from magbi.auth.roles import Actor, permits


def _user(*memberships: tuple[str, str], platform: bool = False) -> Actor:
    return Actor(
        "user",
        "user-1",
        "ada@example.com",
        "Ada",
        platform_admin=platform,
        memberships=memberships,
    )


def test_roles_follow_the_permission_order() -> None:
    editor = _user(("ws", "editor"))
    assert permits(editor, "ws", "viewer")
    assert permits(editor, "ws", "editor")
    assert not permits(editor, "ws", "admin")
    assert not permits(editor, "other", "viewer")
    assert permits(_user(platform=True), "other", "admin")
    embed = Actor(
        "embed", "ada@example.com", "ada@example.com", "Ada", workspace_id="ws"
    )
    assert not permits(embed, "ws", "viewer")
    service = Actor("service", "svc", "", "", workspace_id="ws")
    assert not permits(service, "ws", "editor")
