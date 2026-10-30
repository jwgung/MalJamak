"""트레이 아이콘과 같은 모양으로 exe 아이콘(.ico)을 만든다."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from maljamak.tray import COLORS, _icon  # noqa: E402

out = Path(__file__).resolve().parent / "icon.ico"
_icon(COLORS["listening"]).save(out, sizes=[(16, 16), (32, 32), (48, 48), (64, 64)])
print(out)
