"""현장 자막: STT 가 만든 조각(초안)을 조작자가 검토·수정해 내보내고, 내보낸 것만 자막 화면에 띄운다.

review 방식
  auto    조각마다 카운트다운이 돌고, 조작자가 손대지 않으면 자동으로 내보낸다.
  manual  조작자가 내보내기를 눌러야만 나간다.
고치기 시작하면(editing) 카운트다운이 멈춘다. 이미 내보낸 조각도 고칠 수 있고, 자막 화면에 그대로 반영된다.
"""

import re
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

KEEP_ITEMS = 200  # 교정 화면에 보여줄 최근 조각 수

# ───────── 문장 경계 ─────────
# Chrome 은 한국어 결과에 문장부호를 넣지 않는다. 조각은 나오는 즉시 내보내되, 다음 조각이 왔을 때
# 앞뒤 문맥으로 "앞 조각이 문장 끝이었나"를 정한다. 줄바꿈은 다음 조각이 화면에 나올 때만 필요하므로
# 한 조각 늦게 판단해도 지연이 없다.

_QUESTION_END = re.compile(r"(까|까요|나요|죠|니)$")
_SENTENCE_END = re.compile(r"(니다|어요|아요|에요|예요|세요|해요|래요|네요|군요|지요|거든요|다|요)$")
_CONTINUES = re.compile(r"(고|며|서|는데|은데|인데|지만|니까|면|면요|면서|도록|려고|는|은|을|를|이|가|의|에|에서|으로|로|와|과|도|만|한|할|된|될|던|하는|있는)$")
_NEW_SENTENCE_START = re.compile(
    r"^(그래서|그런데|근데|그리고|하지만|그러나|그러니까|그러므로|그러면|그럼|그렇지만|또|또한|자|이제|여러분|아멘|할렐루야|네|예|아니요|제가|저는|우리가|오늘)(\s|$)")
_CONTINUATION_START = re.compile(r"^(을|를|이|가|은|는|에|에서|으로|로|와|과|도|만|의|하는|되는|있는|통하여|통해|때문에|것)(\s|$)")
_PUNCT_END = ".?!。？！…"


def sentence_break(prev_text: str, prev_reason: str, gap: float, next_text: str) -> str | None:
    """앞 조각 뒤가 문장 경계면 붙일 문장부호("." "?" 또는 "" = 부호 없이 줄만 바꿈)를, 아니면 None."""
    prev, nxt = prev_text.strip(), next_text.strip()
    if not prev:
        return None
    if prev[-1] in _PUNCT_END:  # 조작자가 직접 찍은 부호
        return ""
    last = prev.split()[-1]
    score = 0
    question = bool(_QUESTION_END.search(last))
    ending = question or bool(_SENTENCE_END.search(last)) and not last.endswith("면요")
    if ending:
        score += 2
    elif _CONTINUES.search(last):
        score -= 3
    score += {"final": 1, "pause": 1}.get(prev_reason, 0)
    if gap >= 1.5:
        score += 1
    if _NEW_SENTENCE_START.search(nxt):
        score += 1
    elif _CONTINUATION_START.search(nxt):
        score -= 2
    if score < 2:
        return None
    if not ending:
        return ""  # 문장이 끝난 것 같지만 어미가 애매하면 부호 없이 줄만 바꾼다
    return "?" if question else "."


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
    reason: str = ""  # 엔진이 이 조각을 자른 이유 (final | pause | boundary | max)
    newline: bool = False  # 자동 줄바꿈(실험)이 이 조각을 새 줄에서 시작하게 함
    break_after: bool = False  # 조작자가 이 조각 뒤에서 줄을 바꿈 (Shift+Enter)


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

    def add_draft(self, text: str, review: str, countdown: float, reason: str = "",
                  auto_break: bool = False) -> tuple[Chunk | None, bool]:
        """조각을 추가한다. auto_break 면 앞 조각의 문장 경계도 정한다. (새 조각, 이미 나간 앞 조각이 바뀌었는지)"""
        text = " ".join(text.split())
        if not text:
            return None, False
        self._seq += 1
        now = time.time()
        chunk = Chunk(id=self._seq, text=text, created=now, reason=reason,
                      deadline=now + countdown if review == "auto" else None)
        prev_changed = False
        prev = next((c for c in reversed(self.items) if c.status != "discarded"), None)
        if prev is not None and auto_break:
            mark = sentence_break(prev.text, prev.reason, now - prev.created, text)
            if mark is not None:
                chunk.newline = True
                if mark and prev.text[-1] not in _PUNCT_END:
                    prev.text += mark
                    prev_changed = prev.status == "sent"
                    if prev_changed:
                        self._write()
        self.items.append(chunk)
        self._trim()
        return chunk, prev_changed

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

    def toggle_break(self, chunk_id: int, on: bool | None = None) -> bool:
        """조작자 줄바꿈: 이 조각 뒤에서 줄을 바꾼다. 이미 나간 조각이면 자막 화면에 바로 반영된다."""
        chunk = self.find(chunk_id)
        if chunk is None or chunk.status == "discarded":
            return False
        chunk.break_after = (not chunk.break_after) if on is None else on
        if chunk.status == "sent":
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
        return [{"id": c.id, "text": c.text, "newline": c.newline, "break_after": c.break_after} for c in sent[-limit:]]

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
        # 자막 화면과 같은 줄 단위로 쓴다. 줄 첫 조각의 시각을 붙인다.
        lines: list[str] = []
        prev = None
        for c in sent:
            if not lines or c.newline or (prev and (prev.break_after or prev.text[-1:] in _PUNCT_END)):
                lines.append(f"[{datetime.fromtimestamp(c.sent_at or c.created):%H:%M:%S}] {c.text}")
            else:
                lines[-1] += " " + c.text
            prev = c
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def _trim(self) -> None:
        # 오래된 조각은 교정 화면에서만 빠진다. 기록 파일은 이미 쓴 내용을 유지해야 하므로 sent 는 남긴다.
        if len(self.items) > KEEP_ITEMS * 5:
            keep_from = len(self.items) - KEEP_ITEMS * 5
            self.items = [c for i, c in enumerate(self.items) if i >= keep_from or c.status == "sent"]
