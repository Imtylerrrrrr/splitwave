import re
from pathlib import Path

from common import pitch_filter


def test_smoke_pitch_filter_matches_app():
    """tools/ffmpeg/smoke.sh 는 MSYS 파이썬에서 common 을 import 못 해 필터 문자열을 복사해 둔다.
    앱의 필터 체인이 바뀌면 이 테스트가 깨져서 smoke.sh 갱신을 강제한다."""
    text = (Path(__file__).resolve().parents[1] / "tools" / "ffmpeg" / "smoke.sh").read_text()
    m = re.search(r'PITCH_FILTER="\$\{PITCH_FILTER:-([^}]*)\}"', text)
    assert m, "PITCH_FILTER default not found in smoke.sh"
    assert m.group(1) == pitch_filter(2)
