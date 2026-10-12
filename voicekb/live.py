"""현장 자막: STT 가 만든 조각(초안)을 조작자가 검토·수정해 내보내고, 내보낸 것만 자막 화면에 띄운다.

review 방식
  auto    조각마다 카운트다운이 돌고, 조작자가 손대지 않으면 자동으로 내보낸다.
  manual  조작자가 내보내기를 눌러야만 나간다.
고치기 시작하면(editing) 카운트다운이 멈춘다. 이미 내보낸 조각도 고칠 수 있고, 자막 화면에 그대로 반영된다.
"""

import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

KEEP_ITEMS = 200  # 교정 화면에 보여줄 최근 조각 수


@dataclass
class Chunk:
    id: int
    text: str
    created: float
    status: str = "pending"  # pending | sent | discarded
    deadline: float | None = None  # auto 방식의 자동 내보내기 시각
    editing: bool = False
    sent_at: float | None = None
    edited: bool = False


@dataclass
class LiveSession:
    transcript_dir: Path
    items: list[Chunk] = field(default_factory=list)
    _seq: int = 0
    _file: Path | None = None
    started: datetime | None = None

    def start(self) -> None:
        self.items.clear()
        self.started = datetime.now()
        self._file = None

    # ───────── 조각 ─────────

    def add_draft(self, text: str, review: str, countdown: float) -> Chunk | None:
        text = " ".join(text.split())
        if not text:
            return None
        self._seq += 1
        now = time.time()
        chunk = Chunk(id=self._seq, text=text, created=now,
                      deadline=now + countdown if review == "auto" else None)
        self.items.append(chunk)
        self._trim()
        return chunk

    def find(self, chunk_id: int) -> Chunk | None:
        return next((c for c in self.items if c.id == chunk_id), None)

    def send(self, chunk_id: int, text: str | None = None) -> bool:
        """내보내기. 이미 내보낸 조각에 text 를 주면 수정으로 처리한다."""
        chunk = self.find(chunk_id)
        if chunk is None or chunk.status == "discarded":
            return False
        if text is not None:
            text = " ".join(text.split())
            if not text:
                return self.discard(chunk_id)
            if text != chunk.text:
                chunk.text, chunk.edited = text, True
        chunk.editing = False
        if chunk.status != "sent":
            chunk.status, chunk.sent_at = "sent", time.time()
        self._write()
        return True

    def discard(self, chunk_id: int) -> bool:
        chunk = self.find(chunk_id)
        if chunk is None:
            return False
        was_sent = chunk.status == "sent"
        chunk.status, chunk.editing = "discarded", False
        if was_sent:
            self._write()
        return True

    def update_text(self, chunk_id: int, text: str, countdown: float) -> bool:
        """고친 내용을 저장만 한다(내보내지 않음). 자동 방식이면 카운트다운을 다시 시작한다."""
        chunk = self.find(chunk_id)
        if chunk is None or chunk.status == "discarded":
            return False
        text = " ".join(text.split())
        if text and text != chunk.text:
            chunk.text, chunk.edited = text, True
            if chunk.status == "sent":
                self._write()
        chunk.editing = False
        if chunk.status == "pending" and chunk.deadline is not None:
            chunk.deadline = time.time() + countdown
        return True

    def set_editing(self, chunk_id: int, on: bool, countdown: float) -> bool:
        chunk = self.find(chunk_id)
        if chunk is None:
            return False
        chunk.editing = on
        # 고치다 그만두면 카운트다운을 처음부터 다시 준다.
        if not on and chunk.status == "pending" and chunk.deadline is not None:
            chunk.deadline = time.time() + countdown
        return True

    def set_review(self, review: str, countdown: float) -> None:
        now = time.time()
        for c in self.items:
            if c.status == "pending":
                c.deadline = now + countdown if review == "auto" else None

    def due(self) -> list[Chunk]:
        now = time.time()
        return [c for c in self.items
                if c.status == "pending" and not c.editing and c.deadline is not None and c.deadline <= now]

    def send_all_pending(self) -> int:
        pending = [c for c in self.items if c.status == "pending"]
        for c in pending:
            self.send(c.id)
        return len(pending)

    # ───────── 화면용 데이터 ─────────

    def queue_view(self) -> list[dict]:
        now = time.time()
        out = []
        for c in self.items[-KEEP_ITEMS:]:
            d = asdict(c)
            d["remaining"] = max(0.0, c.deadline - now) if c.deadline and c.status == "pending" else None
            out.append(d)
        return out

    def display_view(self, limit: int = 40) -> list[dict]:
        sent = [c for c in self.items if c.status == "sent"]
        return [{"id": c.id, "text": c.text} for c in sent[-limit:]]

    # ───────── 기록 ─────────

    def transcript_path(self) -> Path:
        if self._file is None:
            stamp = (self.started or datetime.now()).strftime("%Y-%m-%d_%H%M%S")
            self._file = self.transcript_dir / f"자막_{stamp}.txt"
        return self._file

    def _write(self) -> None:
        """내보낸(수정 반영된) 조각 전체를 시간과 함께 다시 쓴다. 조각 수가 많지 않아 매번 통째로 쓴다."""
        sent = [c for c in self.items if c.status == "sent"]
        path = self.transcript_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        lines = [f"[{datetime.fromtimestamp(c.sent_at or c.created):%H:%M:%S}] {c.text}" for c in sent]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def _trim(self) -> None:
        # 오래된 조각은 교정 화면에서만 빠진다. 기록 파일은 이미 쓴 내용을 유지해야 하므로 sent 는 남긴다.
        if len(self.items) > KEEP_ITEMS * 5:
            keep_from = len(self.items) - KEEP_ITEMS * 5
            self.items = [c for i, c in enumerate(self.items) if i >= keep_from or c.status == "sent"]
