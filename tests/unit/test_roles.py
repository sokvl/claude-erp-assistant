import pytest

from app.auth.roles import Role, allows


# A manager can do everything a consultant can; an admin manages accounts and is
# deliberately not a manager, so account work and finance stay separate grants.
@pytest.mark.parametrize(
    ("role", "required", "expected"),
    [
        (Role.CONSULTANT, Role.CONSULTANT, True),
        (Role.CONSULTANT, Role.MANAGER, False),
        (Role.CONSULTANT, Role.ADMIN, False),
        (Role.MANAGER, Role.CONSULTANT, True),
        (Role.MANAGER, Role.MANAGER, True),
        (Role.MANAGER, Role.ADMIN, False),
        (Role.ADMIN, Role.CONSULTANT, False),
        (Role.ADMIN, Role.MANAGER, False),
        (Role.ADMIN, Role.ADMIN, True),
    ],
    ids=[
        "consultant_as_consultant", "consultant_as_manager", "consultant_as_admin",
        "manager_as_consultant", "manager_as_manager", "manager_as_admin",
        "admin_as_consultant", "admin_as_manager", "admin_as_admin",
    ],
)
def test_allows_role_against_required_role_returns_the_grant(role, required, expected):
    # Arrange / Act
    granted = allows(role, required)

    # Assert
    assert granted is expected
