"""CWA reference assembler. See docs/DESIGN.md."""
from .assemble import AssemblyResult, assemble
from .snapshot import Snapshot, SnapshotError, UnsupportedComponentError
from .tokenize import Tokenizer

__all__ = ["AssemblyResult", "Snapshot", "SnapshotError", "Tokenizer", "UnsupportedComponentError", "assemble"]
__version__ = "0.0.1"
