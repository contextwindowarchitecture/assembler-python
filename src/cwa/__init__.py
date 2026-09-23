"""CWA reference assembler. See docs/DESIGN.md."""
from .assemble import AssemblyResult, assemble
from .snapshot import Snapshot, SnapshotError

__all__ = ["AssemblyResult", "Snapshot", "SnapshotError", "assemble"]
__version__ = "0.0.1"
