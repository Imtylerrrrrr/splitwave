"""템포 추종 앱의 PyInstaller 진입 스크립트.

--selftest 면 화면 없이 번들을 점검하고 종료 코드로 알린다 (0 = 정상).
창 없는 빌드는 콘솔 출력이 보이지 않아서, 환경변수 SELFTEST_LOG 가 있으면
점검 출력을 그 파일로 보낸다 (CI 가 실패 이유를 읽는다).
"""
import os
import sys
import traceback


def run_selftest() -> int:
    log = os.environ.get("SELFTEST_LOG")
    if log:
        sys.stdout = sys.stderr = open(log, "a", encoding="utf-8")
    try:
        from tempofollow.selftest import selftest
        return selftest()
    except Exception:
        traceback.print_exc()
        return 1
    finally:
        if log:
            sys.stdout.flush()


def main():
    if "--selftest" in sys.argv:
        sys.exit(run_selftest())
    from tempofollow.app import main as app_main
    app_main()


if __name__ == "__main__":
    main()
