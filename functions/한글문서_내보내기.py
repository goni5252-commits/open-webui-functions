"""
title: HWPX 내보내기 (한글 문서)
author: Claude
author_url: https://github.com/anthropics
funding_url: https://github.com/anthropics
version: 3.4.0
license: MIT
icon_url: data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSIyNCIgaGVpZ2h0PSIyNCIgdmlld0JveD0iMCAwIDI0IDI0IiBmaWxsPSJub25lIiBzdHJva2U9ImN1cnJlbnRDb2xvciIgc3Ryb2tlLXdpZHRoPSIxLjc1IiBzdHJva2UtbGluZWNhcD0icm91bmQiIHN0cm9rZS1saW5lam9pbj0icm91bmQiPgogIDxwYXRoIGQ9Ik0xNCAySDZhMiAyIDAgMCAwLTIgMnYxNmEyIDIgMCAwIDAgMiAyaDEyYTIgMiAwIDAgMCAyLTJWOHoiLz4KICA8cG9seWxpbmUgcG9pbnRzPSIxNCAyIDE0IDggMjAgOCIvPgogIDxjaXJjbGUgY3g9IjEyIiBjeT0iMTIiIHI9IjIiIGZpbGw9Im5vbmUiIHN0cm9rZS13aWR0aD0iMS41Ii8+CiAgPGxpbmUgeDE9IjkiIHkxPSI5IiB4Mj0iMTUiIHkyPSI5IiBzdHJva2Utd2lkdGg9IjEuNSIvPgogIDxsaW5lIHgxPSI5IiB5MT0iMTYuNSIgeDI9IjE1IiB5Mj0iMTYuNSIgc3Ryb2tlLXdpZHRoPSIxLjUiLz4KPC9zdmc+
description: 대화 내용을 한글(HWPX) 문서로 내보내기합니다. 이미지 첨부, 인라인 서식(볼드/이탤릭/코드/링크), LaTeX 수식, 코드블록·인용·목록, 표 포함, Thinking 블록 제거.
required_open_webui_version: 0.11.4
requirements: lxml
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import io
import inspect
import json
import copy
import logging
import os
import re
import struct
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile

from lxml import etree
from pydantic import BaseModel, Field

# Open WebUI imports for file/image retrieval
try:
    from open_webui.models.files import Files  # type: ignore
except Exception:
    Files = None

try:
    from open_webui.models.chats import Chats  # type: ignore
except Exception:
    Chats = None

# Optional interfaces are resolved separately for compatibility and fail-closed access.
try:
    from open_webui.models.chat_messages import ChatMessages
except ImportError:
    ChatMessages = None
try:
    from open_webui.models.users import Users
    from open_webui.utils.access_control.files import has_access_to_file
except ImportError:
    Users = None
    has_access_to_file = None
try:
    from open_webui.storage.provider import Storage
except ImportError:
    Storage = None

async def _call_db(fn, *args, **kwargs):
    if inspect.iscoroutinefunction(fn):
        return await fn(*args, **kwargs)
    value = await asyncio.to_thread(fn, *args, **kwargs)
    return await value if inspect.isawaitable(value) else value

# v3.4.0: async/authorized file access, structured messages, isolated user settings,
# bounded worker rendering and acknowledged browser downloads (based on v3.3.0).
logger = logging.getLogger(__name__)

# ═══ Constants ═══
REPORT_TEMPLATE_B64 = "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"

NS_STR = 'xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph" xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section" xmlns:ha="http://www.hancom.co.kr/hwpml/2011/app" xmlns:hp10="http://www.hancom.co.kr/hwpml/2016/paragraph" xmlns:hc="http://www.hancom.co.kr/hwpml/2011/core" xmlns:hh="http://www.hancom.co.kr/hwpml/2011/head" xmlns:hhs="http://www.hancom.co.kr/hwpml/2011/history" xmlns:hm="http://www.hancom.co.kr/hwpml/2011/master-page" xmlns:hpf="http://www.hancom.co.kr/schema/2011/hpf" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:opf="http://www.idpf.org/2007/opf/" xmlns:ooxmlchart="http://www.hancom.co.kr/hwpml/2016/ooxmlchart" xmlns:hwpunitchar="http://www.hancom.co.kr/hwpml/2016/HwpUnitChar" xmlns:epub="http://www.idpf.org/2007/ops" xmlns:config="urn:oasis:names:tc:opendocument:xmlns:config:1.0"'
A4_W, A4_H, ML, MR, MT, MB = 59528, 84186, 8504, 8504, 5668, 4252
BW = A4_W - ML - MR  # 42520 HWPUNIT = body width

# ═══ CharPr / ParaPr IDs (matching the embedded template header.xml) ═══
C0 = "0"   # 10pt normal
C7 = "7"   # 20pt bold (title)
C8 = "8"   # 14pt bold (heading 2)
C9 = "9"   # 10pt bold (table header / heading 4+)
C11 = "11"  # 9pt normal (small text / code label)
C13 = "13"  # 12pt bold gothic (heading 3 / role header)
C16 = "16"  # 9pt #333 (code text)
C17 = "17"  # 10pt #555 (quote text)
C18 = "18"  # 10pt bold (list bullet)

# New charPr IDs to be added for inline formatting
C_BOLD = "19"      # 10pt bold (inline bold)
C_ITALIC = "20"    # 10pt italic (inline italic)
C_BOLD_ITALIC = "21"  # 10pt bold+italic
C_INLINE_CODE = "22"  # 9pt monospace #333 (inline code)
C_LINK = "23"      # 10pt blue underline (hyperlink)
C_MATH = "24"      # 10pt italic #1a5276 (math expression)

P0 = "0"   # default paragraph
P20 = "20"  # center, 160% lineSpacing
P21 = "21"  # center, 130% (table cell)
P22 = "22"  # justify, 130% (table cell)
P28 = "28"  # code block para
P29 = "29"  # quote para
P30 = "30"  # list level 1
P31 = "31"  # list level 2
P32 = "32"  # horizontal rule para
P33 = "33"  # role header (bold gothic, top spacing)

BF3, BF4 = "3", "4"

# ═══ Regex patterns ═══
_DATA_IMAGE_URL_RE = re.compile(
    r"^data:(?P<mime>image/[a-z0-9.+-]+)\s*;\s*base64\s*,\s*(?P<b64>.*)$",
    re.IGNORECASE | re.DOTALL,
)
_OWUI_API_FILE_ID_RE = re.compile(
    r"/api/v1/files/(?P<id>[A-Za-z0-9-]+)(?:/content)?(?:[/?#]|$)",
    re.IGNORECASE,
)
_THINK_RE = re.compile(r"<think\b[^>]*>.*?</think\s*>", re.IGNORECASE | re.DOTALL)
_DETAILS_RE = re.compile(
    r"<details\b[^>]*>.*?</details\s*>", re.IGNORECASE | re.DOTALL
)
_ANALYSIS_RE = re.compile(
    r"<analysis\b[^>]*>.*?</analysis\s*>", re.IGNORECASE | re.DOTALL
)
_MD_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")


# ═══ Valves ═══
class _BaseValves(BaseModel):
    show_thinking: bool = Field(default=False, description="Thinking 블록 포함 여부")
    include_tables: bool = Field(default=True, description="마크다운 표 → HWPX 표 변환")
    include_images: bool = Field(default=True, description="마크다운 이미지 → HWPX 이미지 삽입")
    MAX_EMBED_IMAGE_MB: int = Field(
        default=20,
        description="이미지 최대 크기 (MB). data URL 및 Open WebUI 내부 파일 적용.",
    )
    MAX_DOCUMENT_CHARS: int = Field(default=1000000, ge=1000, le=5000000)
    MAX_TOTAL_IMAGE_MB: int = Field(default=40, ge=1, le=200)
    DOWNLOAD_TIMEOUT_SECONDS: int = Field(default=60, ge=5, le=300)
    SHOW_STATUS: bool = Field(default=True, description="상태 표시 여부")
    SHOW_DEBUG_LOG: bool = Field(default=False, description="브라우저 콘솔 디버그 로그")
    export_mode: str = Field(
        default="last_assistant",
        description="내보내기 범위: 'last_assistant' (마지막 AI 응답만) 또는 'full_conversation' (전체 대화)",
    )


# ═══ Image Utilities ═══
def _get_image_dimensions(data: bytes) -> Tuple[int, int]:
    """Extract pixel dimensions from PNG/JPEG/GIF/BMP/WEBP bytes. Returns (width, height)."""
    if len(data) < 24:
        return 800, 600  # fallback
    # PNG
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        w, h = struct.unpack(">II", data[16:24])
        return int(w), int(h)
    # JPEG
    if data[:2] == b"\xff\xd8":
        i = 2
        while i < len(data) - 9:
            if data[i] != 0xFF:
                break
            marker = data[i + 1]
            if marker in (0xC0, 0xC1, 0xC2):
                h, w = struct.unpack(">HH", data[i + 5 : i + 9])
                return int(w), int(h)
            seg_len = struct.unpack(">H", data[i + 2 : i + 4])[0]
            i += 2 + seg_len
        return 800, 600
    # GIF
    if data[:6] in (b"GIF87a", b"GIF89a"):
        w, h = struct.unpack("<HH", data[6:10])
        return int(w), int(h)
    return 800, 600


def _image_format_from_bytes(data: bytes) -> str:
    """Detect image format from magic bytes."""
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if data[:2] == b"\xff\xd8":
        return "jpg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    if data[:2] == b"BM":
        return "bmp"
    return "png"  # default


def _image_mime(fmt: str) -> str:
    return {"jpg": "image/jpeg", "gif": "image/gif", "webp": "image/webp", "bmp": "image/bmp"}.get(
        fmt, "image/png"
    )


# ═══ ID Generator ═══
class IDGen:
    def __init__(self):
        self._n = 1000000001

    def next(self):
        v = str(self._n)
        self._n += 1
        return v


# ═══ XML helpers ═══
def _xe(t):
    return (
        t.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


# ═══ Reasoning block removal ═══
def remove_reasoning(text):
    """Remove thinking/details/analysis blocks."""
    text = _THINK_RE.sub("", text)
    text = re.sub(
        r"<details>\s*<summary>\s*Thought[^<]*</summary>.*?</details>",
        "", text, flags=re.DOTALL | re.IGNORECASE,
    )
    text = re.sub(
        r"<details>\s*\n?\s*<summary>[^<]*[Tt]hought[^<]*</summary>[\s\S]*?</details>",
        "", text, flags=re.IGNORECASE,
    )
    text = re.sub(
        r"<details>\s*\n\s*<summary>\s*Thought.*",
        "", text, flags=re.DOTALL | re.IGNORECASE,
    )
    text = _ANALYSIS_RE.sub("", text)
    return text.strip()


# ═══ Inline formatting parser ═══
def parse_inline(text: str) -> List[Tuple[str, str]]:
    """Parse markdown inline formatting into [(text, charPrIDRef), ...] runs.

    Supports: **bold**, *italic*, ***bold+italic***, `code`, [link](url)
    Returns runs using the new charPr IDs for rich formatting.
    """
    if not text or not text.strip():
        return [("", C0)]

    runs: List[Tuple[str, str]] = []
    # Token pattern: bold+italic, bold, italic, inline code, links, images, plain text
    pattern = re.compile(
        r"(\*\*\*(.+?)\*\*\*)"       # bold+italic
        r"|(\*\*(.+?)\*\*)"           # bold
        r"|(__(.+?)__)"               # bold (underscore)
        r"|(\*(.+?)\*)"              # italic
        r"|(_(.+?)_)"                # italic (underscore)
        r"|(`(.+?)`)"                # inline code
        r"|(\[([^\]]+)\]\(([^)]+)\))"  # link [text](url)
        r"|(!\[([^\]]*)\]\(([^)]+)\))"  # image (skip, handled separately)
        r"|(\$([^$]+)\$)"             # inline math $...$
    )

    pos = 0
    for m in pattern.finditer(text):
        # Plain text before this match
        if m.start() > pos:
            runs.append((text[pos:m.start()], C0))

        if m.group(2) is not None:    # ***bold+italic***
            runs.append((m.group(2), C_BOLD_ITALIC))
        elif m.group(4) is not None:  # **bold**
            runs.append((m.group(4), C_BOLD))
        elif m.group(6) is not None:  # __bold__
            runs.append((m.group(6), C_BOLD))
        elif m.group(8) is not None:  # *italic*
            runs.append((m.group(8), C_ITALIC))
        elif m.group(10) is not None: # _italic_
            runs.append((m.group(10), C_ITALIC))
        elif m.group(12) is not None: # `code`
            runs.append((m.group(12), C_INLINE_CODE))
        elif m.group(14) is not None: # [link text](url)
            link_text = m.group(14)
            # link_url = m.group(15) — HWPX doesn't easily support clickable links in raw XML
            runs.append((link_text, C_LINK))
        elif m.group(17) is not None: # ![image](url) — skip, handled as block
            runs.append((f"[{m.group(17) or '이미지'}]", C0))
        elif m.group(20) is not None: # $inline math$
            runs.append((_latex_to_text(m.group(20)), C_MATH))

        pos = m.end()

    # Remaining plain text
    if pos < len(text):
        runs.append((text[pos:], C0))

    # Clean: remove empty runs, merge adjacent same-style runs
    cleaned = []
    for t, cp in runs:
        if not t:
            continue
        if cleaned and cleaned[-1][1] == cp:
            cleaned[-1] = (cleaned[-1][0] + t, cp)
        else:
            cleaned.append((t, cp))

    return cleaned if cleaned else [("", C0)]


def strip_md(text):
    """Strip ALL markdown formatting (legacy, used for table cells etc.)."""
    t = re.sub(r"\*\*\*(.+?)\*\*\*", r"\1", text)
    t = re.sub(r"\*\*(.+?)\*\*", r"\1", t)
    t = re.sub(r"\*(.+?)\*", r"\1", t)
    t = re.sub(r"__(.+?)__", r"\1", t)
    t = re.sub(r"_(.+?)_", r"\1", t)
    t = re.sub(r"`(.+?)`", r"\1", t)
    t = re.sub(r"\[(.+?)\]\(.+?\)", r"\1", t)
    t = re.sub(r"!\[([^\]]*)\]\([^)]+\)", r"\1", t)
    return t


# ═══ Markdown block parser ═══
def parse_md_table(lines):
    if len(lines) < 2:
        return None
    rows = []
    for i, line in enumerate(lines):
        line = line.strip()
        if not line.startswith("|"):
            return None
        if i == 1 and re.match(r"^\|[\s\-:|]+\|$", line):
            continue
        cells = [c.strip() for c in line.split("|")[1:-1]]
        if cells:
            rows.append(cells)
    return rows if rows else None


def split_blocks(text):
    blocks, lines, i = [], text.split("\n"), 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if not stripped:
            blocks.append({"t": "blank"})
            i += 1
            continue
        if re.match(r"^(-{3,}|\*{3,}|_{3,})$", stripped):
            blocks.append({"t": "hr"})
            i += 1
            continue

        # Image line: ![alt](url)
        img_match = re.match(r"^!\[([^\]]*)\]\(([^)]+)\)\s*$", stripped)
        if img_match:
            blocks.append({"t": "image", "alt": img_match.group(1), "url": img_match.group(2)})
            i += 1
            continue

        # LaTeX display math: \[...\] or $$...$$
        if stripped == "\\[" or stripped == "$$":
            delimiter_end = "\\]" if stripped == "\\[" else "$$"
            math_lines = []
            i += 1
            while i < len(lines):
                sl = lines[i].strip()
                if sl == delimiter_end:
                    i += 1
                    break
                math_lines.append(lines[i])
                i += 1
            blocks.append({"t": "math", "text": "\n".join(math_lines)})
            continue

        # Inline $$...$$ on single line
        if stripped.startswith("$$") and stripped.endswith("$$") and len(stripped) > 4:
            blocks.append({"t": "math", "text": stripped[2:-2].strip()})
            i += 1
            continue

        # Code block
        if stripped.startswith("```"):
            lang = stripped[3:].strip()
            cl = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                cl.append(lines[i])
                i += 1
            i += 1
            blocks.append({"t": "code", "text": "\n".join(cl), "lang": lang})
            continue

        # Table
        if stripped.startswith("|"):
            tl = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                tl.append(lines[i])
                i += 1
            rows = parse_md_table(tl)
            blocks.append(
                {"t": "table", "rows": rows}
                if rows
                else {"t": "para", "text": "\n".join(tl)}
            )
            continue

        # Blockquote
        if stripped.startswith(">"):
            ql = []
            while i < len(lines) and lines[i].strip().startswith(">"):
                ql.append(re.sub(r"^>\s?", "", lines[i]))
                i += 1
            blocks.append({"t": "quote", "text": "\n".join(ql)})
            continue

        # Heading
        hm = re.match(r"^(#{1,6})\s+(.+)$", stripped)
        if hm:
            blocks.append({"t": "heading", "text": hm.group(2).strip(), "lv": len(hm.group(1))})
            i += 1
            continue

        # List
        lm = re.match(r"^(\s*)([-*+]|\d+[.)]) (.+)$", stripped)
        if lm:
            items = []
            while i < len(lines):
                s = lines[i].strip()
                m = re.match(r"^(\s*)([-*+]|\d+[.)]) (.+)$", s)
                if m:
                    indent = len(lines[i]) - len(lines[i].lstrip())
                    level = 1 if indent < 4 else 2
                    items.append({"level": level, "bullet": m.group(2), "text": m.group(3)})
                    i += 1
                elif s and not s.startswith("#") and not s.startswith("```") and not s.startswith("|") and not s.startswith(">"):
                    if items:
                        items[-1]["text"] += " " + s
                    i += 1
                else:
                    break
            blocks.append({"t": "list", "items": items})
            continue

        # Paragraph (with inline image detection)
        pl = []
        while i < len(lines):
            l = lines[i].strip()
            if (
                not l
                or l.startswith("|")
                or l.startswith("```")
                or l.startswith(">")
                or re.match(r"^#{1,6}\s+", l)
                or re.match(r"^(\s*)([-*+]|\d+[.)]) ", l)
                or re.match(r"^(-{3,}|\*{3,}|_{3,})$", l)
                or re.match(r"^!\[([^\]]*)\]\(([^)]+)\)\s*$", l)
            ):
                break
            pl.append(lines[i])
            i += 1
        blocks.append({"t": "para", "text": "\n".join(pl)})
    return blocks


def get_msg_text(msg):
    def parts_text(content):
        if isinstance(content, str):
            return content
        if not isinstance(content, list):
            return ""
        parts = []
        for part in content:
            if isinstance(part, str):
                parts.append(part)
            elif isinstance(part, dict):
                if part.get("type") in ("text", "output_text"):
                    text = part.get("text", "")
                    if isinstance(text, str):
                        parts.append(text)
                elif part.get("type") in ("image_url", "input_image"):
                    url = part.get("image_url", "")
                    url = url.get("url", "") if isinstance(url, dict) else url
                    if isinstance(url, str) and url:
                        parts.append(f"![이미지]({url})")
        return "\n".join(parts)
    text = parts_text(msg.get("content"))
    if text.strip():
        return text
    return "\n".join(
        parts_text(item.get("content"))
        for item in (msg.get("output") or [])
        if isinstance(item, dict) and item.get("type") == "message"
        and item.get("role", "assistant") == "assistant"
    )


# ═══ XML Builders ═══
def mk_secpr(g):
    pid = g.next()
    return f"""  <hp:p id="{pid}" paraPrIDRef="0" styleIDRef="0" pageBreak="0" columnBreak="0" merged="0">
    <hp:run charPrIDRef="0">
      <hp:secPr id="" textDirection="HORIZONTAL" spaceColumns="1134" tabStop="8000" tabStopVal="4000" tabStopUnit="HWPUNIT" outlineShapeIDRef="1" memoShapeIDRef="0" textVerticalWidthHead="0" masterPageCnt="0">
        <hp:grid lineGrid="0" charGrid="0" wonggojiFormat="0"/><hp:startNum pageStartsOn="BOTH" page="0" pic="0" tbl="0" equation="0"/><hp:visibility hideFirstHeader="0" hideFirstFooter="0" hideFirstMasterPage="0" border="SHOW_ALL" fill="SHOW_ALL" hideFirstPageNum="0" hideFirstEmptyLine="0" showLineNumber="0"/><hp:lineNumberShape restartType="0" countBy="0" distance="0" startNumber="0"/>
        <hp:pagePr landscape="WIDELY" width="{A4_W}" height="{A4_H}" gutterType="LEFT_ONLY"><hp:margin header="4252" footer="4252" gutter="0" left="{ML}" right="{MR}" top="{MT}" bottom="{MB}"/></hp:pagePr>
        <hp:footNotePr><hp:autoNumFormat type="DIGIT" userChar="" prefixChar="" suffixChar=")" supscript="0"/><hp:noteLine length="-1" type="SOLID" width="0.12 mm" color="#000000"/><hp:noteSpacing betweenNotes="283" belowLine="567" aboveLine="850"/><hp:numbering type="CONTINUOUS" newNum="1"/><hp:placement place="EACH_COLUMN" beneathText="0"/></hp:footNotePr>
        <hp:endNotePr><hp:autoNumFormat type="DIGIT" userChar="" prefixChar="" suffixChar=")" supscript="0"/><hp:noteLine length="14692344" type="SOLID" width="0.12 mm" color="#000000"/><hp:noteSpacing betweenNotes="0" belowLine="567" aboveLine="850"/><hp:numbering type="CONTINUOUS" newNum="1"/><hp:placement place="END_OF_DOCUMENT" beneathText="0"/></hp:endNotePr>
        <hp:pageBorderFill type="BOTH" borderFillIDRef="1" textBorder="PAPER" headerInside="0" footerInside="0" fillArea="PAPER"><hp:offset left="1417" right="1417" top="1417" bottom="1417"/></hp:pageBorderFill>
        <hp:pageBorderFill type="EVEN" borderFillIDRef="1" textBorder="PAPER" headerInside="0" footerInside="0" fillArea="PAPER"><hp:offset left="1417" right="1417" top="1417" bottom="1417"/></hp:pageBorderFill>
        <hp:pageBorderFill type="ODD" borderFillIDRef="1" textBorder="PAPER" headerInside="0" footerInside="0" fillArea="PAPER"><hp:offset left="1417" right="1417" top="1417" bottom="1417"/></hp:pageBorderFill>
      </hp:secPr>
      <hp:ctrl><hp:colPr id="" type="NEWSPAPER" layout="LEFT" colCount="1" sameSz="1" sameGap="0"/></hp:ctrl>
    </hp:run>
    <hp:run charPrIDRef="0"><hp:t/></hp:run>
  </hp:p>"""


def mk_p(g, text, cp=C0, pp=P0):
    return f'  <hp:p id="{g.next()}" paraPrIDRef="{pp}" styleIDRef="0" pageBreak="0" columnBreak="0" merged="0"><hp:run charPrIDRef="{cp}"><hp:t>{_xe(text)}</hp:t></hp:run></hp:p>'


def mk_mr(g, runs, pp=P0):
    """Multi-run paragraph with mixed charPr styles."""
    pid = g.next()
    rx = "".join(
        f'<hp:run charPrIDRef="{cp}"><hp:t>{_xe(t)}</hp:t></hp:run>'
        for t, cp in runs
        if t
    )
    if not rx:
        rx = f'<hp:run charPrIDRef="{C0}"><hp:t/></hp:run>'
    return f'  <hp:p id="{pid}" paraPrIDRef="{pp}" styleIDRef="0" pageBreak="0" columnBreak="0" merged="0">{rx}</hp:p>'


def mk_blank(g):
    return f'  <hp:p id="{g.next()}" paraPrIDRef="0" styleIDRef="0" pageBreak="0" columnBreak="0" merged="0"><hp:run charPrIDRef="0"><hp:t/></hp:run></hp:p>'


def mk_pic(g, bin_id: str, pw: int, ph: int) -> str:
    """Create an inline picture paragraph matching 한글's native hp:pic structure.
    bin_id: image reference ID (matches content.hpf opf:item id)
    pw, ph: pixel dimensions of the image.
    """
    if pw <= 0:
        pw = 800
    if ph <= 0:
        ph = 600

    # Scale to fit body width
    img_w = BW
    img_h = int(BW * ph / pw)
    if img_h <= 0:
        img_h = BW

    pid = g.next()
    pic_id = g.next()
    inst_id = g.next()

    return f"""  <hp:p id="{pid}" paraPrIDRef="0" styleIDRef="0" pageBreak="0" columnBreak="0" merged="0">
    <hp:run charPrIDRef="0">
      <hp:pic id="{pic_id}" zOrder="0" numberingType="PICTURE" textWrap="TOP_AND_BOTTOM" textFlow="BOTH_SIDES" lock="0" dropcapstyle="None" groupLevel="0" instid="{inst_id}" reverse="0">
        <hp:offset x="0" y="0"/>
        <hp:orgSz width="{img_w}" height="{img_h}"/>
        <hp:curSz width="0" height="0"/>
        <hp:flip horizontal="0" vertical="0"/>
        <hp:rotationInfo angle="0" centerX="{img_w // 2}" centerY="{img_h // 2}" rotateimage="1"/>
        <hp:renderingInfo><hc:transMatrix e1="1" e2="0" e3="0" e4="0" e5="1" e6="0"/><hc:scaMatrix e1="1" e2="0" e3="0" e4="0" e5="1" e6="0"/><hc:rotMatrix e1="1" e2="0" e3="0" e4="0" e5="1" e6="0"/></hp:renderingInfo>
        <hc:img binaryItemIDRef="{bin_id}" bright="0" contrast="0" effect="REAL_PIC" alpha="0"/>
        <hp:imgRect><hc:pt0 x="0" y="0"/><hc:pt1 x="{img_w}" y="0"/><hc:pt2 x="{img_w}" y="{img_h}"/><hc:pt3 x="0" y="{img_h}"/></hp:imgRect>
        <hp:imgClip left="0" right="0" top="0" bottom="0"/>
        <hp:inMargin left="0" right="0" top="0" bottom="0"/>
        <hp:imgDim dimwidth="{pw}" dimheight="{ph}"/>
        <hp:effects/>
        <hp:sz width="{img_w}" widthRelTo="ABSOLUTE" height="{img_h}" heightRelTo="ABSOLUTE" protect="0"/>
        <hp:pos treatAsChar="1" affectLSpacing="0" flowWithText="1" allowOverlap="0" holdAnchorAndSO="0" vertRelTo="PARA" horzRelTo="COLUMN" vertAlign="TOP" horzAlign="LEFT" vertOffset="0" horzOffset="0"/>
        <hp:outMargin left="0" right="0" top="0" bottom="0"/>
        <hp:shapeComment>image</hp:shapeComment>
      </hp:pic>
    </hp:run>
  </hp:p>"""


def mk_table(g, rows):
    if not rows:
        return ""
    nr, nc = len(rows), max(len(r) for r in rows)
    cw = BW // nc
    cws = [cw] * nc
    cws[-1] += BW - cw * nc
    rh = 2800
    tid = g.next()
    pid = g.next()
    p = [
        f'  <hp:p id="{pid}" paraPrIDRef="0" styleIDRef="0" pageBreak="0" columnBreak="0" merged="0"><hp:run charPrIDRef="0">'
    ]
    p.append(
        f'    <hp:tbl id="{tid}" zOrder="0" numberingType="TABLE" textWrap="TOP_AND_BOTTOM" textFlow="BOTH_SIDES" lock="0" dropcapstyle="None" pageBreak="CELL" repeatHeader="0" rowCnt="{nr}" colCnt="{nc}" cellSpacing="0" borderFillIDRef="{BF3}" noAdjust="0"><hp:sz width="{BW}" widthRelTo="ABSOLUTE" height="{rh*nr}" heightRelTo="ABSOLUTE" protect="0"/><hp:pos treatAsChar="1" affectLSpacing="0" flowWithText="1" allowOverlap="0" holdAnchorAndSO="0" vertRelTo="PARA" horzRelTo="COLUMN" vertAlign="TOP" horzAlign="LEFT" vertOffset="0" horzOffset="0"/><hp:outMargin left="0" right="0" top="0" bottom="0"/><hp:inMargin left="0" right="0" top="0" bottom="0"/>'
    )
    for ri, row in enumerate(rows):
        hdr = ri == 0
        bf = BF4 if hdr else BF3
        cr = C9 if hdr else C0
        pr = P21 if hdr else P22
        p.append("      <hp:tr>")
        for ci in range(nc):
            ct = strip_md(row[ci]) if ci < len(row) else ""
            cid = g.next()
            p.append(
                f'        <hp:tc name="" header="{1 if hdr else 0}" hasMargin="0" protect="0" editable="0" dirty="1" borderFillIDRef="{bf}"><hp:subList id="" textDirection="HORIZONTAL" lineWrap="BREAK" vertAlign="CENTER" linkListIDRef="0" linkListNextIDRef="0" textWidth="0" textHeight="0" hasTextRef="0" hasNumRef="0"><hp:p paraPrIDRef="{pr}" styleIDRef="0" pageBreak="0" columnBreak="0" merged="0" id="{cid}"><hp:run charPrIDRef="{cr}"><hp:t>{_xe(ct)}</hp:t></hp:run></hp:p></hp:subList><hp:cellAddr colAddr="{ci}" rowAddr="{ri}"/><hp:cellSpan colSpan="1" rowSpan="1"/><hp:cellSz width="{cws[ci]}" height="{rh}"/><hp:cellMargin left="510" right="510" top="142" bottom="142"/></hp:tc>'
            )
        p.append("      </hp:tr>")
    p.append("    </hp:tbl></hp:run></hp:p>")
    return "\n".join(p)


# ═══ HWPX Builder ═══
def _add_charpr_to_header(header_xml_bytes: bytes) -> bytes:
    """Inject additional charPr entries for inline formatting into the template header."""
    root = etree.fromstring(header_xml_bytes)
    ns_hh = "http://www.hancom.co.kr/hwpml/2011/head"
    cp_el = root.find(f".//{{{ns_hh}}}charProperties")
    if cp_el is None:
        return header_xml_bytes

    existing_ids = {c.get("id") for c in cp_el}

    # Base attributes for new charPr entries
    # fontRef indices: 0=함초롬돋움(gothic), 1=함초롬바탕(serif/body default)
    # Structure must EXACTLY match existing charPr elements (charPr 0/9 as reference)
    def _make_charpr(cid, height, bold, italic, underline_color=None, text_color="#000000", font_id="1"):
        if cid in existing_ids:
            return  # already exists
        el = etree.SubElement(cp_el, f"{{{ns_hh}}}charPr")
        el.set("id", cid)
        el.set("height", str(height))
        el.set("textColor", text_color)
        el.set("shadeColor", "none")
        el.set("useFontSpace", "0")
        el.set("useKerning", "0")
        el.set("symMark", "NONE")
        el.set("borderFillIDRef", "2")  # Must match existing (was "0", now "2")

        fr = etree.SubElement(el, f"{{{ns_hh}}}fontRef")
        for fk in ("hangul", "latin", "hanja", "japanese", "other", "symbol", "user"):
            fr.set(fk, font_id)

        for tag in ("ratio", "spacing", "relSz", "offset"):
            sub = etree.SubElement(el, f"{{{ns_hh}}}{tag}")
            vals = {"hangul": "100", "latin": "100", "hanja": "100", "japanese": "100", "other": "100", "symbol": "100", "user": "100"} if tag in ("ratio", "relSz") else {"hangul": "0", "latin": "0", "hanja": "0", "japanese": "0", "other": "0", "symbol": "0", "user": "0"}
            for k, v in vals.items():
                sub.set(k, v)

        if bold:
            etree.SubElement(el, f"{{{ns_hh}}}bold")
        if italic:
            etree.SubElement(el, f"{{{ns_hh}}}italic")

        # underline — always present, matching existing structure
        ul = etree.SubElement(el, f"{{{ns_hh}}}underline")
        if underline_color:
            ul.set("type", "BOTTOM")
            ul.set("shape", "SOLID")
            ul.set("color", underline_color)
        else:
            ul.set("type", "NONE")
            ul.set("shape", "SOLID")
            ul.set("color", "#000000")

        # strikeout — must use "shape" not "type" (matching existing)
        st = etree.SubElement(el, f"{{{ns_hh}}}strikeout")
        st.set("shape", "NONE")
        st.set("color", "#000000")

        # outline
        ol = etree.SubElement(el, f"{{{ns_hh}}}outline")
        ol.set("type", "NONE")

        # shadow — with full attributes matching existing
        sh = etree.SubElement(el, f"{{{ns_hh}}}shadow")
        sh.set("type", "NONE")
        sh.set("color", "#C0C0C0")
        sh.set("offsetX", "10")
        sh.set("offsetY", "10")

        # Do NOT add emboss, engrave, supscript — existing charPr doesn't have them

    # font_id="1" = 함초롬바탕 (matches body charPr 0), "0" = 함초롬돋움 (code/gothic)
    _make_charpr(C_BOLD, 1000, bold=True, italic=False, font_id="1")
    _make_charpr(C_ITALIC, 1000, bold=False, italic=True, font_id="1")
    _make_charpr(C_BOLD_ITALIC, 1000, bold=True, italic=True, font_id="1")
    _make_charpr(C_INLINE_CODE, 900, bold=False, italic=False, text_color="#333333", font_id="0")
    _make_charpr(C_LINK, 1000, bold=False, italic=False, underline_color="#2E74B5", text_color="#2E74B5", font_id="1")
    _make_charpr(C_MATH, 1100, bold=False, italic=True, text_color="#1A5276", font_id="1")

    # Update itemCnt
    cp_el.set("itemCnt", str(len(cp_el)))

    return etree.tostring(root, xml_declaration=True, encoding="UTF-8")


def _add_bindata_to_header(header_bytes: bytes, bin_items: List[Tuple[str, str]]) -> bytes:
    """Add binDataStorage entries to header.xml for images.
    bin_items: [(bin_id, storage_path), ...] e.g. [("BIN0001", "BinData/image1.png")]
    """
    if not bin_items:
        return header_bytes
    root = etree.fromstring(header_bytes)
    ns_hh = "http://www.hancom.co.kr/hwpml/2011/head"

    # Find or create <hh:binDataStorages>
    head_el = root  # root is <hh:head>
    bds = head_el.find(f"{{{ns_hh}}}binDataStorages")
    if bds is None:
        # Insert before the first child that is not beginPr/mappingTable/etc.
        bds = etree.SubElement(head_el, f"{{{ns_hh}}}binDataStorages")

    for bin_id, storage_path in bin_items:
        item = etree.SubElement(bds, f"{{{ns_hh}}}binDataItem")
        item.set("id", bin_id)
        ext = storage_path.rsplit(".", 1)[-1].upper() if "." in storage_path else "PNG"
        item.set("format", ext)
        item.set("compressPolicy", "STORE")
        item.set("storageId", storage_path)

    bds.set("itemCnt", str(len(bds)))
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8")


def build_hwpx(paragraphs, title, images=None):
    """Build HWPX file bytes.
    images: list of (bin_id, storage_path, image_bytes) tuples
    """
    if images is None:
        images = []

    tpl = base64.b64decode(REPORT_TEMPLATE_B64)
    sx = (
        f"<?xml version='1.0' encoding='UTF-8'?>\n<hs:sec {NS_STR}>\n"
        + "\n".join(paragraphs)
        + "\n</hs:sec>"
    )
    # Validate section XML
    etree.fromstring(sx.encode("utf-8"))

    with tempfile.TemporaryDirectory() as td:
        w = Path(td) / "b"
        w.mkdir()
        with ZipFile(io.BytesIO(tpl)) as z:
            z.extractall(w)

        # Write section
        (w / "Contents" / "section0.xml").write_text(sx, encoding="utf-8")

        # Modify header.xml: add inline charPr styles only (NO binDataStorages)
        header_path = w / "Contents" / "header.xml"
        header_bytes = header_path.read_bytes()
        header_bytes = _add_charpr_to_header(header_bytes)
        header_path.write_bytes(header_bytes)

        # Write image files to BinData/
        if images:
            bindata_dir = w / "BinData"
            bindata_dir.mkdir(exist_ok=True)
            for _, spath, img_bytes in images:
                fname = spath.replace("BinData/", "")
                (bindata_dir / fname).write_bytes(img_bytes)

        # Update content.hpf
        hpf = w / "Contents" / "content.hpf"
        if hpf.is_file():
            t = etree.parse(str(hpf))
            ns = {"opf": "http://www.idpf.org/2007/opf/"}
            el = t.getroot().find(".//opf:title", ns)
            if el is not None:
                el.text = title
            now = datetime.now(timezone.utc)
            for m in t.getroot().findall(".//opf:meta", ns):
                n = m.get("name", "")
                if n == "creator":
                    m.text = "Open WebUI"
                elif n == "lastsaveby":
                    m.text = "Open WebUI"
                elif n in ("CreatedDate", "ModifiedDate"):
                    m.text = now.strftime("%Y-%m-%dT%H:%M:%SZ")

            # Add image items to manifest (한글 style: id=bin_id, isEmbeded="1")
            if images:
                manifest_el = t.getroot().find(".//opf:manifest", ns)
                if manifest_el is not None:
                    for bid, spath, _ in images:
                        item_el = etree.SubElement(manifest_el, f"{{{ns['opf']}}}item")
                        item_el.set("id", bid)
                        item_el.set("href", spath)
                        fmt = spath.rsplit(".", 1)[-1].lower()
                        item_el.set("media-type", _image_mime(fmt))
                        item_el.set("isEmbeded", "1")

            t.write(str(hpf), pretty_print=True, xml_declaration=True, encoding="UTF-8")

        # DO NOT modify manifest.xml (한글 keeps it empty)

        # Package — BinData uses ZIP_STORED
        o = Path(td) / "o.hwpx"
        af = sorted(p.relative_to(w).as_posix() for p in w.rglob("*") if p.is_file())
        with ZipFile(o, "w", ZIP_DEFLATED) as z:
            z.write(w / "mimetype", "mimetype", compress_type=ZIP_STORED)
            for r in af:
                if r != "mimetype":
                    ct = ZIP_STORED if r.startswith("BinData/") else ZIP_DEFLATED
                    z.write(w / r, r, compress_type=ct)
        return o.read_bytes()


def _latex_to_text(latex: str) -> str:
    """Convert LaTeX math to readable plain text for HWPX display.
    Since HWPX doesn't natively support MathML/OMML, we render a readable approximation.
    """
    t = latex.strip()
    # Common replacements
    replacements = [
        (r"\\frac\{([^}]*)\}\{([^}]*)\}", r"(\1)/(\2)"),
        (r"\\sqrt\{([^}]*)\}", r"√(\1)"),
        (r"\\boxed\{([^}]*)\}", r"[\1]"),
        (r"\\text\{([^}]*)\}", r"\1"),
        (r"\\mathrm\{([^}]*)\}", r"\1"),
        (r"\\mathbf\{([^}]*)\}", r"\1"),
        (r"\\left\s*", ""),
        (r"\\right\s*", ""),
        (r"\\cdot", "·"),
        (r"\\times", "×"),
        (r"\\div", "÷"),
        (r"\\pm", "±"),
        (r"\\mp", "∓"),
        (r"\\leq", "≤"),
        (r"\\geq", "≥"),
        (r"\\neq", "≠"),
        (r"\\approx", "≈"),
        (r"\\infty", "∞"),
        (r"\\alpha", "α"),
        (r"\\beta", "β"),
        (r"\\gamma", "γ"),
        (r"\\delta", "δ"),
        (r"\\epsilon", "ε"),
        (r"\\theta", "θ"),
        (r"\\lambda", "λ"),
        (r"\\mu", "μ"),
        (r"\\pi", "π"),
        (r"\\sigma", "σ"),
        (r"\\omega", "ω"),
        (r"\\Delta", "Δ"),
        (r"\\Sigma", "Σ"),
        (r"\\Omega", "Ω"),
        (r"\\sum", "Σ"),
        (r"\\prod", "Π"),
        (r"\\int", "∫"),
        (r"\\partial", "∂"),
        (r"\\nabla", "∇"),
        (r"\\rightarrow", "→"),
        (r"\\leftarrow", "←"),
        (r"\\Rightarrow", "⇒"),
        (r"\\quad", "  "),
        (r"\\qquad", "    "),
        (r"\\,", " "),
        (r"\\;", " "),
        (r"\\ ", " "),
        (r"\\\\", "\n"),
        (r"\^{([^}]*)}", r"^\1"),
        (r"_{([^}]*)}", r"_\1"),
    ]
    for pat, repl in replacements:
        t = re.sub(pat, repl, t)
    # Remove remaining backslash commands
    t = re.sub(r"\\[a-zA-Z]+", "", t)
    # Clean up braces
    t = t.replace("{", "").replace("}", "")
    # Clean whitespace
    t = re.sub(r"  +", " ", t).strip()
    return t


# ═══ Block Renderer ═══
def render_blocks(g, blocks, valves, image_collector):
    """Render blocks to HWPX XML paragraphs.
    image_collector: ImageCollector instance for tracking embedded images.
    """
    pa = []
    for b in blocks:
        bt = b["t"]
        if bt == "blank":
            pa.append(mk_blank(g))
        elif bt == "hr":
            pa.append(mk_p(g, "", C0, P32))
        elif bt == "heading":
            lv = b.get("lv", 1)
            # Use inline formatting for headings
            runs = parse_inline(b["text"])
            # Override charPr for heading level style
            heading_cp = {1: C7, 2: C8, 3: C13}.get(lv, C9)
            # For headings, use single-style run (heading style overrides inline)
            heading_pp = P20 if lv == 1 else P0
            pa.append(mk_p(g, strip_md(b["text"]), heading_cp, heading_pp))
        elif bt == "image":
            img_data = image_collector.resolve_image(b["url"])
            if img_data is not None:
                bin_id, pw, ph = img_data
                pa.append(mk_pic(g, bin_id, pw, ph))
            else:
                alt = b.get("alt", "이미지")
                pa.append(mk_p(g, f"[{alt}: 이미지를 불러올 수 없음]", C11, P0))
        elif bt == "math":
            # Render LaTeX as readable text with math styling
            math_text = _latex_to_text(b["text"])
            for mline in math_text.split("\n"):
                mline = mline.strip()
                if mline:
                    pa.append(mk_p(g, f"  {mline}", C_MATH, P28))
        elif bt == "table" and valves.include_tables:
            pa.append(mk_table(g, b["rows"]))
        elif bt == "code":
            if b.get("lang"):
                pa.append(mk_p(g, f"  [{b['lang']}]", C11, P28))
            for cl in b["text"].split("\n"):
                pa.append(mk_p(g, f"  {cl}", C16, P28))
            pa.append(mk_blank(g))
        elif bt == "quote":
            for ql in b["text"].split("\n"):
                ql_clean = strip_md(ql.strip())
                pa.append(mk_p(g, ql_clean if ql_clean else "", C17, P29))
        elif bt == "list":
            for item in b["items"]:
                pp = P30 if item["level"] == 1 else P31
                runs = [(f"{item['bullet']} ", C18)] + parse_inline(item["text"])
                pa.append(mk_mr(g, runs, pp))
        elif bt == "para":
            for ln in b["text"].split("\n"):
                ln = ln.strip()
                if ln:
                    runs = parse_inline(ln)
                    pa.append(mk_mr(g, runs, P0))
        elif bt == "table":
            for row in b["rows"]:
                pa.append(mk_p(g, " | ".join(row), C0, P0))
    return pa


# ═══ Image Collection ═══
class ImageCollector:
    """Collects images during rendering, resolves URLs to binary data."""

    def __init__(self, valves):
        self.valves = valves
        self._file_bytes = {}
        self.skipped = 0
        self._total_bytes = 0
        self._images: List[Tuple[str, str, bytes]] = []  # (bin_id, storage_path, bytes)
        self._counter = 0

    @property
    def images(self):
        return self._images

    def _max_bytes(self) -> int:
        try:
            mb = int(self.valves.MAX_EMBED_IMAGE_MB)
        except Exception:
            mb = 20
        return max(1, mb) * 1024 * 1024

    def resolve_image(self, url: str) -> Optional[Tuple[str, int, int]]:
        """Try to resolve image URL to binary data. Returns (bin_id, pixel_w, pixel_h) or None."""
        if not self.valves.include_images:
            return None
        u = (url or "").strip()
        if not u:
            return None

        max_bytes = self._max_bytes()
        img_bytes = None

        # 1. data: URL
        if u.lower().startswith("data:"):
            img_bytes = self._from_data_url(u, max_bytes)
        else:
            # 2. Open WebUI internal file
            file_id = self._extract_owui_file_id(u)
            if file_id:
                img_bytes = self._from_owui_file(file_id, max_bytes)
            # else: external URL — skip (same as docx behavior)

        if img_bytes is None:
            self.skipped += 1
            return None
        if not (img_bytes.startswith((b"\x89PNG\r\n\x1a\n", b"\xff\xd8", b"GIF87a", b"GIF89a", b"BM"))
                or (img_bytes[:4] == b"RIFF" and img_bytes[8:12] == b"WEBP")):
            self.skipped += 1
            return None
        if self._total_bytes + len(img_bytes) > self.valves.MAX_TOTAL_IMAGE_MB * 1024 * 1024:
            self.skipped += 1
            return None
        self._total_bytes += len(img_bytes)
        self._counter += 1
        fmt = _image_format_from_bytes(img_bytes)
        bin_id = f"image{self._counter}"
        storage_path = f"BinData/image{self._counter}.{fmt}"
        pw, ph = _get_image_dimensions(img_bytes)

        self._images.append((bin_id, storage_path, img_bytes))
        return (bin_id, pw, ph)

    def _from_data_url(self, url: str, max_bytes: int) -> Optional[bytes]:
        m = _DATA_IMAGE_URL_RE.match(url.strip())
        if not m:
            return None
        b64 = (m.group("b64") or "").strip()
        b64 = re.sub(r"\s+", "", b64)
        if not b64:
            return None
        est = (len(b64) * 3) // 4
        if est > max_bytes:
            return None
        pad = (-len(b64)) % 4
        if pad:
            b64 += "=" * pad
        try:
            out = base64.b64decode(b64, validate=False)
        except (binascii.Error, ValueError):
            return None
        return out if len(out) <= max_bytes else None

    def _extract_owui_file_id(self, url: str) -> Optional[str]:
        m = _OWUI_API_FILE_ID_RE.search(url)
        return (m.group("id") or "").strip() if m else None

    def _from_owui_file(self, file_id, max_bytes):
        return self._file_bytes.get(file_id)

    async def prepare(self, messages, user_id):
        """Fetch only authorized referenced files before entering the rendering worker."""
        if not self.valves.include_images or not user_id or Files is None:
            return
        ids = dict.fromkeys(m.group("id") for msg in messages
                            for m in _OWUI_API_FILE_ID_RE.finditer(get_msg_text(msg)))
        total = 0
        for file_id in ids:
            if total >= self.valves.MAX_TOTAL_IMAGE_MB * 1024 * 1024:
                break
            try:
                obj = await _call_db(Files.get_file_by_id, file_id)
                if obj is None:
                    continue
                allowed = getattr(obj, "user_id", None) == user_id
                if not allowed and Users is not None and has_access_to_file is not None:
                    user = await _call_db(Users.get_user_by_id, user_id)
                    allowed = bool(user) and await _call_db(has_access_to_file, file_id, "read", user)
                if not allowed:
                    continue
                raw = await asyncio.to_thread(self._read_authorized_file, obj)
                if raw and total + len(raw) <= self.valves.MAX_TOTAL_IMAGE_MB * 1024 * 1024:
                    self._file_bytes[file_id] = raw
                    total += len(raw)
            except Exception:
                logger.warning("An image could not be loaded for HWPX export")

    def _read_authorized_file(self, obj):
        limit = self._max_bytes()
        data = getattr(obj, "data", None)
        if isinstance(data, dict):
            raw = data.get("bytes")
            if isinstance(raw, (bytes, bytearray)):
                return bytes(raw) if len(raw) <= limit else None
            for key in ("b64", "base64", "data"):
                value = data.get(key)
                if isinstance(value, str) and value:
                    return self._from_data_url("data:image/png;base64," + value, limit)
        path = getattr(obj, "path", None)
        if not isinstance(path, str) or not path:
            return None
        # Never follow arbitrary HTTP URLs or forward the request's bearer token.
        if path.startswith(("http://", "https://")):
            return None
        if Storage is not None:
            path = Storage.get_file(path)
        elif "://" in path:
            return None
        with open(path, "rb") as stream:
            raw = stream.read(limit + 1)
        return raw if len(raw) <= limit else None


def _remove_emojis(text: str) -> str:
    if not isinstance(text, str):
        return ""

    def _is_emoji(cp: int) -> bool:
        return (
            0x1F000 <= cp <= 0x1FAFF
            or 0x1F1E6 <= cp <= 0x1F1FF
            or 0x2600 <= cp <= 0x26FF
            or 0x2700 <= cp <= 0x27BF
            or 0x2300 <= cp <= 0x23FF
            or 0x2B00 <= cp <= 0x2BFF
        )

    def _is_modifier(cp: int) -> bool:
        return (
            cp in (0x200D, 0xFE0E, 0xFE0F, 0x20E3)
            or 0x1F3FB <= cp <= 0x1F3FF
            or 0xE0020 <= cp <= 0xE007F
        )

    return "".join(ch for ch in text if not (_is_emoji(ord(ch)) or _is_modifier(ord(ch))))


# ═══ Build from messages ═══
def build_from_messages(messages, title, valves, image_collector, mode="full_conversation"):
    g = IDGen()
    pa = [mk_secpr(g), mk_blank(g)]
    pa.append(mk_p(g, title, C7, P20))
    pa.append(mk_blank(g))
    pa.append(mk_p(g, f"내보내기 일시: {datetime.now().strftime('%Y년 %m월 %d일 %H:%M')}", C11, P20))
    pa.append(mk_blank(g))
    pa.append(mk_p(g, "", C0, P32))
    pa.append(mk_blank(g))

    if mode == "last_assistant":
        # Export only the last assistant message
        target_msgs = []
        for msg in reversed(messages):
            if msg.get("role") == "assistant":
                target_msgs = [msg]
                break
    else:
        target_msgs = messages

    for msg in target_msgs:
        role = msg.get("role", "unknown")
        text = get_msg_text(msg)
        if not text:
            continue
        if role == "assistant" and not valves.show_thinking:
            text = remove_reasoning(text)
            if not text:
                continue

        if mode == "full_conversation":
            label = {
                "user": "사용자 (User)",
                "assistant": "AI 어시스턴트 (Assistant)",
                "system": "시스템 (System)",
            }.get(role, role)
            pa.append(mk_p(g, f"  {label}", C13, P33))
            pa.append(mk_blank(g))

        pa.extend(render_blocks(g, split_blocks(text), valves, image_collector))
        pa.append(mk_blank(g))

    return build_hwpx(pa, title, images=image_collector.images)


# ═══ Open WebUI Action ═══
class Action:
    class Valves(_BaseValves):
        pass

    class UserValves(BaseModel):
        show_thinking: Optional[bool] = Field(default=None, description="Thinking 블록 포함 여부")
        include_tables: Optional[bool] = Field(default=None, description="마크다운 표 → HWPX 표 변환")
        include_images: Optional[bool] = Field(default=None, description="이미지 삽입 여부")
        export_mode: Optional[str] = Field(
            default=None,
            description="내보내기 범위: 'last_assistant' 또는 'full_conversation'",
        )

    def __init__(self):
        self.valves = self.Valves()

    def _get_user_context(self, __user__) -> Dict[str, str]:
        if isinstance(__user__, (list, tuple)):
            user_data = __user__[0] if __user__ else {}
        elif isinstance(__user__, dict):
            user_data = __user__
        else:
            user_data = {}
        return {
            "user_id": user_data.get("id", "unknown_user"),
            "user_name": user_data.get("name", "User"),
        }

    async def _emit_status(self, emitter, desc: str, done: bool = False):
        if self.valves.SHOW_STATUS and emitter:
            await emitter({"type": "status", "data": {"description": desc, "done": done}})

    async def _emit_notification(self, emitter, content: str, ntype: str = "info"):
        if emitter:
            await emitter({"type": "notification", "data": {"type": ntype, "content": content}})

    async def _emit_debug_log(self, emitter, title: str, data: dict):
        if not self.valves.SHOW_DEBUG_LOG or not emitter:
            return
        try:
            import json
            js_code = f'(function(){{console.group("🛠️ {title}");console.log({json.dumps(data, ensure_ascii=False)});console.groupEnd();}})();'
            await emitter({"type": "execute", "data": {"code": js_code}})
        except Exception:
            pass

    async def action(
        self, body: dict, __user__=None, __event_emitter__=None,
        __event_call__=None, __metadata__=None, __request__=None,
    ) -> Optional[dict]:
        # A request-local instance prevents UserValves leaking into another export.
        worker = Action()
        worker.valves = self.valves.model_copy(deep=True)
        user = __user__ if isinstance(__user__, dict) else {}
        raw = user.get("valves", {})
        if isinstance(raw, BaseModel):
            raw = raw.model_dump(exclude_unset=True)
        overrides = self.UserValves(**raw) if isinstance(raw, dict) else self.UserValves()
        for key, value in overrides.model_dump(exclude_none=True).items():
            setattr(worker.valves, key, value)
        return await worker._export(body, user, __event_emitter__, __event_call__, __metadata__)

    async def _export(self, body, user, emitter, event_call, metadata):
        try:
            if not event_call:
                raise ValueError("브라우저 다운로드 연결이 없습니다. 대화 화면에서 다시 실행해 주세요.")
            if self.valves.export_mode not in ("last_assistant", "full_conversation"):
                raise ValueError("지원하지 않는 내보내기 범위입니다.")
            await self._emit_status(emitter, "HWPX 문서 준비 중...")
            messages = copy.deepcopy(body.get("messages") or [])
            messages = [m for m in messages if isinstance(m, dict)]
            if self.valves.export_mode == "last_assistant":
                messages = next(([m] for m in reversed(messages) if m.get("role") == "assistant"), [])
            cid = body.get("chat_id") or (metadata or {}).get("chat_id") or (body.get("metadata") or {}).get("chat_id")
            uid = user.get("id")
            chat = None
            if cid and uid and Chats is not None:
                chat = await _call_db(Chats.get_chat_by_id_and_user_id, id=cid, user_id=uid)
            # Never fall back to an unrestricted chat lookup.
            if chat and ChatMessages is not None:
                for msg in messages:
                    if not get_msg_text(msg).strip() and msg.get("id"):
                        stored = await _call_db(ChatMessages.get_message_by_id, f"{cid}-{msg['id']}")
                        if stored:
                            msg["output"] = getattr(stored, "output", None)
            messages = [dict(m, content=get_msg_text(m)) for m in messages]
            if not any(m["content"].strip() for m in messages):
                raise ValueError("내보낼 답변 내용이 없습니다.")
            if sum(len(m["content"]) for m in messages) > self.valves.MAX_DOCUMENT_CHARS:
                raise ValueError("문서가 너무 큽니다. 내보내기 범위를 줄여 주세요.")
            title = getattr(chat, "title", "") if chat else ""
            if not title and chat:
                title = (getattr(chat, "chat", None) or {}).get("title", "")
            title = title or body.get("title") or body.get("chat_title") or "대화 내보내기"
            title = str(title)[:200]
            collector = ImageCollector(self.valves)
            await collector.prepare(messages, uid)
            hwpx = await asyncio.to_thread(
                build_from_messages, messages, title, self.valves, collector, self.valves.export_mode
            )
            if len(hwpx) > 48 * 1024 * 1024:
                raise ValueError("다운로드 파일이 너무 큽니다. 이미지 또는 내보내기 범위를 줄여 주세요.")
            safe = re.sub(r'[\\/*?:"<>|\x00-\x1f]', "_", _remove_emojis(title)[:30]) or "대화"
            filename = f"{safe}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.hwpx"
            encoded = base64.b64encode(hwpx).decode("ascii")
            js = """return (() => {
                const bytes = Uint8Array.from(atob(ENCODED), c => c.charCodeAt(0));
                const url = URL.createObjectURL(new Blob([bytes], {type: 'application/hwp+zip'}));
                const a = document.createElement('a');
                a.href = url; a.download = FILENAME; document.body.appendChild(a);
                a.click();
                setTimeout(() => {a.remove(); URL.revokeObjectURL(url);}, 1000);
                return {ok: true};
            })()""".replace("ENCODED", json.dumps(encoded)).replace("FILENAME", json.dumps(filename))
            result = await asyncio.wait_for(
                event_call({"type": "execute", "data": {"code": js}}),
                timeout=self.valves.DOWNLOAD_TIMEOUT_SECONDS,
            )
            if not isinstance(result, dict) or result.get("error") or result.get("ok") is not True:
                raise ValueError("브라우저가 다운로드 시작을 확인하지 못했습니다. 연결 후 다시 실행해 주세요.")
            if collector.skipped:
                await self._emit_notification(emitter, f"권한·형식·크기 또는 경로 문제로 이미지 {collector.skipped}개를 제외했습니다.", "warning")
            await self._emit_status(emitter, "HWPX 다운로드를 시작했습니다.", True)
            await self._emit_notification(emitter, f"{filename} 다운로드 시작", "success")
            return None
        except asyncio.TimeoutError:
            message = "브라우저 응답 시간이 초과되었습니다. 연결을 확인한 뒤 다시 실행해 주세요."
        except Exception as exc:
            logger.exception("HWPX export failed")
            message = str(exc) if isinstance(exc, ValueError) else "문서 생성에 실패했습니다. 서버 로그를 확인해 주세요."
        await self._emit_status(emitter, message, True)
        await self._emit_notification(emitter, message, "error")
        return {"error": message}
