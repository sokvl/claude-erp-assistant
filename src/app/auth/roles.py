from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum


class Role(StrEnum):
    CONSULTANT = "consultant"
    MANAGER = "manager"
    ADMIN = "admin"


GRANTS: Mapping[Role, frozenset[Role]] = {
    Role.CONSULTANT: frozenset({Role.CONSULTANT}),
    Role.MANAGER: frozenset({Role.CONSULTANT, Role.MANAGER}),
    Role.ADMIN: frozenset({Role.ADMIN}),
}


@dataclass(frozen=True)
class Principal:
    username: str
    role: Role


def allows(role: Role, required: Role) -> bool:
    return required in GRANTS[role]
