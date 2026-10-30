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
    kind: str = "stt"  # stt: 음성 인식 · manual: 조작자가 직접 입력 · suggest: 강사 원어의 기계 번역 제안
    source: str = ""  # suggest: 번역한 원어 (조작자 확인용)
    # dual 모드: side = "translate"(영어 STT+번역) | "interpret"(한글 STT) | ""(일반)
    # pair_id: 같은 문장의 두 버전(번역·통역)을 짝짓는다
    side: str = ""
    pair_id: int | None = None
    # Chrome 이 이 조각의 말을 나중에 고쳐 확정한 글. 이미 나갔거나 조작자가 고친 조각에만 남기고, 조작자가 반영하거나 무시한다.
    revision: str = ""


@dataclass
class LiveSession:
    transcript_dir: Path
    items: list[Chunk] = field(default_factory=list)
    _seq: int = 0
    _file: Path | None = None
    started: datetime | None = None
    paused: bool = False  # 전체 일시정지: 자동 내보내기 카운트다운을 모두 멈춘다 (조작자가 틀린 것을 고치는 동안)
    # dual 모드: 차례(pair_id)마다 조작자가 고른 쪽 ("translate" | "interpret"). 고르기 전에는 아무것도 저절로 나가지 않는다.
    pair_choice: dict[int, str] = field(default_factory=dict)

    def start(self) -> None:
        self.paused = False
        self.pair_choice.clear()
        self.items.clear()
        self.started = datetime.now()
        self._file = None

    # ───────── 조각 ─────────

    def add_draft(self, text: str, review: str, countdown: float, reason: str = "",
                  auto_break: bool = False, side: str = "", pair_id: int | None = None
                  ) -> tuple[Chunk | None, bool]:
        """조각을 추가한다. auto_break 면 앞 조각의 문장 경계도 정한다. (새 조각, 이미 나간 앞 조각이 바뀌었는지)
        side/pair_id 는 dual 모드(영어 STT+번역 vs 한글 STT)에서 두 버전을 짝짓는 데 쓴다."""
        text = " ".join(text.split())
        if not text:
            return None, False
        self._seq += 1
        now = time.time()
        chunk = Chunk(id=self._seq, text=text, created=now, reason=reason,
                      deadline=now + countdown if review == "auto" else None,
                      side=side, pair_id=pair_id)
        if pair_id is not None and side:
            # dual: 아직 고르지 않은 차례는 조작자가 골라야 나간다. 이미 고른 차례면 고른 쪽만 받고 다른 쪽은 버린다.
            choice = self.pair_choice.get(pair_id)
            if choice is None:
                chunk.deadline = None
            elif choice != side:
                chunk.status, chunk.deadline = "discarded", None
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

    def _insert(self, chunk: Chunk, after_id: int | None = None, before_time: float | None = None) -> None:
        """조각을 목록의 알맞은 자리에 넣는다. 자막 화면·기록 파일은 목록 순서를 따른다."""
        index = len(self.items)
        if after_id is not None:
            index = next((i + 1 for i, c in enumerate(self.items) if c.id == after_id), index)
        elif before_time is not None:
            index = next((i for i, c in enumerate(self.items) if c.created > before_time), index)
        self.items.insert(index, chunk)

    def add_manual(self, text: str, after_id: int | None = None, send: bool = True) -> Chunk | None:
        """조작자가 직접 쓴 조각 (빠진 통역 보완). 기본은 바로 내보낸다."""
        text = " ".join(text.split())
        if not text:
            return None
        self._seq += 1
        chunk = Chunk(id=self._seq, text=text, created=time.time(), kind="manual")
        self._insert(chunk, after_id=after_id)
        if send:
            self.send(chunk.id)
        return chunk

    def add_suggestion(self, text: str, source: str, after_id: int | None = None) -> Chunk:
        """빠진 통역 자리에 넣는 기계 번역 제안 (조작자가 강사 원어 줄을 골라서 만든다).
        자동 내보내기 대상이 아니다 — 조작자가 확인해야 나간다."""
        self._seq += 1
        chunk = Chunk(id=self._seq, text=" ".join(text.split()), created=time.time(), kind="suggest", source=source.strip())
        self._insert(chunk, after_id=after_id)
        return chunk

    def revise(self, chunk_id: int, text: str) -> None:
        """Chrome 이 이미 내보낸 조각의 말을 고쳐 확정했다. 아직 대기 중이고 조작자가 손대지 않았으면 그대로 바꾸고,
        나갔거나 조작자가 고친 조각이면 "인식이 바뀜"으로만 남긴다 (자막 화면은 조작자가 반영할 때 바뀐다)."""
        chunk = self.find(chunk_id)
        text = " ".join(text.split())
        if chunk is None or chunk.status == "discarded" or not text or text == chunk.text:
            return
        if chunk.status == "pending" and not chunk.edited and not chunk.editing:
            chunk.text, chunk.revision = text, ""
        else:
            chunk.revision = text

    def dismiss_revision(self, chunk_id: int) -> bool:
        chunk = self.find(chunk_id)
        if chunk is None:
            return False
        chunk.revision = ""
        return True

    def find(self, chunk_id: int) -> Chunk | None:
        return next((c for c in self.items if c.id == chunk_id), None)

    def send(self, chunk_id: int, text: str | None = None) -> bool:
        """내보내기. 이미 내보낸 조각에 text 를 주면 수정으로 처리한다."""
        chunk = self.find(chunk_id)
        if chunk is None or chunk.status == "discarded":
            return False
        if text is None and not chunk.text:
            return False  # 번역 제안이 비어 있으면 조작자가 써 넣어야 한다
        if text is not None:
            text = " ".join(text.split())
            if not text:
                return self.discard(chunk_id)
            if text != chunk.text:
                chunk.text, chunk.edited = text, True
            if text == chunk.revision:
                chunk.revision = ""
        if chunk.status == "pending" and self._unchosen(chunk):
            # dual: 한 줄을 내보내면 그 차례는 그 쪽으로 고른 것이다 (다른 쪽은 버린다)
            return self.choose(chunk.pair_id, chunk.side) > 0
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
        if text and text == chunk.revision:
            chunk.revision = ""
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
            # 번역 제안과 아직 고르지 않은 dual 차례는 늘 조작자가 확인
            if c.status == "pending" and c.kind != "suggest" and not self._unchosen(c):
                c.deadline = now + countdown if review == "auto" else None

    # ───────── dual 모드: 차례마다 한쪽 고르기 ─────────

    def _unchosen(self, c: Chunk) -> bool:
        return c.pair_id is not None and bool(c.side) and c.pair_id not in self.pair_choice

    def choose(self, pair_id: int, side: str) -> int:
        """이 차례(pair_id)에서 고른 쪽의 대기 조각을 내보내고 다른 쪽은 버린다. 나중에 오는 다른 쪽 조각도 버린다.
        내보낸 개수를 돌려준다."""
        if side not in ("translate", "interpret"):
            return 0
        # send() 는 고르지 않은 차례의 조각이면 choose() 를 부르므로, 내보내기 전에 먼저 고른 것으로 적어야 한다
        self.pair_choice[pair_id] = side
        count = 0
        for c in self.items:
            if c.pair_id != pair_id or c.status != "pending" or not c.side:
                continue
            if c.side == side:
                count += self.send(c.id)
            else:
                self.discard(c.id)
        return count

    def _choose_default(self, upto: int | None = None) -> int:
        """여기까지·모두 내보내기에서 아직 고르지 않은 차례는 번역 쪽(없으면 통역)으로 고른다. 내보낸 개수를 돌려준다."""
        pending = [c for c in self.items[:upto] if c.status == "pending" and self._unchosen(c)]
        count = 0
        for pair_id in dict.fromkeys(c.pair_id for c in pending):
            sides = {c.side for c in self.items if c.pair_id == pair_id and c.status == "pending"}
            count += self.choose(pair_id, "translate" if "translate" in sides else "interpret")
        return count

    def set_paused(self, paused: bool, countdown: float) -> None:
        """멈추면 아무것도 저절로 나가지 않는다. 다시 흐르게 하면 대기 조각들이 카운트다운을 새로 시작한다
        (멈춘 동안 기한이 지난 조각들이 한꺼번에 나가지 않게)."""
        if self.paused == paused:
            return
        self.paused = paused
        if not paused:
            now = time.time()
            for c in self.items:
                if c.status == "pending" and c.deadline is not None:
                    c.deadline = now + countdown

    def due(self) -> list[Chunk]:
        if self.paused:
            return []
        now = time.time()
        return [c for c in self.items
                if c.status == "pending" and not c.editing and c.deadline is not None and c.deadline <= now]

    def send_upto(self, chunk_id: int, text: str | None = None) -> int:
        """이 조각과 그 위(목록 앞쪽)의 대기 조각을 모두 내보낸다 — 밀렸을 때 훑어보고 한 번에 처리.
        번역 제안은 하나씩 확인해야 하므로 빼되, 조작자가 고른 그 조각이면 내보낸다. 내보낸 개수를 돌려준다."""
        index = next((i for i, c in enumerate(self.items) if c.id == chunk_id), None)
        if index is None:
            return 0
        count = 0
        target = self.items[index]
        if self._unchosen(target):  # dual: 조작자가 고른 그 줄의 쪽으로 이 차례를 고른다
            if text is not None:
                self.update_text(target.id, text, 0)
            count += self.choose(target.pair_id, target.side)
        count += self._choose_default(index)
        for c in self.items[:index]:
            if c.status == "pending" and c.kind != "suggest" and self.send(c.id):
                count += 1
        if target.status == "pending" and self.send(target.id, text):
            count += 1
        return count

    def send_all_pending(self) -> int:
        chosen = self._choose_default()  # dual: 고르지 않은 차례는 번역 쪽으로
        # 번역 제안은 조작자가 하나씩 확인해야 하므로 "모두 내보내기"에서 뺀다
        pending = [c for c in self.items if c.status == "pending" and c.kind != "suggest"]
        for c in pending:
            self.send(c.id)
        return chosen + len(pending)

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
