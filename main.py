"""말자막 — 트레이에 상주하며 아무 입력창에나 음성으로 입력하고, PC 소리를 실시간 번역 자막으로 띄운다."""

import argparse
import multiprocessing


def _log_to_file(name: str) -> None:
    """콘솔 없이 실행되면(빌드된 exe) 출력을 설정 폴더의 로그 파일로 보낸다."""
    import sys

    if sys.stdout is not None and sys.stderr is not None:
        return
    from maljamak.config import config_dir

    path = config_dir() / name
    path.parent.mkdir(parents=True, exist_ok=True)
    log = open(path, "a", encoding="utf-8", buffering=1)
    sys.stdout = sys.stderr = log


def main() -> None:
    parser = argparse.ArgumentParser(description="말자막")
    parser.add_argument("--port", type=int, help="로컬 서버 포트 (기본: 설정값 8765)")
    parser.add_argument("--no-tray", action="store_true", help="트레이 아이콘 없이 실행 (서버·엔진만)")
    parser.add_argument("--dry-run", action="store_true", help="붙여넣지 않고 콘솔에만 출력")
    parser.add_argument("--overlay", action="store_true", help=argparse.SUPPRESS)  # 자막 창 프로세스
    parser.add_argument("--parent", type=int, help=argparse.SUPPRESS)  # 자막 창: 부모가 사라지면 종료
    args = parser.parse_args()

    if not args.overlay:
        from maljamak.config import migrate_legacy_dir

        migrate_legacy_dir()  # 로그 파일이 새 폴더를 만들기 전에
    _log_to_file("overlay.log" if args.overlay else "app.log")

    if args.overlay:
        from maljamak.overlay import run_overlay

        run_overlay(args.port or 8765, args.parent)
        return

    from maljamak.app import App

    App(port=args.port, dry_run=args.dry_run, use_tray=not args.no_tray).run()


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
