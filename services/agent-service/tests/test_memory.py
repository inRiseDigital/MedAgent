"""Tests for long-term conversational memory (P2)."""

from __future__ import annotations

from app.agent.memory import recall, remember, render_memory_block


class _FakeRedis:
    """Minimal async Redis emulating the list ops memory.py uses."""

    def __init__(self) -> None:
        self.d: dict[str, list[str]] = {}

    async def lrem(self, k: str, _count: int, v: str) -> None:
        self.d[k] = [x for x in self.d.get(k, []) if x != v]

    async def rpush(self, k: str, v: str) -> None:
        self.d.setdefault(k, []).append(v)

    async def ltrim(self, k: str, s: int, e: int) -> None:
        lst = self.d.get(k, [])
        n = len(lst)
        si = s if s >= 0 else max(0, n + s)
        ei = e if e >= 0 else n + e
        self.d[k] = lst[si:ei + 1]

    async def expire(self, _k: str, _ttl: int) -> None:
        pass

    async def lrange(self, k: str, s: int, e: int) -> list[str]:
        lst = self.d.get(k, [])
        ei = e if e >= 0 else len(lst) + e
        return lst[s:ei + 1]


async def test_remember_recall_dedup_and_order() -> None:
    r = _FakeRedis()
    assert await remember(r, "p1", "prefers simple explanations") is True
    await remember(r, "p1", "prefers simple explanations")  # dedup → moves to end
    await remember(r, "p1", "asks in Sinhala")
    assert await recall(r, "p1") == ["prefers simple explanations", "asks in Sinhala"]


async def test_remember_caps_history() -> None:
    r = _FakeRedis()
    for i in range(60):
        await remember(r, "p1", f"note {i}")
    notes = await recall(r, "p1")
    assert len(notes) <= 40
    assert notes[-1] == "note 59"  # newest kept


async def test_empty_and_guards() -> None:
    r = _FakeRedis()
    assert await remember(r, "p1", "   ") is False   # blank ignored
    assert await remember(None, "p1", "x") is False  # no redis
    assert await recall(None, "p1") == []
    assert await recall(r, "") == []


def test_render_memory_block() -> None:
    assert render_memory_block([]) == ""
    block = render_memory_block(["prefers simple explanations", "asks in Sinhala"])
    assert "WHAT YOU REMEMBER" in block
    assert "- prefers simple explanations" in block
