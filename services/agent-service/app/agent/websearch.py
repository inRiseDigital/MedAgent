"""Keyless web search (P4) via DuckDuckGo HTML.

Gives the agent access to general medical knowledge, clinical guidelines and drug
information that is NOT in the patient's FHIR record. Best-effort: returns [] on
any failure. Results are LABELLED [web: …] downstream and must never be presented
as the patient's own data or cited with the record's [source: …] form.
"""

from __future__ import annotations

import html as _html
import re
import urllib.parse

import httpx

_ANCHOR = re.compile(r'<a[^>]*class="result__a"[^>]*>(.*?)</a>', re.S)
_HREF = re.compile(r'href="([^"]+)"')
_SNIPPET = re.compile(r'class="result__snippet"[^>]*>(.*?)</a>', re.S)
_UA = "Mozilla/5.0 (compatible; MedAgent/1.0; +https://medagent.health.lk)"


def _clean(s: str) -> str:
    return _html.unescape(re.sub(r"<.*?>", "", s)).strip()


def _real_url(href: str) -> str:
    """DDG wraps result links in a /l/?uddg= redirect — unwrap to the target."""
    m = re.search(r"[?&]uddg=([^&]+)", href)
    url = urllib.parse.unquote(m.group(1)) if m else href
    return url if url.startswith("http") else f"https:{url}" if url.startswith("//") else url


async def web_search(query: str, k: int = 4) -> list[dict[str, str]]:
    """Return up to `k` web results ({title,url,snippet}) for `query`, best-effort."""
    q = (query or "").strip()
    if not q:
        return []
    try:
        async with httpx.AsyncClient(timeout=12.0, headers={"User-Agent": _UA}, follow_redirects=True) as c:
            resp = await c.post("https://html.duckduckgo.com/html/", data={"q": q})
            resp.raise_for_status()
            page = resp.text
    except Exception:  # noqa: BLE001 — search is best-effort, never breaks a turn
        return []
    snippets = [_clean(s) for s in _SNIPPET.findall(page)]
    out: list[dict[str, str]] = []
    for i, m in enumerate(_ANCHOR.finditer(page)):
        if len(out) >= k:
            break
        anchor = m.group(0)
        title = _clean(m.group(1))
        href_m = _HREF.search(anchor)
        if not title or not href_m:
            continue
        out.append({
            "title": title,
            "url": _real_url(href_m.group(1)),
            "snippet": snippets[i] if i < len(snippets) else "",
        })
    return out
