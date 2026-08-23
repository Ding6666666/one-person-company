from pathlib import Path

from dsh_company.application.chat_coordinator import ChatCoordinator
from dsh_company.foundation.assembly import create_production_assembly
from dsh_company.foundation.config import Settings


def test_production_assembly_exposes_and_disposes_chat_coordinator(
    tmp_path: Path,
) -> None:
    assembly = create_production_assembly(
        Settings(
            data_root=tmp_path / "data",
            session_root=tmp_path / "sessions",
        )
    )
    try:
        assert isinstance(assembly.chat_dispatch_queue, ChatCoordinator)
    finally:
        assembly.dispose()
