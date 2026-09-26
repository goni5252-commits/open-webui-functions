"""
title: Export to Excel
author: Fu-Jie
author_url: https://github.com/Fu-Jie/openwebui-extensions
funding_url: https://github.com/open-webui
version: 0.4.0
required_open_webui_version: 0.11.4
requirements: pandas,xlsxwriter
openwebui_id: 244b8f9d-7459-47d6-84d3-c7ae8e3ec710
icon_url: data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSIyNCIgaGVpZ2h0PSIyNCIgdmlld0JveD0iMCAwIDI0IDI0IiBmaWxsPSJub25lIiBzdHJva2U9ImN1cnJlbnRDb2xvciIgc3Ryb2tlLXdpZHRoPSIyIiBzdHJva2UtbGluZWNhcD0icm91bmQiIHN0cm9rZS1saW5lam9pbj0icm91bmQiPjxwYXRoIGQ9Ik0xNSAySDZhMiAyIDAgMCAwLTIgMnYxNmEyIDIgMCAwIDAgMiAyaDEyYTIgMiAwIDAgMCAyLTJWN1oiLz48cGF0aCBkPSJNMTQgMnY0YTIgMiAwIDAgMCAyIDJoNCIvPjxwYXRoIGQ9Ik04IDEzaDIiLz48cGF0aCBkPSJNMTQgMTNoMiIvPjxwYXRoIGQ9Ik04IDE3aDIiLz48cGF0aCBkPSJNMTQgMTdoMiIvPjwvc3ZnPg==
description: Extracts tables from chat messages and exports them to Excel (.xlsx) files with smart formatting.
"""

import io
import json
import copy
import inspect
import math
import pandas as pd
import re
import base64
from typing import Optional, Callable, Awaitable, Any, List, Dict
import datetime
import asyncio
try:
    from open_webui.models.chats import Chats
    from open_webui.models.chat_messages import ChatMessages
    from open_webui.models.users import Users
    from open_webui.utils.chat import generate_chat_completion
except ImportError:
    Chats = ChatMessages = Users = generate_chat_completion = None
from pydantic import BaseModel, Field
from typing import Literal

# v0.4.0 (based on v0.3.10): lossless table columns, safe cell types,
# isolated in-memory exports, authorized async DB recovery and download acknowledgment.
async def _call_db(method, *args, **kwargs):
    if inspect.iscoroutinefunction(method):
        return await method(*args, **kwargs)
    result = await asyncio.to_thread(method, *args, **kwargs)
    return await result if inspect.isawaitable(result) else result


class Action:
    class Valves(BaseModel):
        TITLE_SOURCE: Literal["chat_title", "ai_generated", "markdown_title"] = Field(
            default="chat_title",
            description="Title Source: 'chat_title' (Chat Title), 'ai_generated' (AI Generated), 'markdown_title' (Markdown Title)",
        )
        SHOW_STATUS: bool = Field(
            default=True,
            description="Whether to show operation status updates.",
        )
        EXPORT_SCOPE: Literal["last_message", "all_messages"] = Field(
            default="last_message",
            description="Export Scope: 'last_message' (Last Message Only), 'all_messages' (All Messages)",
        )
        MODEL_ID: str = Field(
            default="",
            description="Model ID for AI title generation. Leave empty to use the current chat model.",
        )
        SHOW_DEBUG_LOG: bool = Field(
            default=False,
            description="Whether to print debug logs in the browser console.",
        )
        ROW_HEIGHT: int = Field(
            default=0,
            description="Fixed row height in points for data rows. 0 = auto-adjust based on content. Set e.g. 20 for compact single-line rows.",
        )
        COLUMN_WIDTH: int = Field(
            default=0,
            description="Fixed column width in characters for all data columns. 0 = auto-adjust based on content. Set e.g. 15 for uniform compact columns.",
        )

        NUMBER_MODE: Literal["text", "safe_numbers"] = Field(
            default="text", description="기본 text는 식별번호·날짜·수식 문자열을 보존합니다. safe_numbers는 안전한 일반 숫자만 변환합니다."
        )
        MAX_INPUT_CHARS: int = Field(default=2000000, ge=1000, le=10000000)
        MAX_CELLS: int = Field(default=100000, ge=1, le=1000000)
        MAX_SHEETS: int = Field(default=100, ge=1, le=255)
        DOWNLOAD_TIMEOUT_SECONDS: int = Field(default=60, ge=5, le=300)

    def __init__(self):
        self.valves = self.Valves()

    async def _emit_status(
        self,
        emitter: Optional[Callable[[Any], Awaitable[None]]],
        description: str,
        done: bool = False,
    ):
        """Emits a status update event."""
        if self.valves.SHOW_STATUS and emitter:
            await emitter(
                {"type": "status", "data": {"description": description, "done": done}}
            )

    async def _emit_notification(
        self,
        emitter: Optional[Callable[[Any], Awaitable[None]]],
        content: str,
        ntype: str = "info",
    ):
        """Emits a notification event (info, success, warning, error)."""
        if emitter:
            await emitter(
                {"type": "notification", "data": {"type": ntype, "content": content}}
            )

    async def _emit_debug_log(self, emitter, title: str, data: dict):
        """Print structured debug logs in the browser console"""
        if not self.valves.SHOW_DEBUG_LOG or not emitter:
            return
        try:
            import json

            js_code = f"""
                (async function() {{
                    console.group("🛠️ {title}");
                    console.log({json.dumps(data, ensure_ascii=False)});
                    console.groupEnd();
                }})();
            """
            await emitter({"type": "execute", "data": {"code": js_code}})
        except Exception as e:
            print(f"Error emitting debug log: {e}")

    async def action(
        self, body: dict, __user__=None, __event_emitter__=None,
        __event_call__=None, __request__=None, __metadata__=None,
    ):
        worker = Action()
        worker.valves = self.valves.model_copy(deep=True)
        return await worker._export(body, __user__, __event_emitter__, __event_call__, __request__, __metadata__)

    async def _export(self, body, user, emitter, event_call, request, metadata):
        try:
            if not event_call:
                raise ValueError("브라우저 다운로드 연결이 없습니다. 대화 화면에서 다시 실행해 주세요.")
            await self._emit_status(emitter, "엑셀 표를 준비하고 있습니다.")
            messages = [m for m in copy.deepcopy(body.get("messages") or []) if isinstance(m, dict)]
            context = self._get_chat_context(body, metadata)
            # Prefer the clicked message; all_messages means the branch supplied by OWUI.
            if self.valves.EXPORT_SCOPE == "last_message":
                target = next((m for m in messages if m.get("id") == context["message_id"]), None) if context["message_id"] else None
                messages = [target] if target is not None else messages[-1:]
            uid = self._get_user_context(user)["user_id"]
            chat = None
            if context["chat_id"] and uid != "unknown_user" and Chats is not None:
                chat = await _call_db(Chats.get_chat_by_id_and_user_id, id=context["chat_id"], user_id=uid)
            for msg in messages:
                text = self._message_text(msg)
                if not text.strip() and chat and ChatMessages is not None and msg.get("id"):
                    text = await self._fetch_message_output_text(context["chat_id"], str(msg["id"]))
                msg["content"] = text
            if sum(len(m["content"]) for m in messages) > self.valves.MAX_INPUT_CHARS:
                raise ValueError("대화가 너무 큽니다. 내보내기 범위를 줄여 주세요.")
            tables, names = [], []
            for msg in messages:
                found = self.extract_tables_from_message(msg["content"])
                if found:
                    _, proposed = self.generate_names_from_content(msg["content"], found)
                    tables.extend(found)
                    names.extend(proposed)
            if not tables:
                raise ValueError("선택한 범위에 마크다운 표가 없습니다.")
            self._validate_tables(tables)
            names = self._unique_sheet_names(names)
            title = ""
            if self.valves.TITLE_SOURCE == "ai_generated":
                title = await self.generate_title_using_ai(body, messages[0]["content"], uid, request, emitter)
            elif self.valves.TITLE_SOURCE == "markdown_title":
                title = next((self.extract_title(m["content"]) for m in messages if self.extract_title(m["content"])), "")
            if not title and chat:
                title = getattr(chat, "title", "") or (getattr(chat, "chat", None) or {}).get("title", "")
            filename = (self.clean_filename(title) or "표_내보내기_" + datetime.datetime.now().strftime("%Y%m%d_%H%M%S")) + ".xlsx"
            raw = await asyncio.to_thread(self._build_workbook, tables, names)
            if len(raw) > 24 * 1024 * 1024:
                raise ValueError("파일이 너무 큽니다. 내보낼 표의 수를 줄여 주세요.")
            js = """return (() => {
                const payload = __PAYLOAD__;
                const bytes = Uint8Array.from(atob(payload.data), c => c.charCodeAt(0));
                const url = URL.createObjectURL(new Blob([bytes], {type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'}));
                const a = document.createElement('a'); a.href = url; a.download = payload.filename;
                document.body.appendChild(a); a.click();
                setTimeout(() => {a.remove(); URL.revokeObjectURL(url);}, 1000);
                return {ok: true};
            })();""".replace("__PAYLOAD__", json.dumps({"data": base64.b64encode(raw).decode("ascii"), "filename": filename}))
            result = await asyncio.wait_for(event_call({"type": "execute", "data": {"code": js}}), timeout=self.valves.DOWNLOAD_TIMEOUT_SECONDS)
            if not isinstance(result, dict) or result.get("error") or result.get("ok") is not True:
                raise ValueError("다운로드 시작을 확인하지 못했습니다. 브라우저 연결 후 다시 실행해 주세요.")
            await self._emit_status(emitter, f"표 {len(tables)}개의 다운로드를 시작했습니다.", True)
            await self._emit_notification(emitter, f"{filename} 다운로드 시작", "success")
            return None
        except asyncio.TimeoutError:
            message = "브라우저 응답 시간이 초과되었습니다. 연결을 확인한 뒤 다시 실행해 주세요."
        except Exception as exc:
            message = str(exc) if isinstance(exc, ValueError) else "엑셀 생성에 실패했습니다. 표의 크기와 설정을 확인해 주세요."
        await self._emit_status(emitter, message, True)
        await self._emit_notification(emitter, message, "error")
        return {"error": message}

    def _build_workbook(self, tables, names):
        self._validate_tables(tables)
        output = io.BytesIO()
        self.save_tables_to_excel_enhanced(tables, output, self._unique_sheet_names(names))
        return output.getvalue()

    def _validate_tables(self, tables):
        if len(tables) > self.valves.MAX_SHEETS:
            raise ValueError("표가 너무 많습니다. 내보내기 범위를 줄여 주세요.")
        count = 0
        for table in tables:
            rows = table["data"]
            width = max((len(row) for row in rows), default=0)
            if not width or len(rows) > 1048576 or width > 16384:
                raise ValueError("Excel에서 지원하지 않는 행·열 크기입니다.")
            count += width * len(rows)
            if any(len(str(value)) > 32767 for row in rows for value in row):
                raise ValueError("32,767자를 넘는 셀이 있습니다. 내용을 나누어 주세요.")
        if count > self.valves.MAX_CELLS:
            raise ValueError("표의 셀이 너무 많습니다. 내보내기 범위를 줄여 주세요.")

    async def generate_title_using_ai(
        self,
        body: dict,
        content: str,
        user_id: str,
        request: Any,
        event_emitter: Callable = None,
    ) -> str:
        if not request:
            return ""
        try:
            user_obj = await _call_db(Users.get_user_by_id, user_id)
            model = (
                self.valves.MODEL_ID.strip()
                if self.valves.MODEL_ID
                else body.get("model")
            )
            payload = {
                "model": model,
                "messages": [
                    {
                        "role": "system",
                        "content": "You are a helpful assistant. Generate a short, concise filename (max 10 words) for an Excel export based on the following content. Do not use quotes or file extensions. Avoid special characters that are invalid in filenames. Only output the filename.",
                    },
                    {"role": "user", "content": content[:2000]},
                ],
                "stream": False,
            }

            response = await asyncio.wait_for(generate_chat_completion(request, payload, user_obj), timeout=30)
            if isinstance(response, dict) and response.get("choices"):
                title = response["choices"][0]["message"].get("content")
                return title.strip() if isinstance(title, str) else ""
        except Exception as e:
            print(f"Error generating title: {e}")
            if event_emitter:
                await self._emit_notification(
                    event_emitter,
                    f"AI title generation failed, using default title. Error: {str(e)}",
                    "warning",
                )
        return ""

    def extract_title(self, content: str) -> str:
        """Extract title from Markdown h1/h2 only"""
        lines = content.split("\n")
        for line in lines:
            match = re.match(r"^#{1,2}\s+(.+)$", line.strip())
            if match:
                return match.group(1).strip()
        return ""

    def _get_user_context(self, __user__: Optional[Dict[str, Any]]) -> Dict[str, str]:
        """Safely extracts user context information."""
        if isinstance(__user__, (list, tuple)):
            user_data = __user__[0] if __user__ else {}
        elif isinstance(__user__, dict):
            user_data = __user__
        else:
            user_data = {}
        return {
            "user_id": user_data.get("id", "unknown_user"),
            "user_name": user_data.get("name", "User"),
            "user_language": user_data.get("language", "en-US"),
        }

    def _get_chat_context(
        self, body: dict, __metadata__: Optional[dict] = None
    ) -> Dict[str, str]:
        """
        Unified extraction of chat context information (chat_id, message_id).
        Prioritizes extraction from body, then metadata.
        """
        chat_id = ""
        message_id = ""
        if isinstance(body, dict):
            chat_id = body.get("chat_id", "")
            message_id = body.get("id", "")
            if not chat_id or not message_id:
                body_metadata = body.get("metadata", {})
                if isinstance(body_metadata, dict):
                    if not chat_id:
                        chat_id = body_metadata.get("chat_id", "")
                    if not message_id:
                        message_id = body_metadata.get("message_id", "")
        if __metadata__ and isinstance(__metadata__, dict):
            if not chat_id:
                chat_id = __metadata__.get("chat_id", "")
            if not message_id:
                message_id = __metadata__.get("message_id", "")
        return {
            "chat_id": str(chat_id or "").strip(),
            "message_id": str(message_id or "").strip(),
        }

    async def fetch_chat_title(self, chat_id: str, user_id: str = "") -> str:
        """Fetch chat title from database by chat_id"""
        if not chat_id:
            return ""
        try:
            chat = None
            if user_id:
                chat = await _call_db(
                    Chats.get_chat_by_id_and_user_id, id=chat_id, user_id=user_id
                )
        except Exception as exc:
            print(f"Failed to load chat {chat_id}: {exc}")
            return ""
        if not chat:
            return ""
        data = getattr(chat, "chat", {}) or {}
        title = data.get("title") or getattr(chat, "title", "")
        return title.strip() if isinstance(title, str) else ""

    @staticmethod
    def _content_text(content):
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return "\n".join(p["text"] for p in content if isinstance(p, dict)
                             and p.get("type") in ("text", "output_text") and isinstance(p.get("text"), str))
        return ""

    def _extract_text_from_output(self, output):
        if not isinstance(output, list):
            return ""
        return "\n".join(self._content_text(item.get("content")) for item in output
                         if isinstance(item, dict) and item.get("type") == "message"
                         and item.get("role", "assistant") == "assistant")

    def _message_text(self, msg):
        text = self._content_text(msg.get("content"))
        return text if text.strip() else self._extract_text_from_output(msg.get("output"))

    async def _fetch_message_output_text(self, chat_id: str, message_id: str) -> str:
        """Assistant text for a message via OWUI's ChatMessages store: its structured
        ``output`` reconstructed by convert_output_to_messages. "" if not found."""
        if not chat_id or not message_id:
            return ""
        message = await _call_db(
            ChatMessages.get_message_by_id, f"{chat_id}-{message_id}"
        )
        return self._extract_text_from_output(message.output) if message else ""

    @staticmethod
    def _split_table_row(line):
        # Keep empty edge cells, unescape literal pipes, and protect matched code spans.
        text = line.strip()
        cells, current = [], []
        i = 0
        while i < len(text):
            ch = text[i]
            if ch == chr(92) and i + 1 < len(text) and text[i + 1] in ("|", chr(92)):
                current.append(text[i + 1]); i += 2; continue
            if ch == "`":
                end = i
                while end < len(text) and text[end] == "`":
                    end += 1
                marker = text[i:end]
                closing = text.find(marker, end)
                if closing >= 0:
                    current.append(text[i:closing + len(marker)])
                    i = closing + len(marker); continue
            if ch == "|":
                cells.append("".join(current).strip()); current = []
            else:
                current.append(ch)
            i += 1
        cells.append("".join(current).strip())
        if text.startswith("|"):
            cells = cells[1:]
        if text.endswith("|") and not current:
            cells = cells[:-1]
        return cells

    def extract_tables_from_message(self, message):
        lines = message.splitlines()
        tables, fence = [], None
        i = 0
        while i < len(lines):
            marker = re.match(r"^\s{0,3}(`{3,}|~{3,})(.*)$", lines[i])
            if marker:
                run, tail = marker.groups()
                if fence is None:
                    fence = (run[0], len(run))
                elif run[0] == fence[0] and len(run) >= fence[1] and not tail.strip():
                    fence = None
                i += 1; continue
            if fence or lines[i].startswith(("    ", "\t")) or i + 1 >= len(lines):
                i += 1; continue
            header = self._split_table_row(lines[i])
            separator = self._split_table_row(lines[i + 1])
            if ("|" not in lines[i] or len(header) != len(separator) or not separator
                    or not all(re.fullmatch(r":?-{3,}:?", cell) for cell in separator)):
                i += 1; continue
            start = i + 1
            data = [header]
            i += 2
            while i < len(lines) and lines[i].strip() and "|" in lines[i] and not re.match(r"^\s*(`{3,}|~{3,})", lines[i]):
                data.append(self._split_table_row(lines[i]))
                i += 1
            tables.append({"data": data, "start_line": start, "end_line": i})
        return tables

    def generate_names_from_content(self, content: str, tables: List[Dict]) -> tuple:
        """
        Generate workbook name and sheet names based on content
        """
        lines = content.split("\n")
        workbook_name = ""
        sheet_names = []
        all_headers = []
        for i, line in enumerate(lines):
            if re.match(r"^#{1,6}\s+", line):
                all_headers.append(
                    {"text": re.sub(r"^#{1,6}\s+", "", line).strip(), "line_num": i}
                )
        for i, table in enumerate(tables):
            table_start_line = table["start_line"] - 1
            closest_header_text = None
            candidate_headers = [
                h for h in all_headers if h["line_num"] < table_start_line
            ]
            if candidate_headers:
                closest_header = max(candidate_headers, key=lambda x: x["line_num"])
                closest_header_text = closest_header["text"]
            if closest_header_text:
                sheet_names.append(self.clean_sheet_name(closest_header_text))
            else:
                sheet_names.append(f"Sheet{i+1}")
        if len(tables) == 1:
            if sheet_names[0] != "Sheet1":
                workbook_name = sheet_names[0]
        elif len(tables) > 1:
            if all_headers:
                first_header = min(all_headers, key=lambda x: x["line_num"])
                workbook_name = first_header["text"]
        workbook_name = self.clean_filename(workbook_name) if workbook_name else ""
        return workbook_name, sheet_names

    def clean_filename(self, name: str) -> str:
        """Clean illegal characters and clamp length for filesystem safety."""
        if not isinstance(name, str):
            return ""
        cleaned = re.sub(r'[\\/*?:"<>|]', "", name)
        cleaned = re.sub(r"\s+", " ", cleaned).strip().strip(".")
        return cleaned[:50].strip()

    def clean_sheet_name(self, name):
        name = re.sub(r"[\\/*?\[\]:\x00-\x1f]", "", str(name)).strip().strip("'")
        name = name[:31].rstrip("'") or "Sheet"
        return "History_" if name.casefold() == "history" else name

    def _unique_sheet_names(self, names):
        seen, result = set(), []
        for raw in names:
            base = self.clean_sheet_name(raw)
            name, n = base, 1
            while name.casefold() in seen:
                suffix = f" ({n})"
                name = base[:31-len(suffix)].rstrip("'") + suffix
                n += 1
            seen.add(name.casefold())
            result.append(name)
        return result

    def _cell_value(self, value):
        text = str(value)
        if self.valves.NUMBER_MODE == "safe_numbers" and re.fullmatch(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?", text):
            digits = re.sub(r"[^0-9]", "", text)
            if len(digits) <= 15 and not text.startswith("-0"):
                number = float(text) if "." in text else int(text)
                if math.isfinite(number):
                    return number
        return text

    # ======================== Enhanced Formatting ========================
    def calculate_text_width(self, text: str) -> float:
        """
        Calculate text display width, considering CJK characters
        """
        if not text:
            return 0
        width = 0
        for char in str(text):
            if "\u4e00" <= char <= "\u9fff" or "\u3000" <= char <= "\u303f":
                width += 2
            else:
                width += 1
        return width

    def calculate_text_height(self, text: str, max_width: int = 50) -> int:
        """
        Calculate required lines for text display
        """
        if not text:
            return 1
        text = str(text)
        explicit_lines = text.count("\n") + 1
        text_width = self.calculate_text_width(text.replace("\n", ""))
        wrapped_lines = max(
            1, int(text_width / max_width) + (1 if text_width % max_width > 0 else 0)
        )
        return max(explicit_lines, wrapped_lines)

    def get_column_letter(self, col_index: int) -> str:
        """
        Convert column index to Excel column letter
        """
        result = ""
        while col_index >= 0:
            result = chr(65 + col_index % 26) + result
            col_index = col_index // 26 - 1
        return result

    def determine_content_type(self, header: str, values: list) -> str:
        """
        Intelligently determine data type based on header and content
        """
        header_lower = str(header).lower().strip()
        number_keywords = [
            "quantity",
            "amount",
            "price",
            "cost",
            "revenue",
            "expense",
            "total",
            "subtotal",
            "percentage",
            "%",
            "ratio",
            "rate",
            "value",
            "score",
            "points",
        ]
        date_keywords = ["date", "time", "year", "month", "moment"]
        sequence_keywords = [
            "no",
            "no.",
            "id",
            "index",
            "rank",
            "order",
            "sequence",
            "code",
        ]

        for keyword in number_keywords:
            if keyword in header_lower:
                return "number"
        for keyword in date_keywords:
            if keyword in header_lower:
                return "date"
        for keyword in sequence_keywords:
            if keyword in header_lower:
                return "sequence"

        if not values:
            return "text"
        sample_values = [str(v).strip() for v in values[:10] if str(v).strip()]
        if not sample_values:
            return "text"

        numeric_count = 0
        date_count = 0
        sequence_count = 0
        for value in sample_values:
            try:
                float(value.replace(",", "").replace("%", ""))
                numeric_count += 1
                continue
            except ValueError:
                pass

            date_patterns = [
                r"\d{4}[-/]\d{1,2}[-/]\d{1,2}",
                r"\d{1,2}[-/]\d{1,2}[-/]\d{4}",
                r"\d{4}\d{2}\d{2}",
            ]
            for pattern in date_patterns:
                if re.match(pattern, value):
                    date_count += 1
                    break

            if re.match(r"^\d+$", value) and len(value) <= 4:
                sequence_count += 1

        total_count = len(sample_values)
        if numeric_count / total_count >= 0.7:
            return "number"
        elif date_count / total_count >= 0.7:
            return "date"
        elif sequence_count / total_count >= 0.8 and sequence_count > 2:
            return "sequence"
        else:
            return "text"

    def save_tables_to_excel_enhanced(
        self, tables: List[Dict], file_path: str, sheet_names: List[str]
    ):
        """
        Enhanced Excel saving function with standard formatting
        """
        try:
            with pd.ExcelWriter(file_path, engine="xlsxwriter", engine_kwargs={"options": {"strings_to_formulas": False, "strings_to_urls": False}}) as writer:
                workbook = writer.book
                HEADER_BG = "#1f2937"
                HEADER_FG = "#ffffff"
                ROW_ODD_BG = "#ffffff"
                ROW_EVEN_BG = "#f3f4f6"
                BORDER_COLOR = "#e5e7eb"

                header_format = workbook.add_format(
                    {
                        "bold": True,
                        "font_size": 11,
                        "font_name": "Arial",
                        "font_color": HEADER_FG,
                        "bg_color": HEADER_BG,
                        "border": 1,
                        "border_color": BORDER_COLOR,
                        "align": "center",
                        "valign": "vcenter",
                        "text_wrap": True,
                    }
                )
                text_format = workbook.add_format(
                    {
                        "font_name": "Arial",
                        "font_size": 10,
                        "border": 1,
                        "border_color": BORDER_COLOR,
                        "bg_color": ROW_ODD_BG,
                        "align": "left",
                        "valign": "vcenter",
                        "text_wrap": True,
                    }
                )
                text_format_alt = workbook.add_format(
                    {
                        "font_name": "Arial",
                        "font_size": 10,
                        "border": 1,
                        "border_color": BORDER_COLOR,
                        "bg_color": ROW_EVEN_BG,
                        "align": "left",
                        "valign": "vcenter",
                        "text_wrap": True,
                    }
                )
                number_format = workbook.add_format(
                    {
                        "font_name": "Arial",
                        "font_size": 10,
                        "border": 1,
                        "border_color": BORDER_COLOR,
                        "bg_color": ROW_ODD_BG,
                        "align": "right",
                        "valign": "vcenter",
                    }
                )
                number_format_alt = workbook.add_format(
                    {
                        "font_name": "Arial",
                        "font_size": 10,
                        "border": 1,
                        "border_color": BORDER_COLOR,
                        "bg_color": ROW_EVEN_BG,
                        "align": "right",
                        "valign": "vcenter",
                    }
                )
                integer_format = workbook.add_format(
                    {
                        "num_format": "0",
                        "font_name": "Arial",
                        "font_size": 10,
                        "border": 1,
                        "border_color": BORDER_COLOR,
                        "bg_color": ROW_ODD_BG,
                        "align": "right",
                        "valign": "vcenter",
                    }
                )
                integer_format_alt = workbook.add_format(
                    {
                        "num_format": "0",
                        "font_name": "Arial",
                        "font_size": 10,
                        "border": 1,
                        "border_color": BORDER_COLOR,
                        "bg_color": ROW_EVEN_BG,
                        "align": "right",
                        "valign": "vcenter",
                    }
                )
                decimal_format = workbook.add_format(
                    {
                        "num_format": "0.00",
                        "font_name": "Arial",
                        "font_size": 10,
                        "border": 1,
                        "border_color": BORDER_COLOR,
                        "bg_color": ROW_ODD_BG,
                        "align": "right",
                        "valign": "vcenter",
                    }
                )
                decimal_format_alt = workbook.add_format(
                    {
                        "num_format": "0.00",
                        "font_name": "Arial",
                        "font_size": 10,
                        "border": 1,
                        "border_color": BORDER_COLOR,
                        "bg_color": ROW_EVEN_BG,
                        "align": "right",
                        "valign": "vcenter",
                    }
                )
                date_format = workbook.add_format(
                    {
                        "font_name": "Arial",
                        "font_size": 10,
                        "border": 1,
                        "border_color": BORDER_COLOR,
                        "bg_color": ROW_ODD_BG,
                        "align": "center",
                        "valign": "vcenter",
                        "text_wrap": True,
                    }
                )
                date_format_alt = workbook.add_format(
                    {
                        "font_name": "Arial",
                        "font_size": 10,
                        "border": 1,
                        "border_color": BORDER_COLOR,
                        "bg_color": ROW_EVEN_BG,
                        "align": "center",
                        "valign": "vcenter",
                        "text_wrap": True,
                    }
                )
                sequence_format = workbook.add_format(
                    {
                        "font_name": "Arial",
                        "font_size": 10,
                        "border": 1,
                        "border_color": BORDER_COLOR,
                        "bg_color": ROW_ODD_BG,
                        "align": "center",
                        "valign": "vcenter",
                    }
                )
                sequence_format_alt = workbook.add_format(
                    {
                        "font_name": "Arial",
                        "font_size": 10,
                        "border": 1,
                        "border_color": BORDER_COLOR,
                        "bg_color": ROW_EVEN_BG,
                        "align": "center",
                        "valign": "vcenter",
                    }
                )
                text_bold_format = workbook.add_format(
                    {
                        "font_name": "Arial",
                        "font_size": 10,
                        "border": 1,
                        "border_color": BORDER_COLOR,
                        "bg_color": ROW_ODD_BG,
                        "align": "left",
                        "valign": "vcenter",
                        "text_wrap": True,
                        "bold": True,
                    }
                )
                text_bold_format_alt = workbook.add_format(
                    {
                        "font_name": "Arial",
                        "font_size": 10,
                        "border": 1,
                        "border_color": BORDER_COLOR,
                        "bg_color": ROW_EVEN_BG,
                        "align": "left",
                        "valign": "vcenter",
                        "text_wrap": True,
                        "bold": True,
                    }
                )
                text_italic_format = workbook.add_format(
                    {
                        "font_name": "Arial",
                        "font_size": 10,
                        "border": 1,
                        "border_color": BORDER_COLOR,
                        "bg_color": ROW_ODD_BG,
                        "align": "left",
                        "valign": "vcenter",
                        "text_wrap": True,
                        "italic": True,
                    }
                )
                text_italic_format_alt = workbook.add_format(
                    {
                        "font_name": "Arial",
                        "font_size": 10,
                        "border": 1,
                        "border_color": BORDER_COLOR,
                        "bg_color": ROW_EVEN_BG,
                        "align": "left",
                        "valign": "vcenter",
                        "text_wrap": True,
                        "italic": True,
                    }
                )
                CODE_BG = "#f0f0f0"
                text_code_format = workbook.add_format(
                    {
                        "font_name": "Consolas",
                        "font_size": 10,
                        "border": 1,
                        "border_color": BORDER_COLOR,
                        "bg_color": CODE_BG,
                        "align": "left",
                        "valign": "vcenter",
                        "text_wrap": True,
                    }
                )
                text_code_format_alt = workbook.add_format(
                    {
                        "font_name": "Consolas",
                        "font_size": 10,
                        "border": 1,
                        "border_color": BORDER_COLOR,
                        "bg_color": CODE_BG,
                        "align": "left",
                        "valign": "vcenter",
                        "text_wrap": True,
                    }
                )

                for i, table in enumerate(tables):
                    try:
                        table_data = table["data"]
                        if not table_data or len(table_data) < 1:
                            print(f"Skipping empty table at index {i}")
                            continue
                        print(f"Processing table {i+1} with {len(table_data)} rows")
                        sheet_name = (
                            sheet_names[i] if i < len(sheet_names) else f"Sheet{i+1}"
                        )
                        max_cols = max(len(row) for row in table_data)
                        headers = [str(table_data[0][j]).strip() if j < len(table_data[0]) and str(table_data[0][j]).strip()
                                   else f"Col{j+1}" for j in range(max_cols)]
                        # Positional construction preserves duplicate and blank column headers.
                        data_rows = [[self._cell_value(row[j]) if j < len(row) else "" for j in range(max_cols)]
                                     for row in table_data[1:]]
                        df = pd.DataFrame(data_rows, columns=headers, dtype=object)

                        df.to_excel(
                            writer,
                            sheet_name=sheet_name,
                            index=False,
                            header=False,
                            startrow=1,
                        )
                        worksheet = writer.sheets[sheet_name]
                        formats = {
                            "header": header_format,
                            "text": [text_format, text_format_alt],
                            "number": [number_format, number_format_alt],
                            "integer": [integer_format, integer_format_alt],
                            "decimal": [decimal_format, decimal_format_alt],
                            "date": [date_format, date_format_alt],
                            "sequence": [sequence_format, sequence_format_alt],
                            "bold": [text_bold_format, text_bold_format_alt],
                            "italic": [text_italic_format, text_italic_format_alt],
                            "code": [text_code_format, text_code_format_alt],
                        }
                        self.apply_enhanced_formatting(
                            worksheet,
                            df,
                            headers,
                            workbook,
                            formats,
                            row_height=self.valves.ROW_HEIGHT,
                            column_width=self.valves.COLUMN_WIDTH,
                        )
                    except Exception as e:
                        raise ValueError(f"표 {i+1} 생성에 실패했습니다. 일부 표만 저장하지 않고 내보내기를 중단합니다.") from e
        except Exception as e:
            print(f"Error saving Excel file: {str(e)}")
            raise

    def apply_enhanced_formatting(
        self,
        worksheet,
        df,
        headers,
        workbook,
        formats,
        row_height: int = 0,
        column_width: int = 0,
    ):
        """
        Apply enhanced formatting with zebra striping
        """
        try:
            header_format = formats["header"]
            print(f"Writing headers with enhanced alignment: {headers}")
            for col_idx, header in enumerate(headers):
                if header and str(header).strip():
                    worksheet.write(0, col_idx, str(header).strip(), header_format)
                else:
                    default_header = f"Col{col_idx+1}"
                    worksheet.write(0, col_idx, default_header, header_format)

            column_types = {}
            for col_idx, column in enumerate(headers):
                if col_idx < len(df.columns):
                    column_values = df.iloc[:, col_idx].tolist()
                    column_types[col_idx] = self.determine_content_type(
                        column, column_values
                    )
                    print(
                        f"Column '{column}' determined as type: {column_types[col_idx]}"
                    )
                else:
                    column_types[col_idx] = "text"

            for row_idx, row in df.iterrows():
                is_alt_row = row_idx % 2 == 1
                for col_idx, value in enumerate(row):
                    content_type = column_types.get(col_idx, "text")
                    fmt_idx = 1 if is_alt_row else 0

                    if content_type == "number":
                        if pd.api.types.is_numeric_dtype(df.iloc[:, col_idx]):
                            if pd.api.types.is_integer_dtype(df.iloc[:, col_idx]):
                                current_format = formats["integer"][fmt_idx]
                            else:
                                try:
                                    numeric_value = float(value)
                                    if numeric_value.is_integer():
                                        current_format = formats["integer"][fmt_idx]
                                        value = int(numeric_value)
                                    else:
                                        current_format = formats["decimal"][fmt_idx]
                                except (ValueError, TypeError):
                                    current_format = formats["decimal"][fmt_idx]
                        else:
                            current_format = formats["number"][fmt_idx]
                    elif content_type == "date":
                        current_format = formats["date"][fmt_idx]
                    elif content_type == "sequence":
                        current_format = formats["sequence"][fmt_idx]
                    else:
                        current_format = formats["text"][fmt_idx]

                    if content_type == "text" and isinstance(value, str):
                        match_bold = re.fullmatch(r"\*\*(.+)\*\*", value.strip())
                        match_italic = re.fullmatch(r"\*(.+)\*", value.strip())
                        match_code = re.fullmatch(r"`(.+)`", value.strip())
                        if match_bold:
                            clean_value = match_bold.group(1)
                            worksheet.write(
                                row_idx + 1,
                                col_idx,
                                clean_value,
                                formats["bold"][fmt_idx],
                            )
                        elif match_italic:
                            clean_value = match_italic.group(1)
                            worksheet.write(
                                row_idx + 1,
                                col_idx,
                                clean_value,
                                formats["italic"][fmt_idx],
                            )
                        elif match_code:
                            clean_value = match_code.group(1)
                            worksheet.write(
                                row_idx + 1,
                                col_idx,
                                clean_value,
                                formats["code"][fmt_idx],
                            )
                        else:
                            clean_value = re.sub(r"\*\*(.+?)\*\*", r"\1", value)
                            clean_value = re.sub(
                                r"(?<!\*)\*([^*]+)\*(?!\*)", r"\1", clean_value
                            )
                            clean_value = re.sub(r"`(.+?)`", r"\1", clean_value)
                            worksheet.write(
                                row_idx + 1, col_idx, clean_value, current_format
                            )
                    else:
                        worksheet.write(row_idx + 1, col_idx, value, current_format)

            if column_width > 0:
                for col_idx in range(len(headers)):
                    col_letter = self.get_column_letter(col_idx)
                    worksheet.set_column(f"{col_letter}:{col_letter}", column_width)
            else:
                for col_idx, column in enumerate(headers):
                    col_letter = self.get_column_letter(col_idx)
                    header_width = self.calculate_text_width(str(column))
                    max_data_width = 0
                    if not df.empty and col_idx < len(df.columns):
                        for value in df.iloc[:, col_idx]:
                            value_width = self.calculate_text_width(str(value))
                            max_data_width = max(max_data_width, value_width)
                    base_width = max(header_width, max_data_width)
                    content_type = column_types.get(col_idx, "text")
                    if content_type == "sequence":
                        optimal_width = max(8, min(15, base_width + 2))
                    elif content_type == "number":
                        optimal_width = max(12, min(25, base_width + 3))
                    elif content_type == "date":
                        optimal_width = max(15, min(20, base_width + 2))
                    else:
                        if base_width <= 10:
                            optimal_width = base_width + 3
                        elif base_width <= 20:
                            optimal_width = base_width + 4
                        else:
                            optimal_width = base_width + 5
                        optimal_width = max(10, min(60, optimal_width))
                    worksheet.set_column(f"{col_letter}:{col_letter}", optimal_width)

            worksheet.set_row(0, 35)
            if row_height > 0:
                for row_idx in range(len(df)):
                    worksheet.set_row(row_idx + 1, row_height)
            else:
                for row_idx, row in df.iterrows():
                    max_row_height = 20
                    for col_idx, value in enumerate(row):
                        if col_idx < len(headers):
                            col_width = min(
                                60,
                                max(
                                    10,
                                    self.calculate_text_width(str(headers[col_idx]))
                                    + 5,
                                ),
                            )
                        else:
                            col_width = 15
                        cell_lines = self.calculate_text_height(str(value), col_width)
                        cell_height = cell_lines * 20
                        max_row_height = max(max_row_height, cell_height)
                    final_height = min(120, max_row_height)
                    worksheet.set_row(row_idx + 1, final_height)
            print(f"Successfully applied enhanced formatting")
        except Exception as e:
            print(f"Warning: Failed to apply enhanced formatting: {str(e)}")
            self.apply_basic_formatting_fallback(worksheet, df)

    def apply_basic_formatting_fallback(self, worksheet, df):
        """
        Basic formatting fallback
        """
        try:
            for i, column in enumerate(df.columns):
                column_width = (
                    max(
                        len(str(column)),
                        (df[column].astype(str).map(len).max() if not df.empty else 0),
                    )
                    + 2
                )
                col_letter = self.get_column_letter(i)
                worksheet.set_column(
                    f"{col_letter}:{col_letter}", min(60, max(10, column_width))
                )
        except Exception as e:
            print(f"Error in basic formatting: {str(e)}")
