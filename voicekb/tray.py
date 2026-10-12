"""트레이 아이콘. 색으로 상태를 보여준다: 회색 대기, 빨강 듣는 중, 파랑 자막 중, 주황 엔진 준비 중."""

import platform

from PIL import Image, ImageDraw

COLORS = {"idle": "#6b7280", "listening": "#dc2626", "captions": "#2563eb", "starting": "#d97706"}


def _icon(color: str) -> Image.Image:
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((2, 2, size - 2, size - 2), fill=color)
    # 마이크 모양
    d.rounded_rectangle((24, 12, 40, 38), radius=8, fill="white")
    d.arc((17, 22, 47, 46), start=0, end=180, fill="white", width=4)
    d.line((32, 46, 32, 53), fill="white", width=4)
    d.line((24, 53, 40, 53), fill="white", width=4)
    return img


class Tray:
    def __init__(self, app):
        import pystray

        self.app = app
        hub = app.hub
        menu = pystray.Menu(
            pystray.MenuItem(lambda _: "음성 입력 정지" if hub.listening else "음성 입력 시작",
                             lambda: app.toggle_input()),
            pystray.MenuItem(lambda _: "PC 소리 자막 끄기" if hub.captions_on else "PC 소리 자막 켜기",
                             lambda: app.toggle_captions()),
            pystray.MenuItem("현장 자막 (교정 화면)…", lambda: app.open_operator()),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("설정…", lambda: app.open_settings(), default=True),
            pystray.MenuItem("종료", lambda: app.quit()),
        )
        self.icon = pystray.Icon("voice-keyboard", _icon(COLORS["starting"]), "Voice Keyboard", menu)
        self._images = {k: _icon(v) for k, v in COLORS.items()}

    def _state(self) -> tuple[str, str]:
        hub = self.app.hub
        if hub.engine is None:
            return "starting", "Voice Keyboard — 엔진 준비 중"
        if hub.listening:
            return "listening", "Voice Keyboard — 듣는 중"
        if hub.captions_on or hub.live_on:
            return "captions", "Voice Keyboard — 자막 중"
        return "idle", "Voice Keyboard — 대기"

    def refresh(self) -> None:
        """서버 스레드에서 불린다. macOS 는 AppKit 을 메인 스레드에서만 만질 수 있어 넘겨 준다."""
        if platform.system() == "Darwin":
            try:
                from PyObjCTools import AppHelper

                AppHelper.callAfter(self._refresh)
                return
            except ImportError:
                pass
        self._refresh()

    def _refresh(self) -> None:
        state, title = self._state()
        self.icon.icon = self._images[state]
        self.icon.title = title
        self.icon.update_menu()

    def notify(self, message: str) -> None:
        try:
            self.icon.notify(message, "Voice Keyboard")
        except Exception:
            pass  # 알림을 지원하지 않는 환경

    def run(self) -> None:
        self.icon.run(setup=lambda icon: (setattr(icon, "visible", True), self._refresh()))

    def stop(self) -> None:
        self.icon.stop()
