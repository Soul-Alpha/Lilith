from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def test_forensics_models_import() -> None:
    from lilith.forensics.models import ExitReason, Side

    assert Side.BUY.value == "BUY"
    assert ExitReason.STOP_LOSS.value == "STOP_LOSS"
