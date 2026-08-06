from __future__ import annotations

import sys

from alembic import command
from alembic.config import Config


def alembic_config() -> Config:
    return Config("alembic.ini")


def upgrade(revision: str = "head") -> None:
    command.upgrade(alembic_config(), revision)


def downgrade(revision: str = "-1") -> None:
    command.downgrade(alembic_config(), revision)


def main(argv: list[str] | None = None) -> None:
    argv = argv or sys.argv[1:]
    action = argv[0] if argv else "upgrade"
    revision = argv[1] if len(argv) > 1 else None

    if action == "upgrade":
        upgrade(revision or "head")
        return
    if action == "downgrade":
        downgrade(revision or "-1")
        return

    raise SystemExit(
        "Usage: python3 -m storage.migrate [upgrade [revision]|downgrade [revision]]"
    )


if __name__ == "__main__":
    main()
