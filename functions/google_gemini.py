"""
title: Google Gemini Pipeline
author: owndev and olivier-lacroix. editied by goni5252
author_url: https://github.com/owndev/
project_url: https://github.com/owndev/Open-WebUI-Functions
funding_url: https://github.com/sponsors/owndev
version: 1.23.6
required_open_webui_version: 0.9.0
license: Apache License 2.0
description: Google Gemini pipeline with Gemini 3.7 support, local Auto Thinking routing, automatic Google Search grounding, Nano Banana 2 image routing/editing, OCR, RAG bypass, and robust tool handling.
features:
  - Optimized asynchronous API calls for maximum performance
  - Intelligent model caching with configurable TTL
  - Streamlined dynamic model specification with automatic prefix handling
  - Smart streaming response handling with safety checks
  - Advanced multimodal input support (text and images)
  - Unified image generation and editing with Gemini 2.5 Flash Image Preview
  - Intelligent image optimization with size-aware compression algorithms
  - Automated image upload to Open WebUI with robust fallback support
  - Optimized text-to-image and image-to-image workflows
  - Non-streaming mode for image generation to prevent chunk overflow
  - Progressive status updates for optimal user experience
  - Consolidated error handling and comprehensive logging
  - Seamless Google Generative AI and Vertex AI integration
  - Model-aware generation parameters with Gemini 3.6+ sampling cleanup
  - Configurable safety settings with environment variable support
  - Military-grade encrypted storage of sensitive API keys
  - Intelligent grounding with Google search integration
  - Automatic Google Search grounding with Gemini-controlled search decisions
  - Native tool-call safe mode: disables streaming when Open WebUI native tools are active
  - Empty-stream guard to prevent silent blank assistant messages
  - Vertex AI Search grounding for RAG
  - Bypass backend RAG: send attached documents natively to Gemini instead of Open WebUI's RAG context (inspired by Gemini Manifold google_genai)
  - Korean HWPX document support: direct ZIP/XML text extraction + embedded-image extraction
  - Native tool calling support with automatic signature management
  - URL context grounding for specified web pages
  - Unified image processing with consolidated helper methods
  - Optimized payload creation for image generation models
  - Configurable image processing parameters (size, quality, compression)
  - Flexible upload fallback options and optimization controls
  - Configurable thinking levels for Gemini 3 models, including modern Flash levels
  - Local Auto Thinking Router: selects low/medium/high by request complexity without an extra API call
  - Auto Thinking respects explicit per-chat reasoning_effort and excludes OCR/image/video/background tasks
  - Configurable thinking budgets (0-32768 tokens) for Gemini 2.5 models
  - Configurable image generation aspect ratio (1:1, 16:9, etc.) and resolution (1K, 2K, 4K)
  - Model whitelist for filtering available models
  - Additional model support for SDK-unsupported models, with Gemini 3.7 Flash fallback
  - Video generation with Google Veo models (Veo 3.1, 3, 2)
  - Configurable video generation parameters (aspect ratio, resolution, duration)
  - Asynchronous video generation with progressive polling status updates
  - Automatic video upload to Open WebUI with chat file attachments
  - Image-to-video generation support for Veo models
  - Negative prompt and person generation controls for video
"""

import os
import copy
import inspect
import json
from collections.abc import Mapping
import contextlib
from contextvars import ContextVar
import re
import time
import asyncio
import base64
import hashlib
import logging
import io
import uuid
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
import aiofiles
from PIL import Image
from google import genai
from google.genai import types
from google.genai.errors import ClientError, ServerError, APIError
from typing import List, Union, Optional, Dict, Any, Tuple, AsyncIterator, Callable
from pydantic_core import core_schema
from pydantic import BaseModel, Field, GetCoreSchemaHandler
from cryptography.fernet import Fernet, InvalidToken
from open_webui.env import SRC_LOG_LEVELS
from open_webui.internal.db import get_async_db_context
from fastapi import Request, UploadFile, BackgroundTasks
from open_webui.routers.files import upload_file
from open_webui.models.chats import Chats
from open_webui.models.users import UserModel, Users
from starlette.datastructures import Headers

ASPECT_RATIO_OPTIONS: List[str] = [
    "default",
    "1:1",
    "2:3",
    "3:2",
    "3:4",
    "4:3",
    "4:5",
    "5:4",
    "9:16",
    "16:9",
    "21:9",
]

RESOLUTION_OPTIONS: List[str] = [
    "default",
    "1K",
    "2K",
    "4K",
]

VIDEO_ASPECT_RATIO_OPTIONS: List[str] = [
    "default",
    "16:9",
    "9:16",
]

VIDEO_RESOLUTION_OPTIONS: List[str] = [
    "default",
    "720p",
    "1080p",
    "4k",
]

VIDEO_DURATION_OPTIONS: List[str] = [
    "default",
    "4",
    "5",
    "6",
    "8",
]

VIDEO_PERSON_GENERATION_OPTIONS: List[str] = [
    "default",
    "allow_all",
    "allow_adult",
    "dont_allow",
]


# Simplified encryption implementation with automatic handling
class EncryptedStr(str):
    """A string type that automatically handles encryption/decryption"""

    @classmethod
    def _get_encryption_key(cls) -> Optional[bytes]:
        """
        Generate encryption key from WEBUI_SECRET_KEY if available
        Returns None if no key is configured
        """
        secret = os.getenv("WEBUI_SECRET_KEY")
        if not secret:
            return None

        hashed_key = hashlib.sha256(secret.encode()).digest()
        return base64.urlsafe_b64encode(hashed_key)

    @classmethod
    def encrypt(cls, value: str) -> str:
        """
        Encrypt a string value if a key is available
        Returns the original value if no key is available
        """
        if not value or value.startswith("encrypted:"):
            return value

        key = cls._get_encryption_key()
        if not key:  # No encryption if no key
            return value

        f = Fernet(key)
        encrypted = f.encrypt(value.encode())
        return f"encrypted:{encrypted.decode()}"

    @classmethod
    def decrypt(cls, value: str) -> str:
        """
        Decrypt an encrypted string value if a key is available
        Returns the original value if no key is available or decryption fails
        """
        if not value or not value.startswith("encrypted:"):
            return value

        key = cls._get_encryption_key()
        if not key:  # No decryption if no key
            raise ValueError(
                "Cannot decrypt GOOGLE_API_KEY: WEBUI_SECRET_KEY is missing. Re-enter the API key."
            )

        try:
            encrypted_part = value[len("encrypted:") :]
            f = Fernet(key)
            decrypted = f.decrypt(encrypted_part.encode())
            return decrypted.decode()
        except InvalidToken as exc:
            raise ValueError(
                "Cannot decrypt GOOGLE_API_KEY: secret key changed or ciphertext is invalid. Re-enter the API key."
            ) from exc

    # Pydantic integration
    @classmethod
    def __get_pydantic_core_schema__(
        cls, _source_type: Any, _handler: GetCoreSchemaHandler
    ) -> core_schema.CoreSchema:
        return core_schema.union_schema(
            [
                core_schema.is_instance_schema(cls),
                core_schema.chain_schema(
                    [
                        core_schema.str_schema(),
                        core_schema.no_info_plain_validator_function(
                            lambda value: cls(cls.encrypt(value) if value else value)
                        ),
                    ]
                ),
            ],
            serialization=core_schema.plain_serializer_function_ser_schema(
                lambda instance: str(instance)
            ),
        )


class Pipe:
    """
    Pipeline for interacting with Google Gemini models.
    """

    @property
    def user(self):
        return self._request_user.get()

    @user.setter
    def user(self, value):
        self._request_user.set(value)

    # User-overridable configuration valves
    class UserValves(BaseModel):
        IMAGE_GENERATION_ASPECT_RATIO: str = Field(
            default=os.getenv("GOOGLE_IMAGE_GENERATION_ASPECT_RATIO", "default"),
            description="Default aspect ratio for image generation.",
            json_schema_extra={"enum": ASPECT_RATIO_OPTIONS},
        )
        IMAGE_GENERATION_RESOLUTION: str = Field(
            default=os.getenv("GOOGLE_IMAGE_GENERATION_RESOLUTION", "default"),
            description="Default resolution for image generation.",
            json_schema_extra={"enum": RESOLUTION_OPTIONS},
        )
        VIDEO_GENERATION_ASPECT_RATIO: str = Field(
            default=os.getenv("GOOGLE_VIDEO_GENERATION_ASPECT_RATIO", "default"),
            description="Default aspect ratio for video generation (16:9 landscape or 9:16 portrait).",
            json_schema_extra={"enum": VIDEO_ASPECT_RATIO_OPTIONS},
        )
        VIDEO_GENERATION_RESOLUTION: str = Field(
            default=os.getenv("GOOGLE_VIDEO_GENERATION_RESOLUTION", "default"),
            description="Default resolution for video generation (720p, 1080p, or 4k).",
            json_schema_extra={"enum": VIDEO_RESOLUTION_OPTIONS},
        )
        VIDEO_GENERATION_DURATION: str = Field(
            default=os.getenv("GOOGLE_VIDEO_GENERATION_DURATION", "default"),
            description="Default duration in seconds for video generation (4, 5, 6, or 8 - availability varies by model).",
            json_schema_extra={"enum": VIDEO_DURATION_OPTIONS},
        )

    # Configuration valves for the pipeline
    class Valves(BaseModel):
        BASE_URL: str = Field(
            default=os.getenv(
                "GOOGLE_GENAI_BASE_URL", "https://generativelanguage.googleapis.com/"
            ),
            description="Base URL for the Google Generative AI API.",
        )
        GOOGLE_API_KEY: EncryptedStr = Field(
            default=os.getenv("GOOGLE_API_KEY", ""),
            description="API key for Google Generative AI (used if USE_VERTEX_AI is false).",
            json_schema_extra={"input": {"type": "password"}},
        )
        API_VERSION: str = Field(
            default=os.getenv("GOOGLE_API_VERSION", "v1beta"),
            description="API version to use for Google Generative AI. v1beta is recommended for Gemini 3 built-in + custom tool combinations.",
        )
        STREAMING_ENABLED: bool = Field(
            default=os.getenv("GOOGLE_STREAMING_ENABLED", "true").lower() == "true",
            description="Enable streaming responses (set false to force non-streaming mode).",
        )
        NATIVE_TOOL_STREAMING_SAFE_MODE: bool = Field(
            default=os.getenv("GOOGLE_NATIVE_TOOL_STREAMING_SAFE_MODE", "true").lower()
            == "true",
            description=(
                "Force non-streaming generation when Open WebUI native Python tools are "
                "available. This avoids the google-genai/Gemini 3 streaming function-call "
                "path that can finish with an empty text response."
            ),
        )
        AUTO_GOOGLE_SEARCH: bool = Field(
            default=os.getenv("GOOGLE_AUTO_SEARCH", "true").lower() == "true",
            description=(
                "Automatically expose Google Search grounding to supported text models. "
                "Gemini decides whether a search is needed for each request."
            ),
        )
        AUTO_THINKING: bool = Field(
            default=os.getenv("GOOGLE_AUTO_THINKING", "true").lower() == "true",
            description=(
                "Automatically choose Gemini thinking_level from the current request "
                "using local heuristics only (no extra router API call). Explicit "
                "per-chat reasoning_effort always wins."
            ),
        )
        AUTO_THINKING_DEFAULT_LEVEL: str = Field(
            default=os.getenv("GOOGLE_AUTO_THINKING_DEFAULT_LEVEL", "low"),
            description=(
                "Baseline level for ordinary text requests before complexity signals "
                "raise it. The value is normalized to the levels supported by the "
                "selected Gemini model."
            ),
            json_schema_extra={"enum": ["minimal", "low", "medium", "high"]},
        )
        AUTO_THINKING_LONG_CONTEXT_LEVEL: str = Field(
            default=os.getenv("GOOGLE_AUTO_THINKING_LONG_CONTEXT_LEVEL", "medium"),
            description=(
                "Target level for long prompts, document analysis, or multi-attachment "
                "requests. Normalized to the selected model's supported levels."
            ),
            json_schema_extra={"enum": ["minimal", "low", "medium", "high"]},
        )
        AUTO_THINKING_COMPLEX_LEVEL: str = Field(
            default=os.getenv("GOOGLE_AUTO_THINKING_COMPLEX_LEVEL", "high"),
            description=(
                "Target level for hard math, proofs, complex debugging, architecture, "
                "multi-step reasoning, and similarly difficult tasks."
            ),
            json_schema_extra={"enum": ["minimal", "low", "medium", "high"]},
        )
        AUTO_THINKING_LONG_TEXT_CHARS: int = Field(
            default=int(os.getenv("GOOGLE_AUTO_THINKING_LONG_TEXT_CHARS", "8000")),
            ge=1000,
            le=200000,
            description=(
                "Latest-user-text length that promotes an otherwise ordinary request "
                "to the long-context thinking level."
            ),
        )
        AUTO_THINKING_VERY_LONG_TEXT_CHARS: int = Field(
            default=int(
                os.getenv("GOOGLE_AUTO_THINKING_VERY_LONG_TEXT_CHARS", "30000")
            ),
            ge=5000,
            le=1000000,
            description=(
                "Latest-user-text length that can promote a request to the complex "
                "thinking level."
            ),
        )
        AUTO_THINKING_MULTIFILE_THRESHOLD: int = Field(
            default=int(os.getenv("GOOGLE_AUTO_THINKING_MULTIFILE_THRESHOLD", "2")),
            ge=1,
            le=20,
            description=(
                "Number of attached files that promotes the request to at least the "
                "long-context thinking level."
            ),
        )
        AUTO_THINKING_SHOW_STATUS: bool = Field(
            default=os.getenv("GOOGLE_AUTO_THINKING_SHOW_STATUS", "false").lower()
            == "true",
            description=(
                "Show a brief Open WebUI status event with the automatically selected "
                "thinking level. Disabled by default; the decision is always logged."
            ),
        )
        LIVE_PROGRESS_STATUS: bool = Field(
            default=os.getenv("GOOGLE_LIVE_PROGRESS_STATUS", "true").lower() == "true",
            description=(
                "Show short operational progress messages in Open WebUI before Gemini's "
                "first answer token arrives (request analysis, document reading, web-search "
                "preparation, tool preparation, and answer generation)."
            ),
        )
        LIVE_PROGRESS_SHOW_THINKING_LEVEL: bool = Field(
            default=os.getenv(
                "GOOGLE_LIVE_PROGRESS_SHOW_THINKING_LEVEL", "true"
            ).lower()
            == "true",
            description=(
                "Include the selected Gemini thinking level in the compact progress status. "
                "This exposes only the configured level, never hidden chain-of-thought."
            ),
        )
        LIVE_PROGRESS_TIMELINE: bool = Field(
            default=os.getenv("GOOGLE_LIVE_PROGRESS_TIMELINE", "true").lower()
            == "true",
            description=(
                "While waiting for Gemini's first visible token, rotate through short "
                "GPT-like progress messages. These are operational waiting indicators, "
                "not a disclosure of hidden chain-of-thought."
            ),
        )
        LIVE_PROGRESS_FINAL_TIMING: bool = Field(
            default=os.getenv("GOOGLE_LIVE_PROGRESS_FINAL_TIMING", "true").lower()
            == "true",
            description=(
                "Keep a final status such as 'Thought for 5.8 seconds · low' after "
                "generation finishes."
            ),
        )
        LIVE_PROGRESS_FIRST_TOKEN_TIMING: bool = Field(
            default=os.getenv("GOOGLE_LIVE_PROGRESS_FIRST_TOKEN_TIMING", "true").lower()
            == "true",
            description=(
                "Include time-to-first-visible-token in the final timing status when streaming."
            ),
        )
        PROVIDER_THOUGHT_SUMMARY_IN_RESPONSE: bool = Field(
            default=os.getenv(
                "GOOGLE_PROVIDER_THOUGHT_SUMMARY_IN_RESPONSE", "true"
            ).lower()
            == "true",
            description=(
                "If Gemini explicitly returns provider thought-summary parts, preserve them "
                "inside a collapsed <details> block. The function never invents a reasoning "
                "summary when the API returns none."
            ),
        )
        PROVIDER_THOUGHT_SUMMARY_MAX_CHARS: int = Field(
            default=int(os.getenv("GOOGLE_PROVIDER_THOUGHT_SUMMARY_MAX_CHARS", "2500")),
            ge=200,
            le=20000,
            description=(
                "Maximum characters of provider-returned Gemini thought summary shown "
                "inside the collapsed response details block."
            ),
        )
        AUTO_IMAGE_ROUTING: bool = Field(
            default=os.getenv("GOOGLE_AUTO_IMAGE_ROUTING", "true").lower() == "true",
            description=(
                "Automatically route explicit image generation/editing requests from "
                "Gemini text models to the configured Nano Banana image model."
            ),
        )
        FORCE_NANO_BANANA_2_VISIBLE: bool = Field(
            default=os.getenv("GOOGLE_FORCE_NANO_BANANA_2_VISIBLE", "true").lower()
            == "true",
            description=(
                "Always expose Nano Banana 2 in Open WebUI's model picker, even when "
                "models.list() is stale. Uses AUTO_IMAGE_MODEL and respects MODEL_WHITELIST."
            ),
        )
        AUTO_IMAGE_MODEL: str = Field(
            default=os.getenv("GOOGLE_AUTO_IMAGE_MODEL", "gemini-3.1-flash-image"),
            description=(
                "Real Gemini image-generation model used by automatic image routing. "
                "Nano Banana 2 GA model ID is gemini-3.1-flash-image."
            ),
        )
        AUTO_IMAGE_ROUTING_STATUS: bool = Field(
            default=os.getenv("GOOGLE_AUTO_IMAGE_ROUTING_STATUS", "true").lower()
            == "true",
            description=(
                "Emit a short status event when a text-model request is automatically "
                "routed to Nano Banana 2."
            ),
        )
        AUTO_GOOGLE_SEARCH_SKIP_TASKS: bool = Field(
            default=os.getenv("GOOGLE_AUTO_SEARCH_SKIP_TASKS", "true").lower()
            == "true",
            description=(
                "Do not enable automatic Google Search for Open WebUI background tasks "
                "such as title/tag generation."
            ),
        )
        ENABLE_URL_CONTEXT_WITH_SEARCH: bool = Field(
            default=os.getenv("GOOGLE_ENABLE_URL_CONTEXT_WITH_SEARCH", "false").lower()
            == "true",
            description=(
                "Also enable URL Context whenever Google Search grounding is enabled. "
                "Disabled by default because URL Context is a separate tool."
            ),
        )
        TOOL_COMBINATION_RAW_FALLBACK: bool = Field(
            default=os.getenv("GOOGLE_TOOL_COMBINATION_RAW_FALLBACK", "true").lower()
            == "true",
            description=(
                "When Gemini 3 combines Google Search with Open WebUI function tools, "
                "also inject toolConfig.includeServerSideToolInvocations through "
                "HttpOptions.extra_body. This works around older google-genai SDKs that "
                "accept ToolConfig but fail to serialize the preview field."
            ),
        )
        AUTO_GOOGLE_SEARCH_SMART: bool = Field(
            default=os.getenv("GOOGLE_AUTO_SEARCH_SMART", "true").lower() == "true",
            description=(
                "When automatic Google Search is enabled, expose Search only for prompts "
                "that look freshness/web-dependent (weather, news, prices, recent releases, "
                "current public facts, etc.) instead of attaching Search to every request."
            ),
        )
        COMBINE_GOOGLE_SEARCH_WITH_NATIVE_TOOLS: bool = Field(
            default=os.getenv("GOOGLE_COMBINE_SEARCH_NATIVE_TOOLS", "false").lower()
            == "true",
            description=(
                "Preview/advanced mode. Allow Google Search and Open WebUI native Python "
                "tools in the same Gemini request. Disabled by default because Open WebUI "
                "currently pins an older google-genai SDK where tool-context circulation "
                "is not typed, and AFC + tool combinations can return empty responses. "
                "When disabled, Search requests use Google Search only; other requests keep "
                "native Open WebUI tools."
            ),
        )
        ENABLE_OCR_VIRTUAL_MODEL: bool = Field(
            default=os.getenv("GOOGLE_ENABLE_OCR_VIRTUAL_MODEL", "true").lower()
            == "true",
            description=(
                "Expose a virtual OCR-optimized model in Open WebUI. The virtual model "
                "is mapped internally to OCR_BASE_MODEL_ID before calling Gemini."
            ),
        )
        OCR_VIRTUAL_MODEL_ID: str = Field(
            default=os.getenv("GOOGLE_OCR_VIRTUAL_MODEL_ID", "gemini-3.8-flash-ocr"),
            description="Virtual model ID shown to Open WebUI for OCR-optimized use.",
        )
        OCR_VIRTUAL_MODEL_NAME: str = Field(
            default=os.getenv(
                "GOOGLE_OCR_VIRTUAL_MODEL_NAME",
                "Gemini 3.8 Flash OCR (Korean High-Res)",
            ),
            description="Display name for the virtual OCR model.",
        )
        OCR_BASE_MODEL_ID: str = Field(
            default=os.getenv("GOOGLE_OCR_BASE_MODEL_ID", "gemini-3.8-flash"),
            description=(
                "Real Gemini API model used behind the virtual OCR model. "
                "Defaults to gemini-3.8-flash; the previous 3.7 OCR base is migrated to 3.8."
            ),
        )
        OCR_MEDIA_RESOLUTION: str = Field(
            default=os.getenv("GOOGLE_OCR_MEDIA_RESOLUTION", "high"),
            description=(
                "Global media resolution for the OCR virtual model. "
                "Allowed: default, low, medium, high."
            ),
            json_schema_extra={"enum": ["default", "low", "medium", "high"]},
        )
        OCR_THINKING_LEVEL: str = Field(
            default=os.getenv("GOOGLE_OCR_THINKING_LEVEL", "low"),
            description=(
                "Thinking level used by the OCR virtual model. Default low is valid "
                "for Gemini 3.7 Flash and usually preferable because OCR benefits more "
                "from visual fidelity than deeper reasoning."
            ),
            json_schema_extra={"enum": ["low", "medium", "high"]},
        )
        OCR_INCLUDE_THOUGHTS: bool = Field(
            default=os.getenv("GOOGLE_OCR_INCLUDE_THOUGHTS", "false").lower() == "true",
            description="Show Gemini thought output for the OCR virtual model.",
        )
        OCR_DISABLE_GOOGLE_SEARCH: bool = Field(
            default=os.getenv("GOOGLE_OCR_DISABLE_GOOGLE_SEARCH", "true").lower()
            == "true",
            description=(
                "Disable Google Search for the OCR virtual model so OCR is grounded "
                "only in the attached document/image."
            ),
        )
        OCR_DISABLE_NATIVE_TOOLS: bool = Field(
            default=os.getenv("GOOGLE_OCR_DISABLE_NATIVE_TOOLS", "true").lower()
            == "true",
            description=(
                "Disable Open WebUI native Python tools for the OCR virtual model. "
                "This also avoids AFC/tool-call paths that can interfere with long OCR output."
            ),
        )
        OCR_SYSTEM_PROMPT: str = Field(
            default=os.getenv(
                "GOOGLE_OCR_SYSTEM_PROMPT",
                (
                    "OCR 전용 처리 규칙:\n"
                    "- 의미 추론이나 자연스러운 문장 교정보다 원본의 시각적 문자 전사를 최우선으로 한다.\n"
                    "- 한글 이름, 학교명, 회사명, 고유명사, 학번, 숫자는 문자 단위로 한 번 더 대조한다.\n"
                    "- 한글 고유명사를 흔한 이름이나 문맥에 맞춰 임의 교정하지 않는다. 초성·중성·종성을 실제 보이는 형태에 근거해 판독한다.\n"
                    "- 첫 판독 후 한글/숫자/고유명사를 원본 위치와 다시 비교하고, 두 판독이 다르면 재검토한다.\n"
                    "- 확실하지 않은 문자는 추측으로 확정하지 말고 [불확실: ...] 형식으로 표시한다.\n"
                    "- 원문을 요약·생략·의역하지 않는다. 구조화는 정확한 전사가 끝난 뒤 수행한다.\n"
                    "- 첨부 문서 자체만 근거로 사용하며 웹 검색이나 외부 지식으로 원문을 보정하지 않는다.\n"
                    "- 이 내부 검증 절차를 별도로 설명하지 말고 사용자가 요청한 최종 형식만 출력한다."
                ),
            ),
            description=(
                "Supplemental system instruction automatically prepended when the "
                "virtual OCR model is selected."
            ),
        )
        INCLUDE_THOUGHTS: bool = Field(
            default=os.getenv("GOOGLE_INCLUDE_THOUGHTS", "true").lower() == "true",
            description="Enable Gemini thoughts outputs (set false to disable).",
        )
        THINKING_BUDGET: int = Field(
            default=int(os.getenv("GOOGLE_THINKING_BUDGET", "-1")),
            description="Thinking budget for Gemini 2.5 models (0=disabled, -1=dynamic, 1-32768=fixed token limit). "
            "Not used for Gemini 3 models which use THINKING_LEVEL instead.",
        )
        THINKING_LEVEL: str = Field(
            default=os.getenv("GOOGLE_THINKING_LEVEL", ""),
            description=(
                "Manual fallback thinking level for Gemini 3 models. Gemini 3.7+ Flash "
                "supports low/medium/high (minimal is not supported); Gemini 3.5/3.6 "
                "Flash support minimal/low/medium/high. Some Pro/image variants expose "
                "narrower sets. Empty string means use the model default when Auto "
                "Thinking does not apply."
            ),
        )
        USE_VERTEX_AI: bool = Field(
            default=os.getenv("GOOGLE_GENAI_USE_VERTEXAI", "false").lower() == "true",
            description="Whether to use Google Cloud Vertex AI instead of the Google Generative AI API.",
        )
        VERTEX_PROJECT: str | None = Field(
            default=os.getenv("GOOGLE_CLOUD_PROJECT"),
            description="The Google Cloud project ID to use with Vertex AI.",
        )
        VERTEX_LOCATION: str = Field(
            default=os.getenv("GOOGLE_CLOUD_LOCATION", "global"),
            description="The Google Cloud region to use with Vertex AI.",
        )
        VERTEX_AI_RAG_STORE: str | None = Field(
            default=os.getenv("GOOGLE_VERTEX_AI_RAG_STORE"),
            description="Vertex AI RAG Store path for grounding (e.g., projects/PROJECT/locations/LOCATION/ragCorpora/DATA_STORE_ID). Only used when USE_VERTEX_AI is true.",
        )
        BYPASS_BACKEND_RAG: bool = Field(
            default=os.getenv("GOOGLE_BYPASS_BACKEND_RAG", "false").lower() == "true",
            description=(
                "Bypass Open WebUI's backend RAG: strip the RAG context injected by the "
                "backend (<context>...</context> template) from the prompt and instead "
                "attach the original files (PDF, text, code, etc.) natively to the last "
                "user message, letting Gemini read the full documents itself. "
                "Install the companion 'Google Gemini RAG Bypass' filter to also skip "
                "the backend retrieval step entirely (the pipe consumes the filter's "
                "stash automatically, even when this valve is off). "
                "Inspired by the Gemini Manifold google_genai pipe + companion filter."
            ),
        )
        RAG_BYPASS_MAX_INLINE_MB: int = Field(
            default=int(os.getenv("GOOGLE_RAG_BYPASS_MAX_INLINE_MB", "18")),
            description=(
                "When BYPASS_BACKEND_RAG is enabled, files up to this size (MB) are sent "
                "inline. Larger files are uploaded via the Google Files API (not available "
                "on Vertex AI; falls back to the backend-extracted text in that case)."
            ),
        )
        ENABLE_HWPX_SUPPORT: bool = Field(
            default=os.getenv("GOOGLE_ENABLE_HWPX_SUPPORT", "true").lower() == "true",
            description=(
                "Enable direct .hwpx handling before generic RAG-bypass fallback. "
                "HWPX is parsed directly with Python's standard library. Binary .hwp "
                "is intentionally outside this function's special handling."
            ),
        )
        HWPX_MAX_TEXT_CHARS: int = Field(
            default=int(os.getenv("GOOGLE_HWPX_MAX_TEXT_CHARS", "1500000")),
            ge=10000,
            le=5000000,
            description=(
                "Maximum extracted HWPX text characters attached to one Gemini request. "
                "The text is truncated only when this safety ceiling is exceeded."
            ),
        )
        HWPX_INCLUDE_EMBEDDED_IMAGES: bool = Field(
            default=os.getenv("GOOGLE_HWPX_INCLUDE_EMBEDDED_IMAGES", "true").lower()
            == "true",
            description=(
                "Attach supported images stored inside HWPX BinData to Gemini in addition "
                "to extracted document text. Useful for image-heavy Korean documents."
            ),
        )
        HWPX_MAX_EMBEDDED_IMAGES: int = Field(
            default=int(os.getenv("GOOGLE_HWPX_MAX_EMBEDDED_IMAGES", "12")),
            ge=0,
            le=50,
            description="Maximum number of HWPX embedded images sent with one document.",
        )
        HWPX_MAX_IMAGE_MB: int = Field(
            default=int(os.getenv("GOOGLE_HWPX_MAX_IMAGE_MB", "8")),
            ge=1,
            le=20,
            description=(
                "Maximum size in MB for each HWPX embedded image sent inline to Gemini."
            ),
        )
        HWPX_INCLUDE_PREVIEW_IF_EMPTY: bool = Field(
            default=os.getenv("GOOGLE_HWPX_INCLUDE_PREVIEW_IF_EMPTY", "true").lower()
            == "true",
            description=(
                "If an HWPX contains little/no extractable text and no BinData image, "
                "send Preview/PrvImage.png as a visual fallback when available."
            ),
        )
        USE_PERMISSIVE_SAFETY: bool = Field(
            default=os.getenv("GOOGLE_USE_PERMISSIVE_SAFETY", "false").lower()
            == "true",
            description="Use permissive safety settings for content generation.",
        )
        MODEL_CACHE_TTL: int = Field(
            default=int(os.getenv("GOOGLE_MODEL_CACHE_TTL", "600")),
            description="Time in seconds to cache the model list before refreshing",
        )
        RETRY_COUNT: int = Field(
            default=int(os.getenv("GOOGLE_RETRY_COUNT", "2")),
            description="Number of times to retry API calls on temporary failures",
        )
        DEFAULT_SYSTEM_PROMPT: str = Field(
            default=os.getenv("GOOGLE_DEFAULT_SYSTEM_PROMPT", ""),
            description="Default system prompt applied to all chats. If a user-defined system prompt exists, "
            "this is prepended to it. Leave empty to disable.",
        )
        ENABLE_FORWARD_USER_INFO_HEADERS: bool = Field(
            default=os.getenv(
                "GOOGLE_ENABLE_FORWARD_USER_INFO_HEADERS", "false"
            ).lower()
            == "true",
            description="Whether to forward user information headers.",
        )
        MODEL_ADDITIONAL: str = Field(
            default=os.getenv(
                "GOOGLE_MODEL_ADDITIONAL",
                "gemini-3.7-flash,gemini-3.1-flash-image",
            ),
            description=(
                "A comma-separated list of model IDs to manually add to the list of "
                "available models. Defaults include Gemini 3.7 Flash and the GA "
                "Nano Banana 2 model gemini-3.1-flash-image."
            ),
        )
        MODEL_WHITELIST: str = Field(
            default=os.getenv("GOOGLE_MODEL_WHITELIST", ""),
            description="A comma-separated list of model IDs to show in the models list. "
            "If set, only these models will be available (after MODEL_ADDITIONAL is applied). "
            "Leave empty to show all models.",
        )
        USE_ENTERPRISE_WEB_SEARCH: bool = Field(
            default=os.getenv("GOOGLE_USE_ENTERPRISE_WEB_SEARCH", "false").lower()
            == "true",
            description="Whether to use Enterprise Web Search instead of standard Google search when grounding is enabled. "
            "Only available on Vertex AI.",
        )

        # Image Processing Configuration
        IMAGE_GENERATION_ASPECT_RATIO: str = Field(
            default=os.getenv("GOOGLE_IMAGE_GENERATION_ASPECT_RATIO", "default"),
            description="Default aspect ratio for image generation.",
            json_schema_extra={"enum": ASPECT_RATIO_OPTIONS},
        )
        IMAGE_GENERATION_RESOLUTION: str = Field(
            default=os.getenv("GOOGLE_IMAGE_GENERATION_RESOLUTION", "default"),
            description="Default resolution for image generation.",
            json_schema_extra={"enum": RESOLUTION_OPTIONS},
        )
        IMAGE_MAX_SIZE_MB: float = Field(
            default=float(os.getenv("GOOGLE_IMAGE_MAX_SIZE_MB", "15.0")),
            description="Maximum image size in MB before compression is applied",
        )
        IMAGE_MAX_DIMENSION: int = Field(
            default=int(os.getenv("GOOGLE_IMAGE_MAX_DIMENSION", "2048")),
            description="Maximum width or height in pixels before resizing",
        )
        IMAGE_COMPRESSION_QUALITY: int = Field(
            default=int(os.getenv("GOOGLE_IMAGE_COMPRESSION_QUALITY", "85")),
            description="JPEG compression quality (1-100, higher = better quality but larger size)",
        )
        IMAGE_ENABLE_OPTIMIZATION: bool = Field(
            default=os.getenv("GOOGLE_IMAGE_ENABLE_OPTIMIZATION", "true").lower()
            == "true",
            description="Enable intelligent image optimization for API compatibility",
        )
        IMAGE_PNG_COMPRESSION_THRESHOLD_MB: float = Field(
            default=float(os.getenv("GOOGLE_IMAGE_PNG_THRESHOLD_MB", "0.5")),
            description="PNG files above this size (MB) will be converted to JPEG for better compression",
        )
        IMAGE_HISTORY_MAX_REFERENCES: int = Field(
            default=int(os.getenv("GOOGLE_IMAGE_HISTORY_MAX_REFERENCES", "5")),
            description="Maximum total number of images (history + current message) to include in a generation call",
        )
        IMAGE_ADD_LABELS: bool = Field(
            default=os.getenv("GOOGLE_IMAGE_ADD_LABELS", "true").lower() == "true",
            description="If true, add small text labels like [Image 1] before each image part so the model can reference them.",
        )
        IMAGE_DEDUP_HISTORY: bool = Field(
            default=os.getenv("GOOGLE_IMAGE_DEDUP_HISTORY", "true").lower() == "true",
            description="If true, deduplicate identical images (by hash) when constructing history context",
        )
        IMAGE_HISTORY_FIRST: bool = Field(
            default=os.getenv("GOOGLE_IMAGE_HISTORY_FIRST", "true").lower() == "true",
            description="If true (default), history images precede current message images; if false, current images first.",
        )
        IMAGE_EDIT_CURRENT_FIRST: bool = Field(
            default=os.getenv("GOOGLE_IMAGE_EDIT_CURRENT_FIRST", "true").lower()
            == "true",
            description=(
                "For image-edit requests, prioritize images attached to the current "
                "user turn over older conversation images."
            ),
        )
        IMAGE_EDIT_LATEST_HISTORY_ONLY: bool = Field(
            default=os.getenv("GOOGLE_IMAGE_EDIT_LATEST_HISTORY_ONLY", "true").lower()
            == "true",
            description=(
                "When the user asks to edit a previously generated image without "
                "reattaching it, use the most recent image found in chat history "
                "instead of sending every historical image."
            ),
        )

        # Video Generation Configuration (Veo models)
        VIDEO_GENERATION_ASPECT_RATIO: str = Field(
            default=os.getenv("GOOGLE_VIDEO_GENERATION_ASPECT_RATIO", "default"),
            description="Default aspect ratio for video generation (16:9 landscape or 9:16 portrait).",
            json_schema_extra={"enum": VIDEO_ASPECT_RATIO_OPTIONS},
        )
        VIDEO_GENERATION_RESOLUTION: str = Field(
            default=os.getenv("GOOGLE_VIDEO_GENERATION_RESOLUTION", "default"),
            description="Default resolution for video generation (720p, 1080p, or 4k).",
            json_schema_extra={"enum": VIDEO_RESOLUTION_OPTIONS},
        )
        VIDEO_GENERATION_DURATION: str = Field(
            default=os.getenv("GOOGLE_VIDEO_GENERATION_DURATION", "default"),
            description="Default duration in seconds for video generation (4, 5, 6, or 8 - availability varies by model).",
            json_schema_extra={"enum": VIDEO_DURATION_OPTIONS},
        )
        VIDEO_GENERATION_NEGATIVE_PROMPT: str = Field(
            default=os.getenv("GOOGLE_VIDEO_GENERATION_NEGATIVE_PROMPT", ""),
            description="Default negative prompt for video generation (describes what not to include).",
        )
        VIDEO_GENERATION_PERSON_GENERATION: str = Field(
            default=os.getenv("GOOGLE_VIDEO_GENERATION_PERSON_GENERATION", "default"),
            description="Controls generation of people in videos (allow_all, allow_adult, dont_allow).",
            json_schema_extra={"enum": VIDEO_PERSON_GENERATION_OPTIONS},
        )
        VIDEO_GENERATION_ENHANCE_PROMPT: bool = Field(
            default=os.getenv("GOOGLE_VIDEO_GENERATION_ENHANCE_PROMPT", "true").lower()
            == "true",
            description="Enable prompt enhancement for video generation.",
        )
        VIDEO_POLL_INTERVAL: int = Field(
            default=int(os.getenv("GOOGLE_VIDEO_POLL_INTERVAL", "10")),
            description="Polling interval in seconds when waiting for video generation to complete.",
        )
        VIDEO_POLL_TIMEOUT: int = Field(
            default=int(os.getenv("GOOGLE_VIDEO_POLL_TIMEOUT", "600")),
            description="Maximum time in seconds to wait for video generation before timing out (0=no limit).",
        )

    # ---------------- Internal Helpers ---------------- #
    async def _gather_history_images(
        self,
        messages: List[Dict[str, Any]],
        last_user_msg: Dict[str, Any],
        optimization_stats: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        history_images: List[Dict[str, Any]] = []
        for msg in messages:
            if msg is last_user_msg:
                continue
            if msg.get("role") not in {"user", "assistant"}:
                continue
            _p, parts = await self._extract_images_from_message(
                msg, stats_list=optimization_stats
            )
            if parts:
                history_images.extend(parts)
        return history_images

    def _deduplicate_images(self, images: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if not self.valves.IMAGE_DEDUP_HISTORY:
            return images
        seen: set[str] = set()
        result: List[Dict[str, Any]] = []
        for part in images:
            try:
                data = part["inline_data"]["data"]
                # Hash full base64 payload for stronger dedup reliability
                h = hashlib.sha256(data.encode()).hexdigest()
                if h in seen:
                    continue
                seen.add(h)
            except Exception as e:
                # Skip images with malformed or missing data, but log for debugging.
                self.log.debug(f"Skipping image in deduplication due to error: {e}")
            result.append(part)
        return result

    def _combine_system_prompts(
        self, user_system_prompt: Optional[str]
    ) -> Optional[str]:
        """Combine default system prompt with user-defined system prompt.

        If DEFAULT_SYSTEM_PROMPT is set and user_system_prompt exists,
        the default is prepended to the user's prompt.
        If only DEFAULT_SYSTEM_PROMPT is set, it is used as the system prompt.
        If only user_system_prompt is set, it is used as-is.

        Args:
            user_system_prompt: The user-defined system prompt from messages (may be None)

        Returns:
            Combined system prompt or None if neither is set
        """
        default_prompt = self.valves.DEFAULT_SYSTEM_PROMPT.strip()
        user_prompt = user_system_prompt.strip() if user_system_prompt else ""

        if default_prompt and user_prompt:
            combined = f"{default_prompt}\n\n{user_prompt}"
            self.log.debug(
                f"Combined system prompts: default ({len(default_prompt)} chars) + "
                f"user ({len(user_prompt)} chars) = {len(combined)} chars"
            )
            return combined
        elif default_prompt:
            self.log.debug(f"Using default system prompt ({len(default_prompt)} chars)")
            return default_prompt
        elif user_prompt:
            return user_prompt
        return None

    def _apply_order_and_limit(
        self,
        history: List[Dict[str, Any]],
        current: List[Dict[str, Any]],
    ) -> Tuple[List[Dict[str, Any]], List[bool]]:
        """Combine history & current image parts honoring order & global limit.

        Returns:
            (combined_parts, reused_flags) where reused_flags[i] == True indicates
            the image originated from history, False if from current message.
        """
        history_first = self.valves.IMAGE_HISTORY_FIRST
        limit = max(1, self.valves.IMAGE_HISTORY_MAX_REFERENCES)
        combined: List[Dict[str, Any]] = []
        reused_flags: List[bool] = []

        def append(parts: List[Dict[str, Any]], reused: bool):
            for p in parts:
                if len(combined) >= limit:
                    break
                combined.append(p)
                reused_flags.append(reused)

        if history_first:
            append(history, True)
            append(current, False)
        else:
            append(current, False)
            append(history, True)
        return combined, reused_flags

    async def _emit_image_stats(
        self,
        ordered_stats: List[Dict[str, Any]],
        reused_flags: List[bool],
        total_limit: int,
        __event_emitter__: Callable,
    ) -> None:
        """Emit per-image optimization stats aligned with final combined order.

        ordered_stats: stats list in the exact order images will be sent (same length as combined image list)
        reused_flags: parallel list indicating whether image originated from history
        """
        if not ordered_stats:
            return
        for idx, stat in enumerate(ordered_stats, start=1):
            reused = reused_flags[idx - 1] if idx - 1 < len(reused_flags) else False
            stat_copy = dict(stat) if stat else {}
            stat_copy.update({"index": idx, "reused": reused})
            if stat and stat.get("original_size_mb") is not None:
                desc = f"Image {idx}: {stat['original_size_mb']:.2f}MB -> {stat['final_size_mb']:.2f}MB"
                if stat.get("quality") is not None:
                    desc += f" (Q{stat['quality']})"
            else:
                desc = f"Image {idx}: (no metrics)"
            reasons = stat.get("reasons") if stat else None
            if reasons:
                desc += " | " + ", ".join(reasons[:3])
            await self._emit_optional(
                __event_emitter__,
                {
                    "type": "status",
                    "data": {
                        "action": "image_optimization",
                        "description": desc,
                        "index": idx,
                        "done": False,
                        "details": stat_copy,
                    },
                },
            )
        await self._emit_optional(
            __event_emitter__,
            {
                "type": "status",
                "data": {
                    "action": "image_optimization",
                    "description": f"{len(ordered_stats)} image(s) processed (limit {total_limit}).",
                    "done": True,
                },
            },
        )

    async def _build_image_generation_contents(
        self,
        messages: List[Dict[str, Any]],
        __event_emitter__: Callable,
        *,
        body: Optional[Dict[str, Any]] = None,
        __metadata__: Optional[Dict[str, Any]] = None,
    ) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        """Construct the contents payload for image-capable models.

        Returns tuple (contents, system_instruction) where system_instruction is extracted from system messages.
        """
        # Extract user-defined system instruction first
        user_system_instruction = next(
            (msg["content"] for msg in messages if msg.get("role") == "system"),
            None,
        )

        # Combine with default system prompt if configured
        system_instruction = self._combine_system_prompts(user_system_instruction)

        last_user_msg = next(
            (m for m in reversed(messages) if m.get("role") == "user"), None
        )
        if not last_user_msg:
            raise ValueError("No user message found")

        optimization_stats: List[Dict[str, Any]] = []
        history_images = await self._gather_history_images(
            messages, last_user_msg, optimization_stats
        )
        prompt, current_images = await self._extract_images_from_message(
            last_user_msg, stats_list=optimization_stats
        )

        # Open WebUI may NOT place a newly attached image inside message.content.
        # Collect request-level files and RAG-bypass companion stash as well.
        extra_file_entries: List[Dict[str, Any]] = []
        if isinstance(body, dict):
            extra_file_entries.extend(
                f for f in (body.get("files") or []) if isinstance(f, dict)
            )
            body_md = body.get("metadata") or {}
            if isinstance(body_md, dict):
                extra_file_entries.extend(
                    f for f in (body_md.get("files") or []) if isinstance(f, dict)
                )
                extra_file_entries.extend(
                    f
                    for f in (body_md.get("_google_gemini_bypassed_files") or [])
                    if isinstance(f, dict)
                )
        if isinstance(__metadata__, dict):
            extra_file_entries.extend(
                f for f in (__metadata__.get("files") or []) if isinstance(f, dict)
            )
            extra_file_entries.extend(
                f
                for f in (__metadata__.get("_google_gemini_bypassed_files") or [])
                if isinstance(f, dict)
            )

        if extra_file_entries:
            current_images.extend(
                await self._extract_images_from_file_entries(
                    extra_file_entries, stats_list=optimization_stats
                )
            )

        # Deduplicate
        history_images = self._deduplicate_images(history_images)
        current_images = self._deduplicate_images(current_images)

        edit_mode = self._is_image_edit_request(prompt)

        if edit_mode:
            # Edits must operate on the intended source image. A newly attached
            # image takes priority; otherwise reuse the most recent historical
            # image (typically the image generated in the previous turn).
            if current_images and self.valves.IMAGE_EDIT_CURRENT_FIRST:
                if self.valves.IMAGE_EDIT_LATEST_HISTORY_ONLY:
                    history_for_edit = history_images[-1:] if history_images else []
                else:
                    history_for_edit = history_images
                combined, reused_flags = self._apply_order_and_limit(
                    history_for_edit, current_images
                )
                # _apply_order_and_limit may still honor IMAGE_HISTORY_FIRST.
                # Force current image(s) to the front for edit requests.
                current_count = min(
                    len(current_images), self.valves.IMAGE_HISTORY_MAX_REFERENCES
                )
                remaining = max(
                    0, self.valves.IMAGE_HISTORY_MAX_REFERENCES - current_count
                )
                combined = (
                    current_images[:current_count] + history_for_edit[-remaining:]
                )
                reused_flags = [False] * min(current_count, len(combined))
                reused_flags += [True] * max(0, len(combined) - len(reused_flags))
            elif history_images:
                if self.valves.IMAGE_EDIT_LATEST_HISTORY_ONLY:
                    combined = history_images[-1:]
                    reused_flags = [True] * len(combined)
                else:
                    combined, reused_flags = self._apply_order_and_limit(
                        history_images, current_images
                    )
            else:
                combined, reused_flags = self._apply_order_and_limit(
                    history_images, current_images
                )

            self.log.info(
                "Image edit mode: prompt=%r current_images=%d history_images=%d sent=%d",
                prompt[:120],
                len(current_images),
                len(history_images),
                len(combined),
            )
        else:
            combined, reused_flags = self._apply_order_and_limit(
                history_images, current_images
            )

        if not prompt and not combined:
            raise ValueError("No prompt or images provided")
        if not prompt and combined:
            prompt = "Analyze and describe the provided images."

        # Build ordered stats aligned with combined list
        ordered_stats: List[Dict[str, Any]] = []
        if optimization_stats:
            # Build map from final_hash -> stat (first wins)
            hash_map: Dict[str, Dict[str, Any]] = {}
            for s in optimization_stats:
                fh = s.get("final_hash")
                if fh and fh not in hash_map:
                    hash_map[fh] = s
            for part in combined:
                try:
                    fh = hashlib.sha256(
                        part["inline_data"]["data"].encode()
                    ).hexdigest()
                    ordered_stats.append(hash_map.get(fh) or {})
                except Exception:
                    ordered_stats.append({})
        # Emit stats AFTER final ordering so labels match
        await self._emit_image_stats(
            ordered_stats,
            reused_flags,
            self.valves.IMAGE_HISTORY_MAX_REFERENCES,
            __event_emitter__,
        )

        # Emit mapping
        if combined:
            mapping = [
                {
                    "index": i + 1,
                    "label": (
                        f"Image {i + 1}" if self.valves.IMAGE_ADD_LABELS else str(i + 1)
                    ),
                    "reused": reused_flags[i],
                    "origin": "history" if reused_flags[i] else "current",
                }
                for i in range(len(combined))
            ]
            await self._emit_optional(
                __event_emitter__,
                {
                    "type": "status",
                    "data": {
                        "action": "image_reference_map",
                        "description": f"{len(combined)} image(s) included (limit {self.valves.IMAGE_HISTORY_MAX_REFERENCES}).",
                        "images": mapping,
                        "done": True,
                    },
                },
            )

        # Build parts
        parts: List[Dict[str, Any]] = []

        # For image generation models, prepend system instruction to the prompt
        # since system_instruction parameter may not be supported
        final_prompt = prompt
        if edit_mode and combined:
            final_prompt = (
                "Edit the provided source image according to the user's instruction. "
                "Preserve all visual details that the user did not ask to change. "
                "Return the edited image, not merely a textual description.\n\n"
                + prompt
            )
        if system_instruction and prompt:
            final_prompt = f"{system_instruction}\n\n{prompt}"
            self.log.debug(
                f"Prepended system instruction to prompt for image generation. "
                f"System instruction length: {len(system_instruction)}, "
                f"Original prompt length: {len(prompt)}, "
                f"Final prompt length: {len(final_prompt)}"
            )
        elif system_instruction and not prompt:
            final_prompt = system_instruction
            self.log.debug(
                f"Using system instruction as prompt for image generation "
                f"(length: {len(system_instruction)})"
            )

        if final_prompt:
            parts.append({"text": final_prompt})
        if self.valves.IMAGE_ADD_LABELS:
            for idx, part in enumerate(combined, start=1):
                parts.append({"text": f"[Image {idx}]"})
                parts.append(part)
        else:
            parts.extend(combined)

        self.log.debug(
            f"Image-capable payload: history={len(history_images)} current={len(current_images)} used={len(combined)} limit={self.valves.IMAGE_HISTORY_MAX_REFERENCES} history_first={self.valves.IMAGE_HISTORY_FIRST} prompt_len={len(final_prompt)}"
        )
        # Return None for system_instruction since we've incorporated it into the prompt
        return [{"role": "user", "parts": parts}], None

    def __init__(self):
        """Initializes the Pipe instance and configures the genai library."""
        self.valves = self.Valves()
        self._request_user = ContextVar("gemini_request_user", default=None)
        self.name: str = "Google Gemini: "

        # Setup logging
        self.log = logging.getLogger("google_ai.pipe")
        self.log.setLevel(SRC_LOG_LEVELS.get("OPENAI", logging.INFO))

        # Model cache
        self._model_cache: Optional[List[Dict[str, str]]] = None
        self._model_cache_time: float = 0

    def _get_client(self) -> genai.Client:
        """
        Validates API credentials and returns a genai.Client instance.
        """
        self._validate_api_key()

        if self.valves.USE_VERTEX_AI:
            self.log.debug(
                f"Initializing Vertex AI client (Project: {self.valves.VERTEX_PROJECT}, Location: {self.valves.VERTEX_LOCATION})"
            )
            return genai.Client(
                vertexai=True,
                project=self.valves.VERTEX_PROJECT,
                location=self.valves.VERTEX_LOCATION,
            )
        else:
            self.log.debug("Initializing Google Generative AI client with API Key")
            headers = {}
            if (
                self.valves.ENABLE_FORWARD_USER_INFO_HEADERS
                and hasattr(self, "user")
                and self.user
            ):

                def sanitize_header_value(value: Any, max_length: int = 255) -> str:
                    if value is None:
                        return ""
                    # Convert to string and remove all control characters
                    sanitized = re.sub(r"[\x00-\x1F\x7F]", "", str(value))
                    sanitized = (
                        sanitized.strip()
                        .encode("ascii", errors="replace")
                        .decode("ascii")
                    )
                    return (
                        sanitized[:max_length]
                        if len(sanitized) > max_length
                        else sanitized
                    )

                user_attrs = {
                    "X-OpenWebUI-User-Name": sanitize_header_value(
                        getattr(self.user, "name", None)
                    ),
                    "X-OpenWebUI-User-Id": sanitize_header_value(
                        getattr(self.user, "id", None)
                    ),
                    "X-OpenWebUI-User-Email": sanitize_header_value(
                        getattr(self.user, "email", None)
                    ),
                    "X-OpenWebUI-User-Role": sanitize_header_value(
                        getattr(self.user, "role", None)
                    ),
                }
                headers = {k: v for k, v in user_attrs.items() if v not in (None, "")}
            options = types.HttpOptions(
                api_version=self.valves.API_VERSION,
                base_url=self.valves.BASE_URL,
                headers=headers,
            )
            return genai.Client(
                api_key=EncryptedStr.decrypt(self.valves.GOOGLE_API_KEY),
                http_options=options,
            )

    def _validate_api_key(self) -> None:
        """
        Validates that the necessary Google API credentials are set.

        Raises:
            ValueError: If the required credentials are not set.
        """
        if self.valves.USE_VERTEX_AI:
            if not self.valves.VERTEX_PROJECT:
                self.log.error("USE_VERTEX_AI is true, but VERTEX_PROJECT is not set.")
                raise ValueError(
                    "VERTEX_PROJECT is not set. Please provide the Google Cloud project ID."
                )
            # For Vertex AI, location has a default, so project is the main thing to check.
            # Actual authentication will be handled by ADC or environment.
            self.log.debug(
                "Using Vertex AI. Ensure ADC or service account is configured."
            )
        else:
            if not self.valves.GOOGLE_API_KEY:
                self.log.error("GOOGLE_API_KEY is not set (and not using Vertex AI).")
                raise ValueError(
                    "GOOGLE_API_KEY is not set. Please provide the API key in the environment variables or valves."
                )
            self.log.debug("Using Google Generative AI API with API Key.")

    def strip_prefix(self, model_name: str) -> str:
        """
        Normalize an Open WebUI/Google model identifier without damaging
        version dots inside real Gemini model IDs.

        Examples:
          google_gemini.gemini-3.7-flash      -> gemini-3.7-flash
          google_gemini.gemini-3.7-flash-ocr  -> gemini-3.7-flash-ocr
          models/gemini-3.7-flash              -> gemini-3.7-flash
          publishers/google/models/gemini-3.7-flash -> gemini-3.7-flash
          gemini-3.7-flash                     -> gemini-3.7-flash

        This function is deliberately idempotent: calling it twice must
        return the same model ID.
        """
        value = str(model_name or "").strip()
        if not value:
            return value

        # Google resource paths: keep only the final model component.
        if "/" in value:
            value = value.rsplit("/", 1)[-1]

        # Already a real/virtual model ID. Do NOT treat the version dot
        # (e.g. "3.7") as an Open WebUI pipe separator.
        if value.startswith(("gemini-", "veo-")):
            return value

        # Open WebUI pipe IDs are typically "<pipe_id>.<base_model_id>".
        # Only strip the prefix if the suffix actually looks like a model ID.
        if "." in value:
            _prefix, candidate = value.split(".", 1)
            if candidate.startswith(("gemini-", "veo-")):
                return candidate

        return value

    def get_google_models(self, force_refresh: bool = False) -> List[Dict[str, str]]:
        """
        Retrieve available Google models suitable for content generation.
        Uses caching to reduce API calls.

        Args:
            force_refresh: Whether to force refreshing the model cache

        Returns:
            List of dictionaries containing model id and name.
        """
        # Check cache first
        current_time = time.time()
        if (
            not force_refresh
            and self._model_cache is not None
            and (current_time - self._model_cache_time) < self.valves.MODEL_CACHE_TTL
        ):
            self.log.debug("Using cached model list")
            return self._model_cache

        try:
            client = self._get_client()
            self.log.debug("Fetching models from Google API")
            try:
                models = list(client.models.list())
            finally:
                client.close()

            # Process additional models (models not returned by SDK but that we want to add)
            additional = self.valves.MODEL_ADDITIONAL
            if additional:
                self.log.debug(f"Processing additional models: {additional}")
                existing_model_names = {self.strip_prefix(m.name) for m in models}
                additional_ids = set(re.findall(r"[^,\s]+", additional))

                for model_id in additional_ids.difference(existing_model_names):
                    self.log.debug(f"Adding additional model '{model_id}'.")
                    models.append(types.Model(name=f"models/{model_id}"))

            available_models = []
            for model in models:
                actions = model.supported_actions
                model_id_stripped = self.strip_prefix(model.name)
                is_content_model = actions is None or "generateContent" in actions
                is_video_model = (
                    actions is not None and "generateVideos" in actions
                ) or model_id_stripped.startswith("veo-")
                if is_content_model or is_video_model:
                    model_id = model_id_stripped
                    model_name = model.display_name or model_id

                    # Check if model supports image generation
                    supports_image_generation = self._check_image_generation_support(
                        model_id
                    )
                    if supports_image_generation:
                        model_name += " 🎨"  # Add image generation indicator

                    # Check if model supports video generation
                    supports_video_generation = self._check_video_generation_support(
                        model_id
                    )
                    if supports_video_generation:
                        model_name += " 🎬"  # Add video generation indicator

                    available_models.append(
                        {
                            "id": model_id,
                            "name": model_name,
                            "image_generation": supports_image_generation,
                            "video_generation": supports_video_generation,
                        }
                    )

            model_map = {model["id"]: model for model in available_models}

            # Nano Banana 2 preview was shut down in June 2026. Do not expose
            # the retired preview ID even if a stale SDK/cache still lists it.
            model_map.pop("gemini-3.1-flash-image-preview", None)

            # Present the GA image model with the familiar product name.
            if "gemini-3.1-flash-image" in model_map:
                model_map["gemini-3.1-flash-image"]["name"] = "Nano Banana 2 🎨"

            # Add an Open WebUI-only virtual OCR model. It is never sent to the
            # Google API directly; _prepare_model_id() maps it to OCR_BASE_MODEL_ID.
            if self.valves.ENABLE_OCR_VIRTUAL_MODEL:
                ocr_virtual_id = self.strip_prefix(
                    self.valves.OCR_VIRTUAL_MODEL_ID or ""
                )
                if ocr_virtual_id:
                    model_map[ocr_virtual_id] = {
                        "id": ocr_virtual_id,
                        "name": self.valves.OCR_VIRTUAL_MODEL_NAME.replace(
                            "Gemini 3.7 Flash OCR", "Gemini 3.8 Flash OCR"
                        ),
                        "image_generation": False,
                        "video_generation": False,
                    }
                    self.log.debug(
                        "Added virtual OCR model '%s' -> '%s'",
                        ocr_virtual_id,
                        self.valves.OCR_BASE_MODEL_ID,
                    )

            # Apply MODEL_WHITELIST filter if configured (takes priority)
            whitelist = self.valves.MODEL_WHITELIST
            if whitelist:
                self.log.debug(f"Applying model whitelist: {whitelist}")
                whitelisted_ids = {
                    self.strip_prefix(v) for v in re.findall(r"[^,\s]+", whitelist)
                }
                # Filter to only include whitelisted models
                filtered_models = {
                    k: v for k, v in model_map.items() if k in whitelisted_ids
                }
                self.log.debug(f"After whitelist filter: {len(filtered_models)} models")
            else:
                # If no whitelist, filter to only include models starting with 'gemini-' or 'veo-'
                filtered_models = {
                    k: v
                    for k, v in model_map.items()
                    if k.startswith("gemini-") or k.startswith("veo-")
                }
                self.log.debug(f"After prefix filter: {len(filtered_models)} models")

            # Update cache
            self._model_cache = list(filtered_models.values())
            self._model_cache_time = current_time
            self.log.debug(f"Found {len(self._model_cache)} Gemini models")
            return self._model_cache

        except Exception as e:
            self.log.exception(f"Could not fetch models from Google: {str(e)}")
            # Return a specific error entry for the UI
            return [{"id": "error", "name": f"Could not fetch models: {str(e)}"}]

    def _check_image_generation_support(self, model_id: str) -> bool:
        """
        Check if a model supports image generation.

        Args:
            model_id: The model ID to check

        Returns:
            True if the model supports image generation, False otherwise
        """
        # Known image generation models (both Gemini 2.5 and Gemini 3)
        image_generation_models = [
            "gemini-2.5-flash-image",
            "gemini-2.5-flash-image-preview",
            "gemini-3-flash-image",
            "gemini-3-flash-image-preview",
            "gemini-3.1-flash-image",
            "gemini-3.1-flash-lite-image",
            "gemini-3-pro-image",
        ]

        # Check for exact matches or pattern matches
        for pattern in image_generation_models:
            if model_id == pattern or pattern in model_id:
                return True

        # Additional pattern checking for future models
        if "image" in model_id.lower() and (
            "generation" in model_id.lower() or "preview" in model_id.lower()
        ):
            return True

        return False

    def _is_gemini_3_family_model(self, model_id: str) -> bool:
        """Return True for Gemini 3.x model IDs, including Gemini 3.1+."""
        model_lower = model_id.lower()
        return model_lower.startswith("gemini-3-") or model_lower.startswith(
            "gemini-3."
        )

    @staticmethod
    def _gemini_version_tuple(model_id: str) -> Optional[Tuple[int, int]]:
        """Extract the major/minor Gemini version from IDs such as gemini-3.7-flash."""
        match = re.match(r"^gemini-(\d+)(?:\.(\d+))?(?:-|$)", model_id.lower())
        if not match:
            return None
        major = int(match.group(1))
        minor = int(match.group(2) or 0)
        return major, minor

    def _uses_modern_sampling_config(self, model_id: str) -> bool:
        """
        Return True for models that should not receive temperature/top_p/top_k.

        Google documents this breaking change for Gemini 3.6 Flash and all future
        Gemini releases, and also for Gemini 3.5 Flash-Lite. Keeping the check
        version-based makes Gemini 3.7+ work without another code update.
        """
        model_lower = model_id.lower()
        if model_lower.startswith("gemini-3.5-flash-lite"):
            return True
        version = self._gemini_version_tuple(model_lower)
        return bool(version and version >= (3, 6))

    def _is_gemini_3_image_model(self, model_id: str) -> bool:
        """Return True for Gemini 3.x image generation models."""
        return self._is_gemini_3_family_model(
            model_id
        ) and self._check_image_generation_support(model_id)

    def _check_image_config_support(self, model_id: str) -> bool:
        """
        Check if a model supports ImageConfig (aspect_ratio and image_size parameters).

        ImageConfig is only supported by Gemini 3 image generation models.
        Gemini 2.5 image models support image generation but not ImageConfig.

        Args:
            model_id: The model ID to check

        Returns:
            True if the model supports ImageConfig, False otherwise
        """
        return self._is_gemini_3_image_model(model_id)

    def _check_thinking_support(self, model_id: str) -> bool:
        """
        Check if a model supports the thinking feature.

        Args:
            model_id: The model ID to check

        Returns:
            True if the model supports thinking, False otherwise
        """
        # Models that do NOT support thinking
        non_thinking_models = [
            "gemini-2.5-flash-image-preview",
            "gemini-2.5-flash-image",
        ]

        # Check for exact matches
        for pattern in non_thinking_models:
            if model_id == pattern or pattern in model_id:
                return False

        # Gemini 3 image models support thinking and thinking-level controls.
        if self._is_gemini_3_image_model(model_id):
            return True

        # Older image generation preview models typically don't support thinking.
        if "image" in model_id.lower() and (
            "generation" in model_id.lower() or "preview" in model_id.lower()
        ):
            return False

        return model_id.startswith("gemini-2.5-") or self._is_gemini_3_family_model(
            model_id
        )

    def _check_thinking_level_support(self, model_id: str) -> bool:
        """
        Check if a model supports the thinking_level parameter.

        Gemini 3 models support thinking_level and should NOT use thinking_budget.
        Other models (like Gemini 2.5) use thinking_budget instead.

        Args:
            model_id: The model ID to check

        Returns:
            True if the model supports thinking_level, False otherwise
        """
        return self._is_gemini_3_family_model(model_id)

    def _get_supported_thinking_levels(self, model_id: str) -> List[str]:
        """Return known/compatible thinking levels for a Gemini 3 model.

        Google documents Gemini 3.7 Flash (and current 3.8 Flash) as supporting
        low/medium/high only; sending minimal to 3.7 returns an API error.
        Gemini 3.5/3.6 Flash support minimal/low/medium/high. Nano Banana 2
        (Gemini 3.1 Flash Image) supports minimal/high.
        """
        model_lower = model_id.lower()

        # Nano Banana 2 / Flash-Lite Image use a deliberately narrow control surface.
        if model_lower.startswith(
            "gemini-3.1-flash-lite-image"
        ) or model_lower.startswith("gemini-3.1-flash-image"):
            return ["minimal", "high"]

        version = self._gemini_version_tuple(model_lower)

        # Gemini 3.7+ Flash currently supports low/medium/high (no minimal).
        if (
            "flash" in model_lower
            and "image" not in model_lower
            and version is not None
            and version >= (3, 7)
        ):
            return ["low", "medium", "high"]

        # Gemini 3.5/3.6 Flash and Gemini 3 Flash preview expose all four levels.
        if (
            "flash" in model_lower
            and "image" not in model_lower
            and (
                model_lower.startswith("gemini-3-flash")
                or (version is not None and (3, 5) <= version < (3, 7))
            )
        ):
            return ["minimal", "low", "medium", "high"]

        if model_lower.startswith("gemini-3.1-pro"):
            return ["low", "medium", "high"]

        if model_lower.startswith("gemini-3-pro"):
            return ["low", "high"]

        if self._is_gemini_3_family_model(model_id):
            # Conservative fallback for unknown Gemini 3 variants.
            return ["low", "high"]

        return []

    def _coerce_thinking_level(
        self, requested_level: str, supported_levels: List[str]
    ) -> Optional[str]:
        """Map unsupported thinking levels to the closest supported level."""
        if not supported_levels:
            return None

        level_rank = {"minimal": 0, "low": 1, "medium": 2, "high": 3}
        requested_rank = level_rank.get(requested_level)
        if requested_rank is None:
            return None

        supported_ranks = sorted(
            (level_rank[level], level)
            for level in supported_levels
            if level in level_rank
        )
        if not supported_ranks:
            return None

        best_rank, best_level = min(
            supported_ranks,
            key=lambda item: (abs(item[0] - requested_rank), -item[0]),
        )
        _ = best_rank
        return best_level

    def _validate_thinking_level(self, level: str, model_id: str = "") -> Optional[str]:
        """
        Validate and normalize the thinking level value for the current model.

        Args:
            level: The thinking level string to validate
            model_id: The model ID used to determine supported levels

        Returns:
            Supported thinking level string or None if invalid/empty
        """
        if not level:
            return None

        normalized = level.strip().lower()
        valid_levels = ["minimal", "low", "medium", "high"]

        if normalized not in valid_levels:
            self.log.warning(
                f"Invalid thinking level '{level}'. Valid values are: {', '.join(valid_levels)}. "
                "Falling back to model default."
            )
            return None

        supported_levels = self._get_supported_thinking_levels(model_id)
        if not supported_levels or normalized in supported_levels:
            return normalized

        coerced_level = self._coerce_thinking_level(normalized, supported_levels)
        if coerced_level:
            self.log.warning(
                f"Thinking level '{level}' is not supported for model '{model_id}'. "
                f"Using '{coerced_level}' instead. Supported values: {', '.join(supported_levels)}."
            )
            return coerced_level

        self.log.warning(
            f"Thinking level '{level}' is not supported for model '{model_id}'. Supported values: {', '.join(supported_levels)}. "
            "Falling back to model default."
        )
        return None

    def _validate_thinking_budget(self, budget: int) -> int:
        """
        Validate and normalize the thinking budget value.

        Args:
            budget: The thinking budget integer to validate

        Returns:
            Validated budget: -1 for dynamic, 0 to disable, or 1-32768 for fixed limit
        """
        # -1 means dynamic thinking (let the model decide)
        if budget == -1:
            return -1

        # 0 means disable thinking
        if budget == 0:
            return 0

        # Validate positive range (1-32768)
        if budget > 0:
            if budget > 32768:
                self.log.warning(
                    f"Thinking budget {budget} exceeds maximum of 32768. Clamping to 32768."
                )
                return 32768
            return budget

        # Negative values (except -1) are invalid, treat as -1 (dynamic)
        self.log.warning(
            f"Invalid thinking budget {budget}. Only -1 (dynamic), 0 (disabled), or 1-32768 are valid. "
            "Falling back to dynamic thinking."
        )
        return -1

    def _validate_aspect_ratio(self, aspect_ratio: str) -> Optional[str]:
        """
        Validate and normalize the aspect ratio value.

        Args:
            aspect_ratio: The aspect ratio string to validate

        Returns:
            Validated aspect ratio string, None for "default", or "1:1" as fallback for invalid values
        """
        if not aspect_ratio or aspect_ratio == "default":
            self.log.debug("Using default aspect ratio (None)")
            return None

        normalized = aspect_ratio.strip()
        valid_ratios = [r for r in ASPECT_RATIO_OPTIONS if r != "default"]

        if normalized in valid_ratios:
            return normalized

        self.log.warning(
            f"Invalid aspect ratio '{aspect_ratio}'. Valid values are: {', '.join(valid_ratios)}. "
            "Using default '1:1'."
        )
        return "1:1"

    def _validate_resolution(self, resolution: str) -> Optional[str]:
        """
        Validate and normalize the resolution value.

        Args:
            resolution: The resolution string to validate

        Returns:
            Validated resolution string, None for "default", or "2K" as fallback for invalid values
        """
        if not resolution or resolution.lower() == "default":
            self.log.debug("Using default resolution (None)")
            return None

        normalized = resolution.strip().upper()
        valid_resolutions = [r for r in RESOLUTION_OPTIONS if r.lower() != "default"]

        if normalized in valid_resolutions:
            return normalized

        self.log.warning(
            f"Invalid resolution '{resolution}'. Valid values are: {', '.join(valid_resolutions)}. "
            "Using default '2K'."
        )
        return "2K"

    def _check_video_generation_support(self, model_id: str) -> bool:
        model_lower = model_id.lower()
        return model_lower.startswith("veo-") or (
            "veo" in model_lower and "generate" in model_lower
        )

    @staticmethod
    def _is_open_webui_image_tool(tool_name: str) -> bool:
        """Return True for Open WebUI's built-in image generation tools."""
        return tool_name in {"generate_image", "edit_image"}

    @staticmethod
    def _image_data_hash(image_data: Any) -> str:
        """Build a stable hash for generated image data across bytes/str inputs."""
        if isinstance(image_data, bytes):
            return hashlib.sha256(image_data).hexdigest()
        return hashlib.sha256(str(image_data).encode("utf-8")).hexdigest()

    async def _emit_generated_image_files(
        self,
        image_files: List[Dict[str, Any]],
        __event_emitter__: Optional[Callable],
    ) -> bool:
        """Persist generated images on the assistant message via Open WebUI files."""
        if not image_files or not __event_emitter__:
            return False

        try:
            await self._emit_optional(
                __event_emitter__,
                {
                    "type": "files",
                    "data": {"files": image_files},
                },
            )
            return True
        except Exception as emit_error:
            self.log.warning(f"Failed to emit generated image files: {emit_error}")
            return False

    async def _emit_generated_video_files(
        self,
        video_files: List[Dict[str, Any]],
        __event_emitter__: Optional[Callable],
    ) -> bool:
        """Persist generated videos on the assistant message via Open WebUI files."""
        if not video_files or not __event_emitter__:
            return False

        try:
            await self._emit_optional(
                __event_emitter__,
                {
                    "type": "files",
                    "data": {"files": video_files},
                },
            )
            return True
        except Exception as emit_error:
            self.log.warning(f"Failed to emit generated video files: {emit_error}")
            return False

    @staticmethod
    def _build_generated_image_file(
        content_url: str,
        mime_type: str,
        name: str = "Generated Image",
    ) -> Dict[str, Any]:
        """Build a chat image entry matching Open WebUI's image attachment shape."""
        return {
            "type": "image",
            "url": content_url,
            "content_type": mime_type,
            "name": name,
            "meta": {"content_type": mime_type},
        }

    @staticmethod
    def _build_generated_video_file(
        file_id: str,
        content_url: str,
        filename: str,
        mime_type: str,
        size: int,
    ) -> Dict[str, Any]:
        """Build a chat file entry that matches Open WebUI's file attachment shape."""
        return {
            "id": file_id,
            "type": "file",
            "url": content_url,
            "name": filename,
            "filename": filename,
            "size": size,
            "content_type": mime_type,
            "meta": {
                "content_type": mime_type,
                "size": size,
            },
        }

    def _check_veo_3_1_support(self, model_id: str) -> bool:
        """Check if a Veo model is version 3.1 (supports reference images, interpolation, 4k, extension)."""
        return "veo-3.1" in model_id.lower()

    def _get_veo_model_capabilities(self, model_id: str) -> Dict[str, Any]:
        """Return per-model feature support matrix based on official Google Veo documentation."""
        model_lower = model_id.lower()
        is_fast = "fast" in model_lower

        # `enhance_prompt` is no longer accepted by any current Veo model in the
        # Gemini API (it was a legacy Vertex-only parameter and the public Veo
        # API parameter table no longer lists it). Sending it now produces
        # `400 INVALID_ARGUMENT: enhancePrompt isn't supported by this model`.
        if "veo-3.1" in model_lower:
            return {
                "version": "3.1",
                "is_fast": is_fast,
                "supports_enhance_prompt": False,
                "supports_resolution": True,
                "valid_resolutions": ["720p", "1080p", "4k"],
                "valid_durations": [4, 6, 8],
                "max_videos": 1,
                "supports_reference_images": True,
                "supports_last_frame": True,
                "supports_extension": True,
            }
        if "veo-3" in model_lower:
            return {
                "version": "3",
                "is_fast": is_fast,
                "supports_enhance_prompt": False,
                "supports_resolution": True,
                "valid_resolutions": ["720p", "1080p"],
                "valid_durations": [8],
                "max_videos": 1,
                "supports_reference_images": False,
                "supports_last_frame": True,
                "supports_extension": False,
            }
        if "veo-2" in model_lower:
            return {
                "version": "2",
                "is_fast": False,
                "supports_enhance_prompt": False,
                "supports_resolution": False,
                "valid_resolutions": [],
                "valid_durations": [5, 6, 8],
                "max_videos": 2,
                "supports_reference_images": False,
                "supports_last_frame": True,
                "supports_extension": False,
            }
        return {
            "version": "unknown",
            "is_fast": is_fast,
            "supports_enhance_prompt": False,
            "supports_resolution": False,
            "valid_resolutions": [],
            "valid_durations": [8],
            "max_videos": 1,
            "supports_reference_images": False,
            "supports_last_frame": False,
            "supports_extension": False,
        }

    def _validate_video_aspect_ratio(self, aspect_ratio: str) -> Optional[str]:
        if not aspect_ratio or aspect_ratio == "default":
            return None
        normalized = aspect_ratio.strip()
        valid = [r for r in VIDEO_ASPECT_RATIO_OPTIONS if r != "default"]
        if normalized in valid:
            return normalized
        self.log.warning(
            f"Invalid video aspect ratio '{aspect_ratio}'. Valid: {', '.join(valid)}. Using default."
        )
        return None

    def _validate_video_resolution(self, resolution: str) -> Optional[str]:
        if not resolution or resolution.lower() == "default":
            return None
        normalized = resolution.strip().lower()
        valid = [r for r in VIDEO_RESOLUTION_OPTIONS if r.lower() != "default"]
        if normalized in valid:
            return normalized
        self.log.warning(
            f"Invalid video resolution '{resolution}'. Valid: {', '.join(valid)}. Using default."
        )
        return None

    def _validate_video_duration(self, duration: str) -> Optional[int]:
        if not duration or duration.lower() == "default":
            return None
        valid = {int(d) for d in VIDEO_DURATION_OPTIONS if d != "default"}
        try:
            val = int(duration)
            if val in valid:
                return val
        except (ValueError, TypeError):
            pass
        self.log.warning(
            f"Invalid video duration '{duration}'. Valid: {', '.join(str(v) for v in sorted(valid))}. Using default."
        )
        return None

    def _build_video_generation_config(
        self,
        body: Dict[str, Any],
        __user__: Optional[dict] = None,
        model_id: str = "",
    ) -> types.GenerateVideosConfig:
        """Build GenerateVideosConfig from valves, user overrides, and model capabilities."""
        caps = self._get_veo_model_capabilities(model_id)

        user_ar = self._get_user_valve_value(__user__, "VIDEO_GENERATION_ASPECT_RATIO")
        aspect_ratio = self._validate_video_aspect_ratio(
            body.get(
                "aspect_ratio", user_ar or self.valves.VIDEO_GENERATION_ASPECT_RATIO
            )
        )

        user_res = self._get_user_valve_value(__user__, "VIDEO_GENERATION_RESOLUTION")
        resolution = self._validate_video_resolution(
            body.get("resolution", user_res or self.valves.VIDEO_GENERATION_RESOLUTION)
        )

        user_dur = self._get_user_valve_value(__user__, "VIDEO_GENERATION_DURATION")
        duration_seconds = self._validate_video_duration(
            body.get("duration", user_dur or self.valves.VIDEO_GENERATION_DURATION)
        )

        negative_prompt = (
            body.get("negative_prompt", self.valves.VIDEO_GENERATION_NEGATIVE_PROMPT)
            or None
        )

        person_generation_raw = body.get(
            "person_generation", self.valves.VIDEO_GENERATION_PERSON_GENERATION
        )
        person_generation = None
        if person_generation_raw and person_generation_raw != "default":
            valid_person_values = [
                v for v in VIDEO_PERSON_GENERATION_OPTIONS if v != "default"
            ]
            if person_generation_raw in valid_person_values:
                person_generation = person_generation_raw
            else:
                self.log.warning(
                    f"Invalid person_generation '{person_generation_raw}'. "
                    f"Valid: {', '.join(valid_person_values)}. Ignoring."
                )

        enhance_prompt = body.get(
            "enhance_prompt", self.valves.VIDEO_GENERATION_ENHANCE_PROMPT
        )

        number_of_videos_raw = body.get("number_of_videos", 1)
        try:
            number_of_videos = int(number_of_videos_raw)
        except (ValueError, TypeError):
            self.log.warning(
                f"Invalid number_of_videos '{number_of_videos_raw}', defaulting to 1"
            )
            number_of_videos = 1

        config_params: Dict[str, Any] = {
            "number_of_videos": min(max(number_of_videos, 1), caps["max_videos"]),
        }

        # enhance_prompt: not supported by Fast models or Veo 2
        if caps["supports_enhance_prompt"] and enhance_prompt:
            config_params["enhance_prompt"] = enhance_prompt

        if aspect_ratio:
            config_params["aspect_ratio"] = aspect_ratio

        # Resolution: not supported by Veo 2; model-specific valid values
        if resolution and caps["supports_resolution"]:
            if resolution in caps["valid_resolutions"]:
                config_params["resolution"] = resolution
            else:
                self.log.warning(
                    f"Resolution '{resolution}' not supported by {model_id}. "
                    f"Valid: {', '.join(caps['valid_resolutions'])}. Using default."
                )

        # Duration: model-specific valid values
        if duration_seconds:
            if duration_seconds in caps["valid_durations"]:
                config_params["duration_seconds"] = duration_seconds
            else:
                self.log.warning(
                    f"Duration {duration_seconds}s not supported by {model_id}. "
                    f"Valid: {', '.join(str(d) for d in caps['valid_durations'])}. Using default."
                )

        if negative_prompt:
            config_params["negative_prompt"] = negative_prompt
        if person_generation:
            config_params["person_generation"] = person_generation

        self.log.debug(f"Video generation config for {model_id}: {config_params}")
        return types.GenerateVideosConfig(**config_params)

    def pipes(self) -> List[Dict[str, str]]:
        models = [dict(model) for model in self.get_google_models()]
        if any(model.get("id") == "error" for model in models):
            return models
        image_id = self._prepare_model_id(self.valves.AUTO_IMAGE_MODEL)
        whitelist = {
            self.strip_prefix(v)
            for v in re.findall(r"[^,\s]+", self.valves.MODEL_WHITELIST or "")
        }
        if (
            self.valves.FORCE_NANO_BANANA_2_VISIBLE
            and (not whitelist or image_id in whitelist)
            and self._check_image_generation_support(image_id)
            and not any(m.get("id") == image_id for m in models)
        ):
            models.append(
                {
                    "id": image_id,
                    "name": image_id + " 🎨",
                    "image_generation": True,
                    "video_generation": False,
                }
            )
        return models

    def _is_ocr_virtual_model(self, model_id: str) -> bool:
        """Return True when an Open WebUI request selected the virtual OCR model."""
        if not self.valves.ENABLE_OCR_VIRTUAL_MODEL or not model_id:
            return False

        requested = self.strip_prefix(str(model_id))
        virtual_id = self.strip_prefix((self.valves.OCR_VIRTUAL_MODEL_ID or "").strip())
        return requested in {
            virtual_id,
            "gemini-3.7-flash-ocr",
            "gemini-3.8-flash-ocr",
        } and bool(requested)

    def _apply_ocr_system_prompt(
        self, system_instruction: Optional[str]
    ) -> Optional[str]:
        """Prepend OCR-specific visual transcription rules to the chat system prompt."""
        ocr_prompt = (self.valves.OCR_SYSTEM_PROMPT or "").strip()
        existing = (system_instruction or "").strip()
        if ocr_prompt and existing:
            return f"{ocr_prompt}\n\n{existing}"
        return ocr_prompt or existing or None

    @staticmethod
    def _normalize_ocr_media_resolution(value: str) -> Optional[str]:
        normalized = (value or "").strip().lower()
        mapping = {
            "low": "MEDIA_RESOLUTION_LOW",
            "medium": "MEDIA_RESOLUTION_MEDIUM",
            "high": "MEDIA_RESOLUTION_HIGH",
        }
        return mapping.get(normalized)

    def _prepare_model_id(self, model_id: str) -> str:
        """
        Prepare and validate the model ID for use with the API.

        Args:
            model_id: The original model ID from the user

        Returns:
            Properly formatted model ID

        Raises:
            ValueError: If the model ID is invalid or unsupported
        """
        original_model_id = model_id
        is_ocr_alias = self._is_ocr_virtual_model(original_model_id)
        model_id = self.strip_prefix(model_id)

        # Backward compatibility for old chats / saved model selections.
        # The Nano Banana 2 preview endpoint is retired; transparently map it
        # to the GA model instead of allowing a Google 404.
        retired_image_aliases = {
            "gemini-3.1-flash-image-preview": "gemini-3.1-flash-image",
            "gemini-nano-banana-2": "gemini-3.1-flash-image",
            "nano-banana-2": "gemini-3.1-flash-image",
        }
        if model_id in retired_image_aliases:
            mapped = retired_image_aliases[model_id]
            self.log.info(
                "Mapped retired/virtual image model '%s' to GA model '%s'",
                model_id,
                mapped,
            )
            return mapped

        if is_ocr_alias:
            base_model_id = self.strip_prefix(
                (self.valves.OCR_BASE_MODEL_ID or "").strip()
            )
            # Upgrade the old persisted OCR default as well as fresh installs.
            if base_model_id == "gemini-3.7-flash":
                base_model_id = "gemini-3.8-flash"
            if not base_model_id.startswith("gemini-"):
                raise ValueError(
                    "OCR_BASE_MODEL_ID must be a Gemini model ID "
                    f"(got '{self.valves.OCR_BASE_MODEL_ID}')"
                )
            self.log.info(
                "Virtual OCR model '%s' mapped to REAL Gemini API model '%s'",
                self.strip_prefix(original_model_id),
                base_model_id,
            )
            return base_model_id

        valid_prefixes = ("gemini-", "veo-")

        # If the model ID doesn't match a known prefix, try to find it by name
        if not model_id.startswith(valid_prefixes):
            models_list = self.get_google_models()
            found_model = next(
                (m["id"] for m in models_list if m["name"] == original_model_id), None
            )
            if found_model and found_model.startswith(valid_prefixes):
                model_id = found_model
                self.log.debug(
                    f"Mapped model name '{original_model_id}' to model ID '{model_id}'"
                )
            else:
                if not model_id.startswith(valid_prefixes):
                    self.log.error(
                        f"Invalid or unsupported model ID: '{original_model_id}'"
                    )
                    raise ValueError(
                        f"Invalid or unsupported Google model ID or name: '{original_model_id}'"
                    )

        return model_id

    # ------------------------------------------------------------------
    # Bypass backend RAG (inspired by the Gemini Manifold google_genai pipe)
    #
    # Open WebUI's middleware runs its RAG pipeline before the pipe is
    # invoked and injects the retrieved chunks into the prompt using the
    # RAG template (a "### Task: ... <context>...</context> <user_query>...
    # </user_query>" block). When BYPASS_BACKEND_RAG is enabled, this pipe:
    #   1. Strips that injected RAG context from the messages, restoring the
    #      original user query.
    #   2. Loads the original attached files from Open WebUI storage and
    #      attaches them natively (inline bytes or Google Files API) to the
    #      last user turn, so Gemini reads the full documents itself.
    # ------------------------------------------------------------------

    # MIME types natively supported by Gemini for document understanding
    # (any "text/*" type is also accepted).
    GEMINI_NATIVE_DOC_MIME_TYPES = {
        "application/pdf",
        "application/json",
        "application/rtf",
        "application/xml",
        "application/x-javascript",
        "application/x-python-code",
        "application/x-typescript",
        "application/javascript",
        "application/yaml",
        "application/x-yaml",
    }

    _RAG_USER_QUERY_RE = re.compile(r"<user_query>\s*(.*?)\s*</user_query>", re.DOTALL)
    _RAG_CONTEXT_BLOCK_RE = re.compile(r"<context>.*?</context>\s*", re.DOTALL)
    _RAG_TASK_HEADER_RE = re.compile(r"### Task:.*?(?=<context>)", re.DOTALL)

    def _strip_rag_template_from_text(self, text: str) -> str:
        """Remove the backend-injected RAG template from a text blob and
        restore the original user query. Returns the text unchanged when no
        RAG template markers are found."""
        if "<context>" not in text:
            return text

        original = text

        # The default RAG template ends with <user_query>{query}</user_query>.
        # Anything after the last closing tag is content that was appended to
        # the message after injection; keep it if present.
        query_match = None
        for query_match in self._RAG_USER_QUERY_RE.finditer(text):
            pass  # keep last match

        if query_match:
            trailing = text[query_match.end() :].strip()
            restored = trailing if trailing else query_match.group(1)
        else:
            # Non-default template: best effort, drop the context block and
            # the default task/guidelines header.
            restored = self._RAG_CONTEXT_BLOCK_RE.sub("", text)
            restored = self._RAG_TASK_HEADER_RE.sub("", restored)
            restored = restored.strip()

        if restored != original:
            self.log.debug(
                "BYPASS_BACKEND_RAG: stripped injected RAG context "
                f"({len(original)} -> {len(restored)} chars)"
            )
        return restored

    def _strip_backend_rag_context(
        self, messages: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Return a copy of `messages` with the backend-injected RAG template
        removed from string contents and from text items of multimodal
        contents (system and user roles)."""
        cleaned: List[Dict[str, Any]] = []
        for message in messages:
            content = message.get("content")
            if isinstance(content, str) and "<context>" in content:
                message = {
                    **message,
                    "content": self._strip_rag_template_from_text(content),
                }
            elif isinstance(content, list):
                new_items = []
                changed = False
                for item in content:
                    if (
                        isinstance(item, dict)
                        and item.get("type") == "text"
                        and "<context>" in (item.get("text") or "")
                    ):
                        new_items.append(
                            {
                                **item,
                                "text": self._strip_rag_template_from_text(
                                    item["text"]
                                ),
                            }
                        )
                        changed = True
                    else:
                        new_items.append(item)
                if changed:
                    message = {**message, "content": new_items}
            cleaned.append(message)
        return cleaned

    def _collect_metadata_files(
        self, __metadata__: Optional[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Collect file attachments (and files inside knowledge collections)
        from request metadata. Includes files stashed by the companion
        "Google Gemini RAG Bypass" filter under `_google_gemini_bypassed_files`.
        Returns a deduplicated list of {"id", "name", "content_type"} dicts."""
        metadata = __metadata__ or {}
        raw_files = list(metadata.get("files") or []) + list(
            metadata.get("_google_gemini_bypassed_files") or []
        )
        collected: List[Dict[str, Any]] = []
        seen: set = set()

        def _add(entry: Dict[str, Any]) -> None:
            file_info = entry.get("file") or {}
            fid = entry.get("id") or file_info.get("id")
            if not fid or fid in seen:
                return
            seen.add(fid)
            meta = file_info.get("meta") or entry.get("meta") or {}
            collected.append(
                {
                    "id": fid,
                    "name": entry.get("name")
                    or file_info.get("filename")
                    or entry.get("filename")
                    or fid,
                    "content_type": (
                        entry.get("content_type")
                        or file_info.get("content_type")
                        or meta.get("content_type")
                    ),
                }
            )

        for entry in raw_files:
            if not isinstance(entry, dict):
                continue
            entry_type = entry.get("type", "file")
            if entry_type in {"file", "image", "image_file"}:
                _add(entry)
            elif entry_type == "collection":
                for inner in entry.get("files") or []:
                    if isinstance(inner, dict):
                        _add(inner)
        return collected

    async def _load_owui_file(self, file_id: str) -> Tuple[Optional[bytes], Any]:
        """Load raw bytes and the file record for an Open WebUI file ID.
        Returns (bytes | None, file_obj | None)."""
        try:
            from open_webui.models.files import Files
            from open_webui.storage.provider import Storage

            file_obj = await Files.get_file_by_id(file_id)
            if not file_obj:
                self.log.warning(f"BYPASS_BACKEND_RAG: file {file_id} not found")
                return None, None
            data: Optional[bytes] = None
            try:
                file_path = await asyncio.to_thread(Storage.get_file, file_obj.path)
                async with aiofiles.open(file_path, "rb") as fp:
                    data = await fp.read()
            except Exception as read_error:
                self.log.warning(
                    f"BYPASS_BACKEND_RAG: could not read bytes for file "
                    f"{file_id}: {read_error}"
                )
            return data, file_obj
        except Exception as e:
            self.log.warning(f"BYPASS_BACKEND_RAG: failed to load file {file_id}: {e}")
            return None, None

    @staticmethod
    def _is_hwpx_document(name: str, mime_type: str) -> bool:
        """Return True for HWPX using extension + common MIME aliases."""
        lower_name = str(name or "").lower().strip()
        lower_mime = str(mime_type or "").lower().split(";", 1)[0].strip()
        return lower_name.endswith(".hwpx") or lower_mime in {
            "application/hwp+zip",
            "application/vnd.hancom.hwpx",
            "application/x-hwpx",
        }

    @staticmethod
    def _hwpx_local_name(tag: str) -> str:
        return str(tag or "").rsplit("}", 1)[-1].lower()

    @staticmethod
    def _validate_hwpx_archive(zf):
        entries = zf.infolist()
        if len(entries) > 4096 or sum(i.file_size for i in entries) > 128 * 1024 * 1024:
            raise ValueError("HWPX archive exceeds extraction limits")
        if any(i.file_size > 32 * 1024 * 1024 for i in entries):
            raise ValueError("HWPX archive member exceeds 32 MiB")

    def _extract_hwpx_text(self, data: bytes) -> Tuple[str, Dict[str, Any]]:
        """Extract HWPX body text directly from the ZIP/XML package.

        HWPX is a ZIP-based XML format. We read Contents/section*.xml in numeric
        order and preserve paragraph/table-cell order as plain text. No third-party
        package is required.
        """
        stats: Dict[str, Any] = {
            "sections": 0,
            "text_chars": 0,
            "used_preview_text": False,
        }
        if not data:
            return "", stats

        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            self._validate_hwpx_archive(zf)
            names = zf.namelist()

            section_names = [
                n for n in names if re.match(r"(?i)^Contents/section\d+\.xml$", n)
            ]

            def section_key(value: str) -> int:
                match = re.search(r"(\d+)(?=\.xml$)", value)
                return int(match.group(1)) if match else 10**9

            section_names.sort(key=section_key)
            stats["sections"] = len(section_names)

            all_chunks: List[str] = []

            for section_name in section_names:
                try:
                    raw_xml = zf.read(section_name)
                    section_chunks: List[str] = []

                    def walk(elem):
                        local = self._hwpx_local_name(elem.tag)
                        if local == "t":
                            section_chunks.append(elem.text or "")
                        elif local == "tab":
                            section_chunks.append("\t")
                        elif local in {"linebreak", "line-break", "br"}:
                            section_chunks.append("\n")
                        for child in elem:
                            walk(child)
                            if local == "t":
                                section_chunks.append(child.tail or "")
                        if local == "p":
                            section_chunks.append("\n")

                    walk(ET.fromstring(raw_xml))

                    section_text = "".join(section_chunks)
                    if section_text.strip():
                        all_chunks.append(section_text)
                except Exception as section_error:
                    self.log.warning(
                        "HWPX: failed to parse %s: %s",
                        section_name,
                        section_error,
                    )

            text = "\n".join(all_chunks)

            # If section XML contains no useful text, Preview/PrvText.txt is a
            # cheap compatibility fallback. Some image-centric HWPX files place
            # only a short description there.
            if not text.strip():
                preview_name = next(
                    (n for n in names if n.lower() == "preview/prvtext.txt"),
                    None,
                )
                if preview_name:
                    try:
                        preview_bytes = zf.read(preview_name)
                        text = preview_bytes.decode("utf-8", errors="replace")
                        stats["used_preview_text"] = True
                    except Exception:
                        pass

        # Normalize only layout noise. Do not rewrite document wording.
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        text = re.sub(r"[ \t]+\n", "\n", text)
        text = re.sub(r"\n{4,}", "\n\n\n", text).strip()

        max_chars = int(self.valves.HWPX_MAX_TEXT_CHARS)
        if len(text) > max_chars:
            text = (
                text[:max_chars].rstrip()
                + "\n\n[HWPX text truncated by HWPX_MAX_TEXT_CHARS]"
            )
            stats["truncated"] = True

        stats["text_chars"] = len(text)
        return text, stats

    def _extract_hwpx_images(
        self, data: bytes
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """Extract supported BinData images from an HWPX package."""
        parts: List[Dict[str, Any]] = []
        stats: Dict[str, Any] = {
            "images_found": 0,
            "images_attached": 0,
            "preview_attached": False,
        }
        if (
            not data
            or not self.valves.HWPX_INCLUDE_EMBEDDED_IMAGES
            or self.valves.HWPX_MAX_EMBEDDED_IMAGES <= 0
        ):
            return parts, stats

        mime_by_ext = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".webp": "image/webp",
            ".gif": "image/gif",
            ".bmp": "image/bmp",
        }
        max_image_bytes = max(1, int(self.valves.HWPX_MAX_IMAGE_MB)) * 1024 * 1024
        max_images = int(self.valves.HWPX_MAX_EMBEDDED_IMAGES)

        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            self._validate_hwpx_archive(zf)
            names = zf.namelist()
            image_names = [
                n
                for n in names
                if n.lower().startswith("bindata/")
                and Path(n).suffix.lower() in mime_by_ext
            ]
            image_names.sort()
            stats["images_found"] = len(image_names)

            for image_name in image_names:
                if stats["images_attached"] >= max_images:
                    break
                try:
                    info = zf.getinfo(image_name)
                    if info.file_size > max_image_bytes:
                        self.log.info(
                            "HWPX: skipping large embedded image %s (%.2f MB)",
                            image_name,
                            info.file_size / (1024 * 1024),
                        )
                        continue
                    raw = zf.read(image_name)
                    mime = mime_by_ext[Path(image_name).suffix.lower()]
                    if mime in {"image/gif", "image/bmp"}:
                        with Image.open(io.BytesIO(raw)) as embedded:
                            converted = io.BytesIO()
                            embedded.convert("RGB").save(converted, format="PNG")
                            raw = converted.getvalue()
                        mime = "image/png"
                        if len(raw) > max_image_bytes:
                            continue
                    parts.append(
                        {
                            "text": (
                                f"[Embedded image from HWPX: {Path(image_name).name}]"
                            )
                        }
                    )
                    parts.append(
                        {
                            "inline_data": {
                                "mime_type": mime,
                                "data": base64.b64encode(raw).decode("utf-8"),
                            }
                        }
                    )
                    stats["images_attached"] += 1
                except Exception as image_error:
                    self.log.warning(
                        "HWPX: failed to extract embedded image %s: %s",
                        image_name,
                        image_error,
                    )

        return parts, stats

    def _extract_hwpx_preview_image(self, data: bytes) -> Optional[Dict[str, Any]]:
        """Return Preview/PrvImage.* as an inline image when available."""
        if not data or not self.valves.HWPX_INCLUDE_PREVIEW_IF_EMPTY:
            return None

        mime_by_ext = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".webp": "image/webp",
        }

        try:
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                self._validate_hwpx_archive(zf)
                candidates = [
                    n
                    for n in zf.namelist()
                    if n.lower().startswith("preview/prvimage")
                    and Path(n).suffix.lower() in mime_by_ext
                ]
                if not candidates:
                    return None
                name = sorted(candidates)[0]
                raw = zf.read(name)
                if len(raw) > int(self.valves.HWPX_MAX_IMAGE_MB) * 1024 * 1024:
                    return None
                return {
                    "inline_data": {
                        "mime_type": mime_by_ext[Path(name).suffix.lower()],
                        "data": base64.b64encode(raw).decode("utf-8"),
                    }
                }
        except Exception as preview_error:
            self.log.debug("HWPX preview extraction failed: %s", preview_error)
            return None

    async def _build_hwpx_document_parts(
        self,
        *,
        data: Optional[bytes],
        name: str,
        mime_type: str,
    ) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        """Build Gemini text/image parts for .hwpx without sending HWPX bytes natively."""
        if (
            not self.valves.ENABLE_HWPX_SUPPORT
            or not self._is_hwpx_document(name, mime_type)
            or not data
        ):
            return [], None

        try:
            text, text_stats = self._extract_hwpx_text(data)
            image_parts, image_stats = self._extract_hwpx_images(data)

            parts: List[Dict[str, Any]] = []

            if text:
                parts.append(
                    {
                        "text": (
                            f'<file name="{name}" format="HWPX" '
                            f'extraction="direct-xml">\n{text}\n</file>'
                        )
                    }
                )

            if image_parts:
                parts.extend(image_parts)

            if not text and not image_parts:
                preview = self._extract_hwpx_preview_image(data)
                if preview:
                    parts.append(
                        {
                            "text": (
                                f"[HWPX preview image for visually reading '{name}']"
                            )
                        }
                    )
                    parts.append(preview)
                    image_stats["preview_attached"] = True

            if parts:
                self.log.info(
                    "HWPX: attached '%s' via direct extraction "
                    "(sections=%s, text_chars=%s, embedded_images=%s, preview=%s)",
                    name,
                    text_stats.get("sections"),
                    text_stats.get("text_chars"),
                    image_stats.get("images_attached"),
                    image_stats.get("preview_attached"),
                )
                return parts, "hwpx-direct"

        except zipfile.BadZipFile:
            self.log.warning("HWPX: '%s' is not a valid ZIP/HWPX package", name)
        except Exception as hwpx_error:
            self.log.warning("HWPX extraction failed for '%s': %s", name, hwpx_error)

        return [], None

    def _is_gemini_supported_doc_mime(self, mime_type: str) -> bool:
        return mime_type.startswith("text/") or (
            mime_type in self.GEMINI_NATIVE_DOC_MIME_TYPES
        )

    async def _upload_to_google_files_api(
        self, data: bytes, mime_type: str, display_name: str
    ) -> Optional[Dict[str, Any]]:
        """Upload a large file via the Google Files API and wait until it is
        ACTIVE. Returns a file_data part dict or None on failure."""
        try:
            client = self._get_client()
            uploaded = await client.aio.files.upload(
                file=io.BytesIO(data),
                config={"mime_type": mime_type, "display_name": display_name},
            )
            # Wait for processing to finish (max ~60s).
            for _ in range(30):
                state = str(getattr(uploaded, "state", "") or "")
                if "ACTIVE" in state:
                    return {
                        "file_data": {
                            "file_uri": uploaded.uri,
                            "mime_type": mime_type,
                        }
                    }
                if "FAILED" in state:
                    self.log.warning(
                        f"BYPASS_BACKEND_RAG: Files API processing failed for "
                        f"'{display_name}'"
                    )
                    return None
                await asyncio.sleep(2)
                uploaded = await client.aio.files.get(name=uploaded.name)
            self.log.warning(
                f"BYPASS_BACKEND_RAG: Files API upload of '{display_name}' timed out"
            )
            return None
        except Exception as e:
            self.log.warning(
                f"BYPASS_BACKEND_RAG: Files API upload failed for "
                f"'{display_name}': {e}"
            )
            return None

    async def _build_rag_bypass_parts(
        self, metadata_files: List[Dict[str, Any]], *, require_full_pdf: bool = False
    ) -> Tuple[List[Dict[str, Any]], List[str]]:
        """Convert Open WebUI file attachments into native Gemini parts.

        Preference order per file:
          1. Inline bytes (supported MIME type, size within limit)
          2. Google Files API (supported MIME type, too large, non-Vertex)
          3. Backend-extracted text from the file record (fallback)
        Returns (parts, attached file names)."""
        parts: List[Dict[str, Any]] = []
        attached_names: List[str] = []
        max_inline_bytes = max(1, self.valves.RAG_BYPASS_MAX_INLINE_MB) * 1024 * 1024

        for entry in metadata_files:
            name = entry["name"]
            data, file_obj = await self._load_owui_file(entry["id"])
            mime_type = (
                (
                    entry.get("content_type")
                    or (getattr(file_obj, "meta", None) or {}).get("content_type")
                    or "application/octet-stream"
                )
                .split(";")[0]
                .strip()
            )

            if name.lower().endswith(".pdf"):
                mime_type = "application/pdf"

            # HWPX is unpacked locally into XML text + embedded images.
            # Binary .hwp is intentionally not specially handled here.
            if self.valves.ENABLE_HWPX_SUPPORT and self._is_hwpx_document(
                name, mime_type
            ):
                hwpx_parts, hwpx_method = await self._build_hwpx_document_parts(
                    data=data,
                    name=name,
                    mime_type=mime_type,
                )
                if hwpx_parts:
                    parts.extend(hwpx_parts)
                    attached_names.append(name)
                    self.log.info(
                        "BYPASS_BACKEND_RAG: HWPX '%s' prepared via %s",
                        name,
                        hwpx_method,
                    )
                    continue

            part: Optional[Dict[str, Any]] = None
            if data and (
                mime_type.startswith("text/")
                or mime_type in self.GEMINI_NATIVE_DOC_MIME_TYPES - {"application/pdf"}
            ):
                try:
                    decoded = data.decode("utf-8-sig")
                    part = {"text": f'<file name="{name}">\n{decoded}\n</file>'}
                except UnicodeDecodeError:
                    pass  # Fall back to backend-extracted text for other encodings.
            if data and mime_type.startswith("image/"):
                url = f"data:{mime_type};base64," + base64.b64encode(data).decode(
                    "ascii"
                )
                image_parts = self._process_multimodal_content(
                    [{"type": "image_url", "image_url": {"url": url}}]
                )
                if image_parts and "inline_data" in image_parts[0]:
                    part = image_parts[0]
            if data and mime_type == "application/pdf":
                if len(data) <= max_inline_bytes:
                    part = {
                        "inline_data": {
                            "mime_type": mime_type,
                            "data": base64.b64encode(data).decode("utf-8"),
                        }
                    }
                elif not self.valves.USE_VERTEX_AI:
                    self.log.info(
                        f"BYPASS_BACKEND_RAG: '{name}' exceeds inline limit, "
                        "uploading via Google Files API"
                    )
                    part = await self._upload_to_google_files_api(data, mime_type, name)

            if part is None and require_full_pdf and mime_type == "application/pdf":
                raise ValueError(
                    f"OCR PDF 원문 전달 실패: {name}. 파일 접근 또는 업로드 상태를 확인하세요. "
                    "추출 텍스트만으로 전체 PDF OCR을 대신하지 않습니다."
                )
            if part is None:
                # Fallback: use the text the backend extracted at upload time.
                extracted = (getattr(file_obj, "data", None) or {}).get("content")
                if extracted:
                    part = {"text": (f'<file name="{name}">\n{extracted}\n</file>')}
                    self.log.info(
                        f"BYPASS_BACKEND_RAG: attaching '{name}' as extracted "
                        f"text (mime type '{mime_type}' not sent natively)"
                    )
                else:
                    self.log.warning(
                        f"BYPASS_BACKEND_RAG: skipping '{name}' "
                        f"(unsupported mime type '{mime_type}' and no extracted text)"
                    )
                    continue

            parts.append(part)
            attached_names.append(name)

        return parts, attached_names

    async def _prepare_content(
        self,
        messages: List[Dict[str, Any]],
        __metadata__: Optional[Dict[str, Any]] = None,
        __event_emitter__: Optional[Callable] = None,
    ) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        """
        Prepare messages content for the API and extract system message if present.

        Args:
            messages: List of message objects from the request
            __metadata__: Request metadata (used for BYPASS_BACKEND_RAG file handling)
            __event_emitter__: Optional event emitter for status updates

        Returns:
            Tuple of (prepared content list, system message string or None)
        """
        # Bypass backend RAG: strip the injected RAG context before any
        # further processing (applies to system and user messages alike).
        # Activated by the BYPASS_BACKEND_RAG valve OR by the companion
        # "Google Gemini RAG Bypass" filter having stashed files in metadata
        # (mirrors how the Gemini Manifold pipe consumes its companion filter).
        # Skipped for background task requests (title/tags generation, etc.).
        stashed_files = (__metadata__ or {}).get("_google_gemini_bypassed_files")
        ocr_full_pdf = bool((__metadata__ or {}).get("_google_gemini_ocr_full_pdf"))
        bypass_rag = (
            self.valves.BYPASS_BACKEND_RAG or bool(stashed_files) or ocr_full_pdf
        ) and not ((__metadata__ or {}).get("task"))
        metadata_files = self._collect_metadata_files(__metadata__)
        if (__metadata__ or {}).get("task"):
            metadata_files = []
        elif not bypass_rag:
            metadata_files = [
                entry
                for entry in metadata_files
                if (
                    self.valves.ENABLE_HWPX_SUPPORT
                    and self._is_hwpx_document(
                        entry.get("name", ""), entry.get("content_type", "")
                    )
                )
                or str(entry.get("content_type") or "").startswith("image/")
            ]
        file_parts, attached_names = ([], [])
        if metadata_files:
            file_parts, attached_names = await self._build_rag_bypass_parts(
                metadata_files, require_full_pdf=ocr_full_pdf
            )
        if bypass_rag and metadata_files and len(attached_names) == len(metadata_files):
            messages = self._strip_backend_rag_context(messages)

        # Extract user-defined system message
        user_system_message = (
            "\n\n".join(
                self._message_text(msg.get("content"))
                for msg in messages
                if msg.get("role") in {"system", "developer"}
            )
            or None
        )

        # Combine with default system prompt if configured
        system_message = self._combine_system_prompts(user_system_message)

        # Prepare contents for the API
        contents = []
        for message in messages:
            role = message.get("role")
            if role in {"system", "developer"}:
                continue  # Skip system messages, handled separately

            content = message.get("content", "")
            parts = []

            # Handle different content types
            if isinstance(content, list):  # Multimodal content
                resolved_content = []
                for item in content:
                    item = copy.deepcopy(item)
                    if item.get("type") == "image_url":
                        image_ref = item.get("image_url") or {}
                        url = (
                            image_ref
                            if isinstance(image_ref, str)
                            else image_ref.get("url", "")
                        )
                        if "/api/v1/files/" in url or url.startswith("/files/"):
                            loaded = await self._fetch_file_as_base64(url)
                            if loaded:
                                url = loaded
                        item["image_url"] = {"url": url}
                    resolved_content.append(item)
                parts.extend(self._process_multimodal_content(resolved_content))
            elif isinstance(content, str):  # Plain text content
                parts.append({"text": content})
            else:
                self.log.warning(f"Unsupported message content type: {type(content)}")
                continue  # Skip unsupported content

            # Map roles: 'assistant' -> 'model', 'user' -> 'user'
            api_role = "model" if role == "assistant" else "user"
            if parts:  # Only add if there are parts
                contents.append({"role": api_role, "parts": parts})

        # Bypass backend RAG: attach the original files natively to the last
        # user turn (mirrors the Gemini Manifold google_genai behavior of
        # attaching bypassed files to the last user message).
        if file_parts and contents:
            if metadata_files:
                # Already loaded before deciding whether RAG context can be removed.
                if file_parts:
                    last_user_content = next(
                        (c for c in reversed(contents) if c.get("role") == "user"),
                        None,
                    )
                    if last_user_content is not None:
                        last_user_content["parts"] = (
                            file_parts + last_user_content["parts"]
                        )
                        self.log.info(
                            "BYPASS_BACKEND_RAG: attached "
                            f"{len(file_parts)} file(s) natively: "
                            f"{', '.join(attached_names)}"
                        )
                        if __event_emitter__:
                            try:
                                await self._emit_optional(
                                    __event_emitter__,
                                    {
                                        "type": "status",
                                        "data": {
                                            "action": "rag_bypass",
                                            "description": (
                                                f"Prepared {len(attached_names)} file(s) "
                                                "for Gemini"
                                            ),
                                            "done": True,
                                        },
                                    },
                                )
                            except Exception as emit_error:
                                self.log.debug(
                                    f"Failed to emit RAG bypass status: {emit_error}"
                                )

        return contents, system_message

    def _process_multimodal_content(
        self, content_list: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Process multimodal content (text and images).

        Args:
            content_list: List of content items

        Returns:
            List of processed parts for the Gemini API
        """
        parts = []

        for item in content_list:
            if item.get("type") == "text":
                parts.append({"text": item.get("text", "")})
            elif item.get("type") == "image_url":
                image_url = item.get("image_url", {}).get("url", "")

                if image_url.startswith("data:image"):
                    # Handle base64 encoded image data with optimization
                    try:
                        # Optimize the image before processing
                        optimized_image = self._optimize_image_for_api(image_url)
                        header, encoded = optimized_image.split(",", 1)
                        mime_type = header.split(":")[1].split(";")[0]

                        # Basic validation for image types
                        if mime_type not in [
                            "image/jpeg",
                            "image/png",
                            "image/webp",
                            "image/heic",
                            "image/heif",
                        ]:
                            self.log.warning(
                                f"Unsupported image mime type: {mime_type}"
                            )
                            parts.append(
                                {"text": f"[Image type {mime_type} not supported]"}
                            )
                            continue

                        # Check if the encoded data is too large
                        if len(encoded) > 15 * 1024 * 1024:  # 15MB limit for base64
                            self.log.warning(
                                f"Image data too large: {len(encoded)} characters"
                            )
                            parts.append(
                                {
                                    "text": "[Image too large for processing - please use a smaller image]"
                                }
                            )
                            continue

                        parts.append(
                            {
                                "inline_data": {
                                    "mime_type": mime_type,
                                    "data": encoded,
                                }
                            }
                        )
                    except Exception as img_ex:
                        self.log.exception(f"Could not parse image data URL: {img_ex}")
                        parts.append({"text": "[Image data could not be processed]"})
                else:
                    # Gemini API doesn't directly support image URLs
                    self.log.warning(f"Direct image URLs not supported: {image_url}")
                    parts.append({"text": f"[Image URL not processed: {image_url}]"})

        return parts

    # _find_image removed (was single-image oriented and is superseded by multi-image logic)

    async def _extract_images_from_file_entries(
        self,
        entries: Optional[List[Dict[str, Any]]],
        *,
        stats_list: Optional[List[Dict[str, Any]]] = None,
    ) -> List[Dict[str, Any]]:
        """Load image attachments represented as Open WebUI file entries.

        Open WebUI can keep an attached image outside message.content, for example
        in body["files"], metadata["files"], companion-filter stash entries, or an
        assistant message's persisted "files" list. Image creation does not need
        these entries, but image editing absolutely does because the source pixels
        must be sent to Gemini.
        """
        result: List[Dict[str, Any]] = []
        if not entries:
            return result

        for entry in entries:
            if not isinstance(entry, dict):
                continue

            mime = (
                str(
                    entry.get("content_type")
                    or (entry.get("meta") or {}).get("content_type")
                    or ""
                )
                .split(";")[0]
                .strip()
                .lower()
            )
            entry_type = str(entry.get("type") or "").lower()

            # Do not treat arbitrary documents as edit-source images.
            is_image = entry_type in {"image", "image_file"} or mime.startswith(
                "image/"
            )
            if not is_image:
                continue

            data_url: Optional[str] = None

            # 1) Persisted Open WebUI image URL.
            url = str(
                entry.get("url")
                or entry.get("content_url")
                or entry.get("image_url")
                or ""
            ).strip()
            if url:
                if url.startswith("data:image"):
                    data_url = url
                elif "/files/" in url or "/api/v1/files/" in url:
                    data_url = await self._fetch_file_as_base64(url)

            # 2) File ID. This is the important path for uploads processed by
            #    Open WebUI / the RAG-bypass companion.
            if not data_url:
                file_id = entry.get("id") or entry.get("file_id")
                if file_id:
                    raw, file_obj = await self._load_owui_file(str(file_id))
                    if raw:
                        actual_mime = (
                            mime
                            or str(
                                (getattr(file_obj, "meta", None) or {}).get(
                                    "content_type", ""
                                )
                            )
                            .split(";")[0]
                            .strip()
                            .lower()
                            or "image/png"
                        )
                        if actual_mime.startswith("image/"):
                            data_url = f"data:{actual_mime};base64," + base64.b64encode(
                                raw
                            ).decode("utf-8")

            if not data_url:
                self.log.warning(
                    "Image edit attachment could not be loaded: name=%s id=%s url=%s",
                    entry.get("name"),
                    entry.get("id") or entry.get("file_id"),
                    url,
                )
                continue

            try:
                optimized = self._optimize_image_for_api(data_url, stats_list)
                header, b64 = optimized.split(",", 1)
                actual_mime = header.split(":", 1)[1].split(";", 1)[0]
                result.append(
                    {
                        "inline_data": {
                            "mime_type": actual_mime,
                            "data": b64,
                        }
                    }
                )
            except Exception as image_error:
                self.log.warning(
                    "Failed to prepare attached image for editing: %s", image_error
                )

        return result

    @staticmethod
    def _is_image_edit_request(text: str) -> bool:
        """Return True for explicit image modification/editing instructions."""
        if not text:
            return False
        t = text.strip().lower()

        ko = (
            r"(수정해|수정해줘|편집해|편집해줘|바꿔|바꿔줘|변경해|변경해줘|"
            r"지워|지워줘|제거해|제거해줘|추가해|추가해줘|합성해|합성해줘|"
            r"보정해|보정해줘|리터치|업스케일|확대해|복원해|배경\s*(?:을\s*)?"
            r"(?:없애|제거|바꿔)|스타일로\s*(?:바꿔|변환)|색(?:상)?\s*(?:을\s*)?"
            r"(?:바꿔|변경))"
        )
        en = (
            r"\b(edit|modify|change|replace|remove|erase|add|retouch|upscale|"
            r"restore|recolor|restyle|inpaint|outpaint|change the background|"
            r"remove the background)\b"
        )
        return bool(
            re.search(ko, t, flags=re.IGNORECASE)
            or re.search(en, t, flags=re.IGNORECASE)
        )

    async def _extract_images_from_message(
        self,
        message: Dict[str, Any],
        *,
        stats_list: Optional[List[Dict[str, Any]]] = None,
    ) -> Tuple[str, List[Dict[str, Any]]]:
        """Extract prompt text and ALL images from a single user message.

        This replaces the previous single-image _find_image logic for image-capable
        models so that multi-image prompts are respected.

        Returns:
            (prompt_text, image_parts)
                prompt_text: concatenated text content (may be empty)
                image_parts: list of {"inline_data": {mime_type, data}} dicts
        """
        content = message.get("content", "")
        text_segments: List[str] = []
        image_parts: List[Dict[str, Any]] = []

        # Helper to process a data URL or fetched file and append inline_data
        def _add_image(data_url: str):
            try:
                optimized = self._optimize_image_for_api(data_url, stats_list)
                header, b64 = optimized.split(",", 1)
                mime = header.split(":", 1)[1].split(";", 1)[0]
                image_parts.append({"inline_data": {"mime_type": mime, "data": b64}})
            except Exception as e:  # pragma: no cover - defensive
                self.log.warning(f"Skipping image (parse failure): {e}")

        # Regex to extract markdown image references
        md_pattern = re.compile(
            r"!\[[^\]]*\]\((data:image[^)]+|/files/[^)]+|/api/v1/files/[^)]+)\)"
        )

        # Structured multimodal array
        if isinstance(content, list):
            for item in content:
                if item.get("type") == "text":
                    txt = item.get("text", "")
                    text_segments.append(txt)
                    # Also parse any markdown images embedded in the text
                    for match in md_pattern.finditer(txt):
                        url = match.group(1)
                        if url.startswith("data:"):
                            _add_image(url)
                        else:
                            b64 = await self._fetch_file_as_base64(url)
                            if b64:
                                _add_image(b64)
                elif item.get("type") == "image_url":
                    url = item.get("image_url", {}).get("url", "")
                    if url.startswith("data:"):
                        _add_image(url)
                    elif "/files/" in url or "/api/v1/files/" in url:
                        b64 = await self._fetch_file_as_base64(url)
                        if b64:
                            _add_image(b64)
        # Plain string message (may include markdown images)
        elif isinstance(content, str):
            text_segments.append(content)
            for match in md_pattern.finditer(content):
                url = match.group(1)
                if url.startswith("data:"):
                    _add_image(url)
                else:
                    b64 = await self._fetch_file_as_base64(url)
                    if b64:
                        _add_image(b64)
        else:
            self.log.debug(
                f"Unsupported content type for image extraction: {type(content)}"
            )

        # Open WebUI often persists generated/attached images in a separate
        # message["files"] field rather than message.content.
        file_images = await self._extract_images_from_file_entries(
            message.get("files") or message.get("attachments"),
            stats_list=stats_list,
        )
        if file_images:
            image_parts.extend(file_images)

        prompt_text = " ".join(s.strip() for s in text_segments if s.strip())
        return prompt_text, image_parts

    def _optimize_image_for_api(
        self, image_data: str, stats_list: Optional[List[Dict[str, Any]]] = None
    ) -> str:
        """
        Optimize image data for Gemini API using configurable parameters.

        Returns:
            Optimized base64 data URL
        """
        # Check if optimization is enabled
        if not self.valves.IMAGE_ENABLE_OPTIMIZATION:
            self.log.debug("Image optimization disabled via configuration")
            return image_data

        max_size_mb = self.valves.IMAGE_MAX_SIZE_MB
        max_dimension = self.valves.IMAGE_MAX_DIMENSION
        base_quality = self.valves.IMAGE_COMPRESSION_QUALITY
        png_threshold = self.valves.IMAGE_PNG_COMPRESSION_THRESHOLD_MB

        self.log.debug(
            f"Image optimization config: max_size={max_size_mb}MB, max_dim={max_dimension}px, quality={base_quality}, png_threshold={png_threshold}MB"
        )
        try:
            # Parse the data URL
            if image_data.startswith("data:"):
                header, encoded = image_data.split(",", 1)
                mime_type = header.split(":")[1].split(";")[0]
            else:
                encoded = image_data
                mime_type = "image/png"

            # Decode and analyze the image
            image_bytes = base64.b64decode(encoded)
            original_size_mb = len(image_bytes) / (1024 * 1024)
            base64_size_mb = len(encoded) / (1024 * 1024)

            self.log.debug(
                f"Original image: {original_size_mb:.2f} MB (decoded), {base64_size_mb:.2f} MB (base64), type: {mime_type}"
            )

            # Determine optimization strategy
            reasons: List[str] = []
            if original_size_mb > max_size_mb:
                reasons.append(f"size > {max_size_mb} MB")
            if base64_size_mb > max_size_mb * 1.4:
                reasons.append("base64 overhead")
            if mime_type == "image/png" and original_size_mb > png_threshold:
                reasons.append(f"PNG > {png_threshold}MB")

            # Always check dimensions
            with Image.open(io.BytesIO(image_bytes)) as img:
                width, height = img.size
                resized_flag = False
                if width > max_dimension or height > max_dimension:
                    reasons.append(f"dimensions > {max_dimension}px")

                # Early exit: no optimization triggers -> keep original, record stats
                if not reasons:
                    if stats_list is not None:
                        stats_list.append(
                            {
                                "original_size_mb": round(original_size_mb, 4),
                                "final_size_mb": round(original_size_mb, 4),
                                "quality": None,
                                "format": mime_type.split("/")[-1].upper(),
                                "resized": False,
                                "reasons": ["no_optimization_needed"],
                                "final_hash": hashlib.sha256(
                                    encoded.encode()
                                ).hexdigest(),
                            }
                        )
                    self.log.debug(
                        "Skipping optimization: image already within thresholds"
                    )
                    return image_data

                self.log.debug(f"Optimization triggers: {', '.join(reasons)}")

                # Convert to RGB for JPEG compression
                if img.mode in ("RGBA", "LA", "P"):
                    background = Image.new("RGB", img.size, (255, 255, 255))
                    if img.mode == "P":
                        img = img.convert("RGBA")
                    background.paste(
                        img,
                        mask=img.split()[-1] if img.mode in ("RGBA", "LA") else None,
                    )
                    img = background
                elif img.mode != "RGB":
                    img = img.convert("RGB")

                # Resize if needed
                if width > max_dimension or height > max_dimension:
                    ratio = min(max_dimension / width, max_dimension / height)
                    new_size = (int(width * ratio), int(height * ratio))
                    self.log.debug(
                        f"Resizing from {width}x{height} to {new_size[0]}x{new_size[1]}"
                    )
                    img = img.resize(new_size, Image.Resampling.LANCZOS)
                    resized_flag = True

                # Determine quality levels based on original size and user configuration
                if original_size_mb > 5.0:
                    quality_levels = [
                        base_quality,
                        base_quality - 10,
                        base_quality - 20,
                        base_quality - 30,
                        base_quality - 40,
                        max(base_quality - 50, 25),
                    ]
                elif original_size_mb > 2.0:
                    quality_levels = [
                        base_quality,
                        base_quality - 5,
                        base_quality - 15,
                        base_quality - 25,
                        max(base_quality - 35, 35),
                    ]
                else:
                    quality_levels = [
                        min(base_quality + 5, 95),
                        base_quality,
                        base_quality - 10,
                        max(base_quality - 20, 50),
                    ]

                # Ensure quality levels are within valid range (1-100)
                quality_levels = [max(1, min(100, q)) for q in quality_levels]

                # Try compression levels
                for quality in quality_levels:
                    output_buffer = io.BytesIO()
                    format_type = (
                        "JPEG"
                        if original_size_mb > png_threshold or "jpeg" in mime_type
                        else "PNG"
                    )
                    output_mime = f"image/{format_type.lower()}"

                    img.save(
                        output_buffer,
                        format=format_type,
                        quality=quality,
                        optimize=True,
                    )
                    output_bytes = output_buffer.getvalue()
                    output_size_mb = len(output_bytes) / (1024 * 1024)

                    if output_size_mb <= max_size_mb:
                        optimized_b64 = base64.b64encode(output_bytes).decode("utf-8")
                        self.log.debug(
                            f"Optimized: {original_size_mb:.2f} MB → {output_size_mb:.2f} MB (Q{quality})"
                        )
                        if stats_list is not None:
                            stats_list.append(
                                {
                                    "original_size_mb": round(original_size_mb, 4),
                                    "final_size_mb": round(output_size_mb, 4),
                                    "quality": quality,
                                    "format": format_type,
                                    "resized": resized_flag,
                                    "reasons": reasons,
                                    "final_hash": hashlib.sha256(
                                        optimized_b64.encode()
                                    ).hexdigest(),
                                }
                            )
                        return f"data:{output_mime};base64,{optimized_b64}"

                # Fallback: minimum quality
                output_buffer = io.BytesIO()
                img.save(output_buffer, format="JPEG", quality=15, optimize=True)
                output_bytes = output_buffer.getvalue()
                output_size_mb = len(output_bytes) / (1024 * 1024)
                optimized_b64 = base64.b64encode(output_bytes).decode("utf-8")

                self.log.warning(
                    f"Aggressive optimization: {output_size_mb:.2f} MB (Q15)"
                )
                if stats_list is not None:
                    stats_list.append(
                        {
                            "original_size_mb": round(original_size_mb, 4),
                            "final_size_mb": round(output_size_mb, 4),
                            "quality": 15,
                            "format": "JPEG",
                            "resized": resized_flag,
                            "reasons": reasons + ["fallback_min_quality"],
                            "final_hash": hashlib.sha256(
                                optimized_b64.encode()
                            ).hexdigest(),
                        }
                    )
                return f"data:image/jpeg;base64,{optimized_b64}"

        except Exception as e:
            self.log.error(f"Image optimization failed: {e}")
            # Return original or safe fallback
            if image_data.startswith("data:"):
                if stats_list is not None:
                    stats_list.append(
                        {
                            "original_size_mb": None,
                            "final_size_mb": None,
                            "quality": None,
                            "format": None,
                            "resized": False,
                            "reasons": ["optimization_failed"],
                            "final_hash": (
                                hashlib.sha256(encoded.encode()).hexdigest()
                                if "encoded" in locals()
                                else None
                            ),
                        }
                    )
                return image_data
            return f"data:image/jpeg;base64,{encoded if 'encoded' in locals() else image_data}"

    async def _fetch_file_as_base64(self, file_url: str) -> Optional[str]:
        """
        Fetch a file from Open WebUI's file system and convert to base64.

        Args:
            file_url: File URL from Open WebUI

        Returns:
            Base64 encoded file data or None if file not found
        """
        try:
            if "/api/v1/files/" in file_url:
                fid = file_url.split("/api/v1/files/")[-1].split("/")[0].split("?")[0]
            else:
                fid = file_url.split("/files/")[-1].split("/")[0].split("?")[0]

            from pathlib import Path
            from open_webui.models.files import Files
            from open_webui.storage.provider import Storage

            file_obj = await Files.get_file_by_id(fid)
            if file_obj and file_obj.path:
                file_path = await asyncio.to_thread(Storage.get_file, file_obj.path)
                file_path = Path(file_path)
                if file_path.is_file():
                    async with aiofiles.open(file_path, "rb") as fp:
                        raw = await fp.read()
                    enc = base64.b64encode(raw).decode()
                    mime = file_obj.meta.get("content_type", "image/png")
                    return f"data:{mime};base64,{enc}"
        except Exception as e:
            self.log.warning(f"Could not fetch file {file_url}: {e}")
        return None

    async def _upload_image_with_status(
        self,
        image_data: Any,
        mime_type: str,
        __request__: Request,
        __user__: dict,
        __event_emitter__: Callable,
    ) -> str:
        """
        Unified image upload method with status updates and fallback handling.

        Returns:
            URL to uploaded image or data URL fallback
        """
        try:
            await self._emit_optional(
                __event_emitter__,
                {
                    "type": "status",
                    "data": {
                        "action": "image_upload",
                        "description": "Uploading generated image to your library...",
                        "done": False,
                    },
                },
            )

            self.user = user = await Users.get_user_by_id(__user__["id"])

            # Convert image data to base64 string if needed
            if isinstance(image_data, bytes):
                image_data_b64 = base64.b64encode(image_data).decode("utf-8")
            else:
                image_data_b64 = str(image_data)

            image_url = await self._upload_image(
                __request__=__request__,
                user=user,
                image_data=image_data_b64,
                mime_type=mime_type,
            )

            await self._emit_optional(
                __event_emitter__,
                {
                    "type": "status",
                    "data": {
                        "action": "image_upload",
                        "description": "Image uploaded successfully!",
                        "done": True,
                    },
                },
            )

            return image_url

        except Exception as e:
            self.log.warning(f"File upload failed, falling back to data URL: {e}")

            if isinstance(image_data, bytes):
                image_data_b64 = base64.b64encode(image_data).decode("utf-8")
            else:
                image_data_b64 = str(image_data)

            await self._emit_optional(
                __event_emitter__,
                {
                    "type": "status",
                    "data": {
                        "action": "image_upload",
                        "description": "Using inline image (upload failed)",
                        "done": True,
                    },
                },
            )

            return f"data:{mime_type};base64,{image_data_b64}"

    async def _upload_image(
        self, __request__: Request, user: UserModel, image_data: str, mime_type: str
    ) -> str:
        """
        Upload generated image to Open WebUI's file system.
        Expects base64 encoded string input.

        Args:
            __request__: FastAPI request object
            user: User model object
            image_data: Base64 encoded image data string
            mime_type: MIME type of the image

        Returns:
            URL to the uploaded image or data URL fallback
        """
        try:
            self.log.debug(
                f"Processing image data, type: {type(image_data)}, length: {len(image_data)}"
            )

            # Decode base64 string to bytes
            try:
                decoded_data = base64.b64decode(image_data)
                self.log.debug(
                    f"Successfully decoded image data: {len(decoded_data)} bytes"
                )
            except Exception as decode_error:
                self.log.error(f"Failed to decode base64 data: {decode_error}")
                # Try to add padding if missing
                try:
                    missing_padding = len(image_data) % 4
                    if missing_padding:
                        image_data += "=" * (4 - missing_padding)
                    decoded_data = base64.b64decode(image_data)
                    self.log.debug(
                        f"Successfully decoded with padding: {len(decoded_data)} bytes"
                    )
                except Exception as second_decode_error:
                    self.log.error(f"Still failed to decode: {second_decode_error}")
                    return f"data:{mime_type};base64,{image_data}"

            bio = io.BytesIO(decoded_data)
            bio.seek(0)

            # Determine file extension
            extension = "png"
            if "jpeg" in mime_type or "jpg" in mime_type:
                extension = "jpg"
            elif "webp" in mime_type:
                extension = "webp"
            elif "gif" in mime_type:
                extension = "gif"

            # Create filename
            filename = f"gemini-generated-{uuid.uuid4().hex}.{extension}"

            # Upload with simple approach like reference
            async with get_async_db_context() as db:
                up_obj = await upload_file(
                    request=__request__,
                    background_tasks=BackgroundTasks(),
                    file=UploadFile(
                        file=bio,
                        filename=filename,
                        headers=Headers({"content-type": mime_type}),
                    ),
                    process=False,  # Matching reference - no heavy processing
                    user=user,
                    metadata={
                        "mime_type": mime_type,
                        "source": "gemini_image_generation",
                    },
                    db=db,
                )

            self.log.debug(
                f"Upload completed. File ID: {up_obj.id}, Decoded size: {len(decoded_data)} bytes"
            )

            # Generate URL using reference method
            return __request__.app.url_path_for("get_file_content_by_id", id=up_obj.id)

        except Exception as e:
            self.log.exception(f"Image upload failed, using data URL fallback: {e}")
            # Fallback to data URL if upload fails
            return f"data:{mime_type};base64,{image_data}"

    async def _upload_video(
        self,
        __request__: Request,
        user: UserModel,
        video_data: bytes,
        mime_type: str = "video/mp4",
        chat_id: Optional[str] = None,
        message_id: Optional[str] = None,
    ) -> Tuple[str, Dict[str, Any]]:
        """Upload generated video to Open WebUI's file system.

        Returns:
            Tuple of (content_url, file_entry)
        """
        bio = io.BytesIO(video_data)
        bio.seek(0)

        extension = "mp4"
        if "webm" in mime_type:
            extension = "webm"

        filename = f"veo-generated-{uuid.uuid4().hex}.{extension}"

        async with get_async_db_context() as db:
            up_obj = await upload_file(
                request=__request__,
                background_tasks=BackgroundTasks(),
                file=UploadFile(
                    file=bio,
                    filename=filename,
                    headers=Headers({"content-type": mime_type}),
                ),
                process=False,
                user=user,
                metadata={"mime_type": mime_type, "source": "veo_video_generation"},
                db=db,
            )

            if chat_id and message_id:
                try:
                    await Chats.insert_chat_files(
                        chat_id=chat_id,
                        message_id=message_id,
                        file_ids=[up_obj.id],
                        user_id=user.id,
                        db=db,
                    )
                except Exception as chat_file_error:
                    self.log.warning(
                        f"Failed to link generated video file to chat message: {chat_file_error}"
                    )

        content_url = str(
            __request__.app.url_path_for("get_file_content_by_id", id=up_obj.id)
        )
        self.log.debug(
            f"Video upload completed. File ID: {up_obj.id}, Size: {len(video_data)} bytes"
        )
        return content_url, self._build_generated_video_file(
            file_id=up_obj.id,
            content_url=content_url,
            filename=filename,
            mime_type=mime_type,
            size=len(video_data),
        )

    async def _upload_video_with_status(
        self,
        video_data: bytes,
        mime_type: str,
        __request__: Request,
        __user__: dict,
        __event_emitter__: Callable,
        __metadata__: Optional[Dict[str, Any]] = None,
    ) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
        """Upload video with status updates and data-URL fallback.

        Returns:
            Tuple of (file_entry_or_None, content_url_or_data_url_or_None)
        """
        try:
            await self._emit_optional(
                __event_emitter__,
                {
                    "type": "status",
                    "data": {
                        "action": "video_upload",
                        "description": "Uploading generated video to your library...",
                        "done": False,
                    },
                },
            )

            self.user = user = await Users.get_user_by_id(__user__["id"])
            chat_id = __metadata__.get("chat_id") if __metadata__ else None
            message_id = __metadata__.get("message_id") if __metadata__ else None
            video_url, file_entry = await self._upload_video(
                __request__=__request__,
                user=user,
                video_data=video_data,
                mime_type=mime_type,
                chat_id=chat_id,
                message_id=message_id,
            )

            await self._emit_optional(
                __event_emitter__,
                {
                    "type": "status",
                    "data": {
                        "action": "video_upload",
                        "description": "Video uploaded successfully!",
                        "done": True,
                    },
                },
            )
            return file_entry, video_url

        except Exception as e:
            self.log.warning(f"Video upload failed, falling back to data URL: {e}")
            video_data_b64 = base64.b64encode(video_data).decode("utf-8")
            await self._emit_optional(
                __event_emitter__,
                {
                    "type": "status",
                    "data": {
                        "action": "video_upload",
                        "description": "Using inline video (upload failed)",
                        "done": True,
                    },
                },
            )
            return None, f"data:{mime_type};base64,{video_data_b64}"

    def _get_user_valve_value(
        self, __user__: Optional[dict], valve_name: str
    ) -> Optional[str]:
        """Get a user valve value, returning None if not set or set to 'default'"""
        if __user__ and "valves" in __user__:
            value = getattr(__user__["valves"], valve_name, None)
            if value and value != "default":
                return value
        return None

    @staticmethod
    def _message_text(content: Any) -> str:
        """Extract visible text from an Open WebUI message content value."""
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            chunks: List[str] = []
            for item in content:
                if isinstance(item, str):
                    chunks.append(item)
                elif isinstance(item, dict):
                    if item.get("type") == "text" and isinstance(item.get("text"), str):
                        chunks.append(item["text"])
                    elif isinstance(item.get("content"), str):
                        chunks.append(item["content"])
            return "\n".join(chunks)
        if isinstance(content, dict):
            if isinstance(content.get("text"), str):
                return content["text"]
            if isinstance(content.get("content"), str):
                return content["content"]
        return ""

    def _last_user_text(self, body: Dict[str, Any]) -> str:
        for msg in reversed(body.get("messages") or []):
            if isinstance(msg, dict) and msg.get("role") == "user":
                return self._message_text(msg.get("content")).strip()
        return ""

    def _last_user_has_image(self, body: Dict[str, Any]) -> bool:
        """Best-effort detection of an image attached to the latest user turn."""
        for msg in reversed(body.get("messages") or []):
            if not isinstance(msg, dict) or msg.get("role") != "user":
                continue
            content = msg.get("content")
            if isinstance(content, list):
                for item in content:
                    if not isinstance(item, dict):
                        continue
                    item_type = str(item.get("type") or "").lower()
                    if item_type in {
                        "image",
                        "image_url",
                        "input_image",
                        "image_file",
                    }:
                        return True
                    if item.get("image_url") or item.get("image"):
                        return True
            break

        # Some Open WebUI versions keep attachments at request level.
        candidate_files: List[Dict[str, Any]] = [
            f for f in (body.get("files") or []) if isinstance(f, dict)
        ]
        body_md = body.get("metadata") or {}
        if isinstance(body_md, dict):
            candidate_files.extend(
                f
                for f in (body_md.get("_google_gemini_bypassed_files") or [])
                if isinstance(f, dict)
            )

        for f in candidate_files:
            if not isinstance(f, dict):
                continue
            mime = str(
                f.get("content_type") or (f.get("meta") or {}).get("content_type") or ""
            ).lower()
            ftype = str(f.get("type") or "").lower()
            if mime.startswith("image/") or ftype == "image":
                return True
        return False

    @staticmethod
    def _should_auto_image_route(text: str, has_image: bool = False) -> bool:
        """
        Conservative image generation/editing intent detector.

        It intentionally requires an image-related noun or a clear editing
        instruction so questions *about* image models do not get routed.
        """
        if not text:
            return False

        t = text.strip().lower()
        if re.search(
            r"(ocr|텍스트\s*추출|글자\s*추출|전사|번역|transcrib|extract\s+text)", t
        ):
            return False
        if re.search(
            r"(이미지|그림|사진|image|picture).{0,30}(만들지|생성하지|그리지)", t
        ) or re.search(r"(?:do not|don't|never)\s+(?:create|generate|draw)", t):
            return False

        # Explicit image creation nouns.
        image_nouns_ko = (
            r"(이미지|그림|사진|일러스트|삽화|포스터|아이콘|로고|배너|"
            r"썸네일|캐릭터|초상화|프로필\s*사진|배경화면)"
        )
        create_verbs_ko = (
            r"(만들어|만들어줘|생성해|생성해줘|그려|그려줘|제작해|제작해줘|"
            r"디자인해|디자인해줘|렌더링해|렌더해|시각화해|시각화해줘)"
        )
        edit_verbs_ko = (
            r"(수정해|수정해줘|편집해|편집해줘|바꿔|바꿔줘|변경해|변경해줘|"
            r"지워|지워줘|제거해|제거해줘|추가해|추가해줘|합성해|합성해줘|"
            r"보정해|보정해줘|리터치|업스케일|배경\s*(?:을\s*)?(?:없애|제거|바꿔)|"
            r"스타일로\s*(?:바꿔|변환))"
        )

        if re.search(image_nouns_ko, t) and re.search(
            create_verbs_ko + "|" + edit_verbs_ko, t
        ):
            return True
        if has_image and re.search(edit_verbs_ko, t):
            return True

        # English creation/editing requests.
        image_nouns_en = (
            r"\b(image|picture|photo|illustration|poster|icon|logo|banner|"
            r"thumbnail|portrait|wallpaper|character art)\b"
        )
        create_verbs_en = r"\b(generate|create|draw|render|design|make|illustrate)\b"
        edit_verbs_en = (
            r"\b(edit|modify|change|replace|remove|erase|add|retouch|"
            r"upscale|restyle|recolor|inpaint|outpaint)\b"
        )

        if re.search(image_nouns_en, t) and re.search(
            create_verbs_en + "|" + edit_verbs_en, t
        ):
            return True
        if has_image and re.search(edit_verbs_en, t):
            return True

        return False

    def _is_auto_thinking_candidate_model(self, model_id: str) -> bool:
        """Auto-route thinking only for Gemini 3.x Flash text models.

        OCR, image, video, Pro, and older Gemini 2.5 models keep their existing
        dedicated/default thinking behavior.
        """
        model_lower = str(model_id or "").lower()
        if not self._check_thinking_level_support(model_lower):
            return False
        if self._check_image_generation_support(model_lower):
            return False
        if self._check_video_generation_support(model_lower):
            return False
        return "flash" in model_lower and "image" not in model_lower

    @staticmethod
    def _count_request_attachments(
        body: Dict[str, Any], __metadata__: Optional[Dict[str, Any]] = None
    ) -> Tuple[int, int, int]:
        """Return (total_files, image_files, document_files) for routing hints.

        Counts best-effort references across Open WebUI message content, body
        files, metadata files, and the RAG-bypass companion stash. Duplicate
        IDs/URLs are collapsed so the same upload does not inflate complexity.
        """
        seen: set[str] = set()
        image_count = 0
        document_count = 0

        def add_entry(entry: Any, prefix: str = "file") -> None:
            nonlocal image_count, document_count
            if not isinstance(entry, dict):
                return

            mime = (
                str(
                    entry.get("content_type")
                    or (entry.get("meta") or {}).get("content_type")
                    or entry.get("mime_type")
                    or ""
                )
                .split(";")[0]
                .strip()
                .lower()
            )
            ftype = str(entry.get("type") or "").lower()
            fid = str(entry.get("id") or entry.get("file_id") or "").strip()
            url = str(
                entry.get("url")
                or entry.get("content_url")
                or entry.get("image_url")
                or ""
            ).strip()
            name = str(entry.get("name") or entry.get("filename") or "").strip()
            key = fid or url or (f"{name}|{mime}" if name or mime else "")
            if not key:
                key = f"{prefix}:{id(entry)}"
            if key in seen:
                return
            seen.add(key)

            is_image = mime.startswith("image/") or ftype in {
                "image",
                "image_file",
                "input_image",
                "image_url",
            }
            if is_image:
                image_count += 1
            else:
                document_count += 1

        for entry in body.get("files") or []:
            add_entry(entry, "body")

        body_md = body.get("metadata") or {}
        metadata_sources: List[Dict[str, Any]] = []
        if isinstance(body_md, dict):
            metadata_sources.append(body_md)
        if isinstance(__metadata__, dict):
            metadata_sources.append(__metadata__)

        for md in metadata_sources:
            for key in ("files", "_google_gemini_bypassed_files"):
                for entry in md.get(key) or []:
                    add_entry(entry, key)

        # Structured content can hold images/files directly.
        for msg_index, msg in enumerate(body.get("messages") or []):
            if not isinstance(msg, dict):
                continue
            for entry in msg.get("files") or msg.get("attachments") or []:
                add_entry(entry, f"msg{msg_index}")
            content = msg.get("content")
            if not isinstance(content, list):
                continue
            for item_index, item in enumerate(content):
                if not isinstance(item, dict):
                    continue
                item_type = str(item.get("type") or "").lower()
                if item_type in {
                    "image",
                    "image_url",
                    "input_image",
                    "image_file",
                    "file",
                    "input_file",
                }:
                    add_entry(item, f"content{msg_index}:{item_index}")

        return len(seen), image_count, document_count

    @staticmethod
    def _auto_thinking_text_score(text: str) -> Tuple[int, List[str]]:
        """Score the latest user text for reasoning complexity.

        This is intentionally conservative. It uses no model/API call, so the
        latency and token cost of routing are effectively zero.
        """
        if not text:
            return 0, ["empty/very short request"]

        t = text.strip()
        lower = t.lower()
        score = 0
        reasons: List[str] = []

        # Strong hard-reasoning signals.
        hard_patterns = [
            r"(증명해|증명하|수학적\s*증명|정리.*증명|유도해|엄밀하게|논리적으로\s*도출)",
            r"(복잡한\s*오류|근본\s*원인|원인\s*분석|디버깅|debug|stack\s*trace|traceback)",
            r"(알고리즘.*복잡도|시간\s*복잡도|공간\s*복잡도|최적화|optimization|race\s*condition|deadlock)",
            r"(아키텍처|architecture|시스템\s*설계|설계\s*대안|trade[- ]?off|트레이드오프)",
            r"(다단계\s*추론|multi[- ]?step|formal\s*proof|theorem|derive|derivation)",
            r"(미적분|적분|미분|확률\s*분포|선형대수|행렬|수열|기하|combinatorics|calculus|integral|derivative)",
            r"(취약점\s*분석|보안\s*검토|security\s*review|root\s*cause)",
        ]
        if any(re.search(p, lower, flags=re.IGNORECASE) for p in hard_patterns):
            score += 5
            reasons.append("hard reasoning/debug/math signal")

        # General analysis/synthesis signals.
        analysis_patterns = [
            r"(분석해|분석하|비교해|비교하|검토해|검토하|평가해|평가하|종합해|종합하)",
            r"(장단점|근거와\s*함께|단계별|체계적으로|상세하게|심층|정교하게)",
            r"\b(analy[sz]e|compare|evaluate|review|synthesize|reason|step[- ]by[- ]step)\b",
            r"(코드.*작성|코드.*수정|함수.*수정|구현해|리팩터링|refactor|implement)",
            r"(세특|생기부|생활기록부|교과학습발달상황|학생부|평가서|"
            r"프롬프트.*(?:개선|작성|정교)|prompt.*(?:improve|design))",
        ]
        if any(re.search(p, lower, flags=re.IGNORECASE) for p in analysis_patterns):
            score += 2
            reasons.append("analysis/synthesis signal")

        # Code blocks, logs, or structured technical payloads.
        code_fences = t.count("```")
        if code_fences >= 2 or re.search(
            r"(^|\n)\s*(?:Traceback \(most recent call last\):|Exception:|Error:|"
            r"SELECT\s+|CREATE\s+TABLE|function\s+\w+\s*\(|def\s+\w+\s*\(|"
            r"class\s+\w+[:(]|\{[\s\S]{200,}\})",
            t,
            flags=re.IGNORECASE,
        ):
            score += 2
            reasons.append("code/log/structured payload")

        # Explicit multi-source or constraint-heavy tasks.
        if re.search(
            r"(여러\s*(?:자료|문서|파일|관점)|복수\s*(?:자료|문서)|상충|모순|"
            r"제약\s*조건|조건을\s*모두|요구사항을\s*모두|multiple\s*(?:files|sources|documents)|"
            r"conflicting|constraints?)",
            lower,
            flags=re.IGNORECASE,
        ):
            score += 2
            reasons.append("multi-source/constraint signal")

        # Simple tasks suppress overthinking unless other strong signals exist.
        simple_patterns = [
            r"^\s*(안녕|안녕하세요|고마워|감사|hello|hi|thanks)\b",
            r"(번역해|번역해줘|translate\b)",
            r"(뜻이\s*뭐|무슨\s*뜻|의미가\s*뭐|what does .* mean)",
            r"(맞춤법|문법만|다듬어줘|고쳐줘|rewrite|proofread)",
            r"(짧게\s*요약|간단히\s*요약|한\s*줄|한줄|요약해줘|summari[sz]e briefly)",
        ]
        if any(re.search(p, lower, flags=re.IGNORECASE) for p in simple_patterns):
            score -= 2
            reasons.append("simple translation/rewrite/chat signal")

        # Very short requests are usually latency-sensitive.
        if len(t) <= 120 and score <= 1:
            score -= 1
            reasons.append("short request")

        return score, reasons

    def _select_auto_thinking_level(
        self,
        body: Dict[str, Any],
        model_id: str,
        __metadata__: Optional[Dict[str, Any]] = None,
    ) -> Tuple[Optional[str], str]:
        """Choose a model-valid thinking level using local request heuristics."""
        if not self.valves.AUTO_THINKING:
            return None, "AUTO_THINKING disabled"
        if not self._is_auto_thinking_candidate_model(model_id):
            return None, "model excluded from Auto Thinking"

        text = self._last_user_text(body)
        score, reasons = self._auto_thinking_text_score(text)
        total_files, image_files, document_files = self._count_request_attachments(
            body, __metadata__
        )

        # Length and attachment signals are additive so a long, multi-file
        # analytical request naturally reaches high.
        if len(text) >= self.valves.AUTO_THINKING_VERY_LONG_TEXT_CHARS:
            score += 4
            reasons.append(f"very long latest prompt ({len(text):,} chars)")
        elif len(text) >= self.valves.AUTO_THINKING_LONG_TEXT_CHARS:
            score += 2
            reasons.append(f"long latest prompt ({len(text):,} chars)")

        if total_files >= self.valves.AUTO_THINKING_MULTIFILE_THRESHOLD:
            score += 2
            score = max(score, 2)
            reasons.append(f"multiple attachments ({total_files})")
        elif document_files >= 1:
            score += 2
            score = max(score, 2)
            reasons.append("document attachment")
        elif image_files >= 1:
            # A text question about one image usually needs some multimodal
            # reasoning, but not automatically the maximum level.
            score += 1
            reasons.append("image attachment")

        # Long-running/agentic tool requests benefit from at least medium.
        metadata = __metadata__ or {}
        params = metadata.get("params", {}) or {}
        if params.get("function_calling") == "native" and body.get("tools"):
            score += 1
            reasons.append("native tool workflow")

        # Convert score to target category.
        if score >= 5:
            requested = self.valves.AUTO_THINKING_COMPLEX_LEVEL
            category = "complex"
        elif score >= 2:
            requested = self.valves.AUTO_THINKING_LONG_CONTEXT_LEVEL
            category = "long/analytical"
        else:
            requested = self.valves.AUTO_THINKING_DEFAULT_LEVEL
            category = "ordinary/simple"

        validated = self._validate_thinking_level(requested, model_id)
        if not validated:
            # If an admin configured an invalid target, use the model's lowest
            # known supported level rather than failing the whole request.
            supported = self._get_supported_thinking_levels(model_id)
            validated = supported[0] if supported else None

        reason_text = f"{category}; score={score}; " + (
            ", ".join(reasons) if reasons else "no strong complexity signal"
        )
        return validated, reason_text

    @staticmethod
    def _should_auto_google_search(text: str) -> bool:
        """Conservative freshness/web-intent detector for automatic grounding."""
        if not text:
            return False

        t = text.lower()

        # Explicit URLs and explicit search/source requests.
        if re.search(r"https?://|www\.", t):
            return True

        patterns = [
            # Korean: freshness, web lookup, weather/news/market/current public facts.
            r"(오늘|내일|이번\s*주|이번\s*달|현재|지금|최신|최근|실시간|속보|뉴스|날씨|기상|"
            r"예보|주가|증시|환율|가격|시세|일정|스코어|결과|순위|출시|공개|업데이트|"
            r"버전|추가되|새로\s*나온|검색해|찾아줘|찾아봐|웹에서|인터넷에서|출처|근거|"
            r"공식\s*문서|공식\s*사이트|현직|현재\s*대통령|현재\s*CEO)",
            # English equivalents.
            r"\b(today|tomorrow|this week|this month|current|currently|latest|recent|"
            r"real[- ]?time|breaking|news|weather|forecast|stock|share price|exchange rate|"
            r"price|schedule|score|standings|released|release|updated|update|version|"
            r"newly added|search|look up|browse|web|internet|source|citation|official docs?|"
            r"official site|current president|current ceo)\b",
        ]
        return any(re.search(p, t, flags=re.IGNORECASE) for p in patterns)

    @staticmethod
    def _prefer_native_tool_for_query(
        text: str, __tools__: Optional[dict[str, Any]]
    ) -> bool:
        """Prefer obvious local/native utility tools over web search when available."""
        if not text or not __tools__:
            return False

        t = text.lower()
        tool_blob_parts: List[str] = []
        for name, tool_def in __tools__.items():
            tool_blob_parts.append(str(name).lower())
            if isinstance(tool_def, dict):
                spec = tool_def.get("spec") or {}
                if isinstance(spec, dict):
                    tool_blob_parts.append(str(spec.get("name") or "").lower())
                    tool_blob_parts.append(str(spec.get("description") or "").lower())
        tool_blob = " ".join(tool_blob_parts)

        utility_routes = [
            (
                r"(몇\s*시|현재\s*시간|지금\s*시간|시각|타임스탬프|timestamp|what time|current time)",
                r"(time|timestamp|clock|date|시간|시각)",
            ),
            (
                r"(계산|계산해|calculator|calculate|arithmetic|산술)",
                r"(calculator|calculate|math|계산)",
            ),
            (
                r"(단위\s*변환|환산|convert|conversion)",
                r"(convert|conversion|unit|변환|환산)",
            ),
        ]
        for query_pat, tool_pat in utility_routes:
            if re.search(query_pat, t, flags=re.IGNORECASE) and re.search(
                tool_pat, tool_blob, flags=re.IGNORECASE
            ):
                return True
        return False

    @staticmethod
    def _json_tool_result(value):
        """Convert nested mapping proxies and standard model results at the AFC boundary."""
        active = set()

        def convert(item):
            if item is None or isinstance(item, (str, bool, int, float)):
                return item
            marker = id(item)
            if marker in active:
                raise ValueError("Circular tool result")
            active.add(marker)
            try:
                if isinstance(item, Mapping):
                    return {str(k): convert(v) for k, v in item.items()}
                if isinstance(item, (list, tuple, set, frozenset)):
                    return [convert(v) for v in item]
                if isinstance(item, BaseModel):
                    return convert(item.model_dump(mode="python"))
                if isinstance(item, bytes):
                    return {
                        "encoding": "base64",
                        "data": base64.b64encode(item).decode("ascii"),
                    }
                raise TypeError("Unsupported tool result type: " + type(item).__name__)
            finally:
                active.remove(marker)

        result = convert(value)
        json.dumps(result, allow_nan=False)
        return result

    @staticmethod
    def _named_native_tool(name, tool, used_names):
        """Give each SDK callable a request-local name without mutating shared tools."""
        original_name = str(name)
        api_name = re.sub(r"[^A-Za-z0-9_]", "_", original_name)
        if not api_name or not re.match(r"[A-Za-z_]", api_name):
            api_name = "tool_" + api_name
        if api_name != original_name or len(api_name) > 64:
            digest = hashlib.sha256(original_name.encode()).hexdigest()[:12]
            api_name = api_name[:51] + "_" + digest
        base = api_name
        number = 1
        while api_name in used_names:
            suffix = "_" + str(number)
            api_name = base[: 64 - len(suffix)] + suffix
            number += 1
        used_names.add(api_name)

        async def named_tool(*args, **kwargs):
            try:
                if inspect.iscoroutinefunction(tool):
                    result = await tool(*args, **kwargs)
                else:
                    result = await asyncio.to_thread(tool, *args, **kwargs)
                    if inspect.isawaitable(result):
                        result = await result
                return Pipe._json_tool_result(result)
            except Exception as exc:
                # Do not feed exception objects / HTTP headers to SDK serialization.
                return {
                    "error": {
                        "tool": api_name,
                        "type": type(exc).__name__,
                        "message": str(exc),
                    },
                    "ok": False,
                    "instruction": "The tool failed. Do not invent results or claim successful retrieval.",
                }

        # Both schema discovery and automatic-call dispatch use __name__.
        # __signature__ keeps the public parameters instead of *args/**kwargs.
        named_tool.__name__ = api_name
        named_tool.__qualname__ = api_name
        named_tool.__doc__ = getattr(tool, "__doc__", None) or original_name
        named_tool.__annotations__ = dict(getattr(tool, "__annotations__", {}) or {})
        named_tool.__signature__ = inspect.signature(tool)
        return named_tool

    def _configure_generation(
        self,
        body: Dict[str, Any],
        system_instruction: Optional[str],
        __metadata__: Dict[str, Any],
        __tools__: dict[str, Any] | None = None,
        __user__: Optional[dict] = None,
        enable_image_generation: bool = False,
        model_id: str = "",
        disable_auto_search: bool = False,
    ) -> types.GenerateContentConfig:
        """
        Configure generation parameters and safety settings.

        Args:
            body: The request body containing generation parameters
            system_instruction: Optional system instruction string
            enable_image_generation: Whether to enable image generation
            model_id: The model ID being used (for feature support checks)

        Returns:
            types.GenerateContentConfig
        """
        ocr_mode = self._is_ocr_virtual_model(body.get("model", ""))

        response_guidance = (
            "응답 방식: 내부 지침은 조용히 적용하세요. 사용자가 지침 자체의 설명을 "
            "요청하지 않았다면 AGENTS.md, 시스템 프롬프트, Skill 목록이나 준수 선언을 "
            "인사말 또는 답변에 나열하지 마세요. 인사에는 간단히 인사하고 실제 질문에 답하세요. "
            "최신 정보나 검색을 요청받으면 제공된 검색 도구를 사용하고 확인한 출처를 제시하세요. "
            "도구가 실패하거나 검색 결과가 없으면 그 사실을 말하고 결과를 지어내지 마세요."
        )
        system_instruction = (
            (system_instruction or "").rstrip() + "\n\n" + response_guidance
        ).strip()

        # Gemini 3.6 Flash and future Gemini releases reject/deprecate the
        # legacy sampling controls temperature/top_p/top_k. Build a minimal
        # common config first, then add those controls only for older models.
        gen_config_params = {
            "max_output_tokens": body.get("max_tokens"),
            "stop_sequences": (
                [body["stop"]]
                if isinstance(body.get("stop"), str)
                else body.get("stop")
            )
            or None,
            "system_instruction": system_instruction,
        }

        if ocr_mode:
            media_resolution_name = self._normalize_ocr_media_resolution(
                self.valves.OCR_MEDIA_RESOLUTION
            )
            if media_resolution_name:
                media_enum = getattr(types, "MediaResolution", None)
                media_value: Any = media_resolution_name
                if media_enum is not None and hasattr(
                    media_enum, media_resolution_name
                ):
                    media_value = getattr(media_enum, media_resolution_name)

                config_fields = getattr(types.GenerateContentConfig, "model_fields", {})
                if not config_fields or "media_resolution" in config_fields:
                    gen_config_params["media_resolution"] = media_value
                    self.log.debug("OCR media_resolution=%s", media_resolution_name)
                else:
                    # Compatibility fallback for older google-genai versions.
                    try:
                        gen_config_params["http_options"] = types.HttpOptions(
                            extra_body={
                                "generation_config": {
                                    "media_resolution": media_resolution_name
                                }
                            }
                        )
                        self.log.warning(
                            "Installed google-genai lacks typed media_resolution; "
                            "using HttpOptions.extra_body fallback"
                        )
                    except Exception as media_fallback_error:
                        self.log.warning(
                            "OCR media_resolution unavailable in installed google-genai: %s",
                            media_fallback_error,
                        )

        if self._uses_modern_sampling_config(model_id):
            ignored_sampling = {
                key: body.get(key)
                for key in ("temperature", "top_p", "top_k")
                if body.get(key) is not None
            }
            if ignored_sampling:
                self.log.debug(
                    "Omitting deprecated sampling parameters for %s: %s",
                    model_id,
                    ", ".join(ignored_sampling.keys()),
                )
        else:
            gen_config_params.update(
                {
                    "temperature": body.get("temperature"),
                    "top_p": body.get("top_p"),
                    "top_k": body.get("top_k"),
                }
            )

        # Enable image generation if requested
        if enable_image_generation:
            gen_config_params["response_modalities"] = ["TEXT", "IMAGE"]

            # Configure image generation parameters (aspect ratio and resolution)
            # ImageConfig is only supported by Gemini 3 models
            if self._check_image_config_support(model_id):
                # Body parameters override valve defaults for per-request customization
                # Get aspect_ratio: body > user_valves (if not "default") > system valves
                user_aspect_ratio = self._get_user_valve_value(
                    __user__, "IMAGE_GENERATION_ASPECT_RATIO"
                )
                aspect_ratio = body.get(
                    "aspect_ratio",
                    user_aspect_ratio or self.valves.IMAGE_GENERATION_ASPECT_RATIO,
                )

                # Get resolution: body > user_valves (if not "default") > system valves
                user_resolution = self._get_user_valve_value(
                    __user__, "IMAGE_GENERATION_RESOLUTION"
                )
                resolution = body.get(
                    "resolution",
                    user_resolution or self.valves.IMAGE_GENERATION_RESOLUTION,
                )

                # Validate and normalize the values
                validated_aspect_ratio = self._validate_aspect_ratio(aspect_ratio)
                validated_resolution = self._validate_resolution(resolution)

                # Create image config if we have at least one valid value
                if validated_aspect_ratio or validated_resolution:
                    try:
                        image_config_params = {}
                        if validated_aspect_ratio:
                            image_config_params["aspect_ratio"] = validated_aspect_ratio
                        if validated_resolution:
                            image_config_params["image_size"] = validated_resolution
                        gen_config_params["image_config"] = types.ImageConfig(
                            **image_config_params
                        )
                        self.log.debug(
                            f"Image generation config: aspect_ratio={validated_aspect_ratio}, resolution={validated_resolution}"
                        )
                    except (AttributeError, TypeError) as e:
                        # Fall back if SDK does not support ImageConfig
                        self.log.warning(
                            f"ImageConfig not supported by SDK version: {e}. Image generation will use default settings."
                        )
                    except Exception as e:
                        # Log unexpected errors but continue without image config
                        self.log.warning(
                            f"Unexpected error configuring ImageConfig: {e}"
                        )
            else:
                self.log.debug(
                    f"Model {model_id} does not support ImageConfig (aspect_ratio/resolution). "
                    "ImageConfig is only available for Gemini 3 image models."
                )

        # Configure Gemini thinking/reasoning for models that support it
        # This is independent of include_thoughts - thinking config controls HOW the model reasons,
        # while include_thoughts controls whether the reasoning is shown in the output
        if self._check_thinking_support(model_id):
            try:
                thinking_config_params: Dict[str, Any] = {}

                # Determine include_thoughts setting
                include_thoughts = body.get("include_thoughts", True)
                if ocr_mode:
                    include_thoughts = self.valves.OCR_INCLUDE_THOUGHTS
                if not self.valves.INCLUDE_THOUGHTS and not ocr_mode:
                    include_thoughts = False
                    self.log.debug(
                        "Thoughts output disabled via GOOGLE_INCLUDE_THOUGHTS"
                    )
                thinking_config_params["include_thoughts"] = include_thoughts

                # Check if model supports thinking_level (Gemini 3 models)
                if self._check_thinking_level_support(model_id):
                    # For Gemini 3 models, use thinking_level (not thinking_budget)
                    # Per-chat reasoning_effort overrides environment-level THINKING_LEVEL
                    reasoning_effort = (
                        self.valves.OCR_THINKING_LEVEL
                        if ocr_mode
                        else body.get("reasoning_effort")
                    )
                    validated_level = None
                    source = "OCR_THINKING_LEVEL" if ocr_mode else None

                    if reasoning_effort:
                        validated_level = self._validate_thinking_level(
                            reasoning_effort, model_id
                        )
                        if validated_level and not ocr_mode:
                            source = (
                                "AUTO_THINKING"
                                if body.get("_google_auto_thinking")
                                else "per-chat reasoning_effort"
                            )
                        elif not validated_level:
                            self.log.debug(
                                f"Invalid reasoning_effort '{reasoning_effort}', falling back to THINKING_LEVEL"
                            )

                    # Fall back to environment-level THINKING_LEVEL for normal
                    # models. OCR uses its own dedicated OCR_THINKING_LEVEL.
                    if not validated_level and not ocr_mode:
                        validated_level = self._validate_thinking_level(
                            self.valves.THINKING_LEVEL, model_id
                        )
                        if validated_level:
                            source = "THINKING_LEVEL"

                    if validated_level:
                        thinking_config_params["thinking_level"] = validated_level
                        self.log.debug(
                            f"Using thinking_level='{validated_level}' from {source} for model {model_id}"
                        )
                    else:
                        self.log.debug(
                            f"Using default thinking level for model {model_id}"
                        )
                else:
                    # For non-Gemini 3 models (e.g., Gemini 2.5), use thinking_budget
                    # Body-level thinking_budget overrides environment-level THINKING_BUDGET
                    body_thinking_budget = body.get("thinking_budget")
                    validated_budget = None
                    source = None

                    if body_thinking_budget is not None:
                        validated_budget = self._validate_thinking_budget(
                            body_thinking_budget
                        )
                        if validated_budget is not None:
                            source = "body thinking_budget"
                        else:
                            self.log.debug(
                                f"Invalid body thinking_budget '{body_thinking_budget}', falling back to THINKING_BUDGET"
                            )

                    # Fall back to environment-level THINKING_BUDGET
                    if validated_budget is None:
                        validated_budget = self._validate_thinking_budget(
                            self.valves.THINKING_BUDGET
                        )
                        if validated_budget is not None:
                            source = "THINKING_BUDGET"

                    if validated_budget == 0:
                        # Disable thinking if budget is 0
                        thinking_config_params["thinking_budget"] = 0
                        self.log.debug(
                            f"Thinking disabled via thinking_budget=0 from {source} for model {model_id}"
                        )
                    elif validated_budget is not None and validated_budget > 0:
                        thinking_config_params["thinking_budget"] = validated_budget
                        self.log.debug(
                            f"Using thinking_budget={validated_budget} from {source} for model {model_id}"
                        )
                    else:
                        # -1 or None means dynamic thinking
                        thinking_config_params["thinking_budget"] = -1
                        self.log.debug(
                            f"Using dynamic thinking (model decides) for model {model_id}"
                        )

                gen_config_params["thinking_config"] = types.ThinkingConfig(
                    **thinking_config_params
                )
            except (AttributeError, TypeError) as e:
                # Fall back if SDK/model does not support ThinkingConfig
                self.log.debug(f"ThinkingConfig not supported: {e}")
            except Exception as e:
                # Log unexpected errors but continue without thinking config
                self.log.warning(f"Unexpected error configuring ThinkingConfig: {e}")

        # Configure safety settings
        if self.valves.USE_PERMISSIVE_SAFETY:
            safety_settings = [
                types.SafetySetting(
                    category="HARM_CATEGORY_HARASSMENT", threshold="BLOCK_NONE"
                ),
                types.SafetySetting(
                    category="HARM_CATEGORY_HATE_SPEECH", threshold="BLOCK_NONE"
                ),
                types.SafetySetting(
                    category="HARM_CATEGORY_SEXUALLY_EXPLICIT", threshold="BLOCK_NONE"
                ),
                types.SafetySetting(
                    category="HARM_CATEGORY_DANGEROUS_CONTENT", threshold="BLOCK_NONE"
                ),
            ]
            gen_config_params |= {"safety_settings": safety_settings}

        # Add various tools to Gemini as required.
        # Open WebUI 0.10+ treats native function calling as the default, so an
        # absent function_calling value is handled as native unless it is
        # explicitly set to "legacy".
        metadata = __metadata__ or {}
        features = metadata.get("features", {}) or {}
        params = metadata.get("params", {}) or {}
        tools = []

        function_calling_mode = str(params.get("function_calling") or "native").lower()
        native_function_calling = function_calling_mode != "legacy"
        has_native_tools = (
            bool(__tools__)
            and native_function_calling
            and not enable_image_generation
            and not (ocr_mode and self.valves.OCR_DISABLE_NATIVE_TOOLS)
        )
        is_gemini_3 = self._is_gemini_3_family_model(model_id)

        is_background_task = bool(
            metadata.get("task") or (body.get("metadata") or {}).get("task")
        )
        explicit_search_requested = bool(
            features.get("google_search_tool", False)
            or features.get("web_search", False)
        )
        if ocr_mode and self.valves.OCR_DISABLE_GOOGLE_SEARCH:
            explicit_search_requested = False
        last_user_text = self._last_user_text(body)

        auto_search_allowed = (
            self.valves.AUTO_GOOGLE_SEARCH
            and not (ocr_mode and self.valves.OCR_DISABLE_GOOGLE_SEARCH)
            and not disable_auto_search
            and not (self.valves.AUTO_GOOGLE_SEARCH_SKIP_TASKS and is_background_task)
        )

        if auto_search_allowed and self.valves.AUTO_GOOGLE_SEARCH_SMART:
            auto_search_allowed = self._should_auto_google_search(last_user_text)

        # Utility queries such as "what time is it?" should use an available
        # Open WebUI native utility tool instead of web search.
        if (
            auto_search_allowed
            and has_native_tools
            and self._prefer_native_tool_for_query(last_user_text, __tools__)
        ):
            auto_search_allowed = False
            self.log.debug(
                "Automatic Google Search suppressed because a relevant native utility tool is available"
            )

        # Freshness/search intent may select Google grounding even when unrelated
        # native tools are present. The isolation block below removes conflicting
        # native tools unless combined-tool mode was explicitly enabled.
        google_search_requested = bool(explicit_search_requested or auto_search_allowed)
        # Search grounding is a text-generation tool; do not attach it to image
        # generation calls where tool combinations can be model-specific.
        google_search_enabled = google_search_requested and not enable_image_generation

        native_tools_for_request = has_native_tools
        if google_search_enabled and has_native_tools:
            if (
                not is_gemini_3
                or not self.valves.COMBINE_GOOGLE_SEARCH_WITH_NATIVE_TOOLS
            ):
                native_tools_for_request = False
                self.log.info(
                    "Google Search request: omitting native Python tools to avoid "
                    "tool-context/AFC compatibility issues (model=%s)",
                    model_id,
                )

        if google_search_enabled:
            if self.valves.USE_ENTERPRISE_WEB_SEARCH and self.valves.USE_VERTEX_AI:
                self.log.debug("Enabling Enterprise Web Search grounding")
                tools.append(
                    types.Tool(enterprise_web_search=types.EnterpriseWebSearch())
                )
            else:
                self.log.debug(
                    "Enabling Google Search grounding%s",
                    " automatically" if auto_search_allowed else "",
                )
                tools.append(types.Tool(google_search=types.GoogleSearch()))

            if self.valves.ENABLE_URL_CONTEXT_WITH_SEARCH:
                self.log.debug("Enabling URL Context grounding")
                tools.append(types.Tool(url_context=types.UrlContext()))

        if (
            not enable_image_generation
            and self.valves.USE_VERTEX_AI
            and not (ocr_mode and self.valves.OCR_DISABLE_GOOGLE_SEARCH)
        ) and (
            features.get("vertex_ai_search", False)
            or (
                self.valves.USE_VERTEX_AI
                and (
                    self.valves.VERTEX_AI_RAG_STORE or os.getenv("VERTEX_AI_RAG_STORE")
                )
            )
        ):
            vertex_rag_store = (
                params.get("vertex_rag_store")
                or self.valves.VERTEX_AI_RAG_STORE
                or os.getenv("VERTEX_AI_RAG_STORE")
            )
            if vertex_rag_store:
                self.log.debug(
                    f"Enabling Vertex AI Search grounding: {vertex_rag_store}"
                )
                tools.append(
                    types.Tool(
                        retrieval=types.Retrieval(
                            vertex_ai_search=types.VertexAISearch(
                                datastore=vertex_rag_store
                            )
                        )
                    )
                )
            else:
                self.log.warning(
                    "Vertex AI Search requested but vertex_rag_store not provided in params, valves, or env"
                )

        if __tools__ is not None and native_tools_for_request:
            used_tool_names = set()
            for name, tool_def in __tools__.items():
                if enable_image_generation and self._is_open_webui_image_tool(name):
                    self.log.debug(
                        f"Skipping Open WebUI built-in image tool '{name}' for native Gemini image generation"
                    )
                    continue
                if not name.startswith("_"):
                    tool = (
                        tool_def.get("callable") if isinstance(tool_def, dict) else None
                    )
                    if not callable(tool):
                        self.log.warning(
                            f"Skipping native tool '{name}': callable is unavailable"
                        )
                        continue
                    signature = getattr(tool, "__signature__", None)
                    self.log.debug(f"Adding tool '{name}' with signature {signature}")
                    tools.append(self._named_native_tool(name, tool, used_tool_names))

        if tools:
            gen_config_params["tools"] = tools

        # Gemini 3 built-in + custom tool combinations require tool context
        # circulation. Google explicitly requires:
        #   1) include_server_side_tool_invocations=True
        #   2) function calling mode VALIDATED (AUTO is unsupported in this mode)
        #
        # Some Open WebUI images ship an older google-genai build where ToolConfig
        # may accept the field but fail to serialize it. Therefore we set the typed
        # config AND, by default, inject the exact REST field via HttpOptions.extra_body.
        if (
            google_search_enabled
            and native_tools_for_request
            and is_gemini_3
            and self.valves.COMBINE_GOOGLE_SEARCH_WITH_NATIVE_TOOLS
        ):
            typed_tool_config_ok = False
            try:
                gen_config_params["tool_config"] = types.ToolConfig(
                    include_server_side_tool_invocations=True,
                    function_calling_config=types.FunctionCallingConfig(
                        mode="VALIDATED"
                    ),
                )
                typed_tool_config_ok = True
                self.log.debug(
                    "Enabled Gemini 3 tool context circulation with VALIDATED function calling"
                )
            except (AttributeError, TypeError, ValueError) as tool_config_error:
                self.log.warning(
                    "Typed ToolConfig does not support Gemini 3 tool context circulation: %s",
                    tool_config_error,
                )

            if self.valves.TOOL_COMBINATION_RAW_FALLBACK:
                # extra_body is merged AFTER SDK conversion: use REST camelCase.
                raw_tool_config = {
                    "toolConfig": {
                        "includeServerSideToolInvocations": True,
                        "functionCallingConfig": {"mode": "VALIDATED"},
                    }
                }
                try:
                    gen_config_params["http_options"] = types.HttpOptions(
                        extra_body=raw_tool_config
                    )
                    self.log.debug(
                        "Injected raw toolConfig context-circulation fields via HttpOptions.extra_body"
                    )
                except (AttributeError, TypeError, ValueError) as http_options_error:
                    self.log.warning(
                        "HttpOptions.extra_body fallback is unavailable in installed google-genai: %s",
                        http_options_error,
                    )
                    if not typed_tool_config_ok:
                        self.log.warning(
                            "Neither typed ToolConfig nor raw extra_body fallback is available; "
                            "the request may need a compatibility retry without automatic Search."
                        )

        # Filter out None values for generation config
        filtered_params = {k: v for k, v in gen_config_params.items() if v is not None}
        return types.GenerateContentConfig(**filtered_params)

    @staticmethod
    def _is_tool_context_circulation_error(error: Exception) -> bool:
        """Return True for Gemini 3 built-in + function tool context errors."""
        message = str(error).lower()
        return (
            "include_server_side_tool_invocations" in message
            or "includeserversidetoolinvocations" in message
            or ("built-in tools" in message and "function calling" in message)
        )

    @staticmethod
    def _format_grounding_chunks_as_sources(
        grounding_chunks: list[types.GroundingChunk],
    ):
        formatted_sources = []
        for chunk in grounding_chunks:
            if hasattr(chunk, "retrieved_context") and chunk.retrieved_context:
                context = chunk.retrieved_context
                formatted_sources.append(
                    {
                        "source": {
                            "name": getattr(context, "title", None) or "Document",
                            "type": "vertex_ai_search",
                            "uri": getattr(context, "uri", None),
                        },
                        "document": [getattr(context, "chunk_text", None) or ""],
                        "metadata": [
                            {"source": getattr(context, "title", None) or "Document"}
                        ],
                    }
                )
            elif hasattr(chunk, "web") and chunk.web:
                context = chunk.web
                uri = context.uri
                title = context.title or "Source"

                formatted_sources.append(
                    {
                        "source": {
                            "name": title,
                            "type": "web_search_results",
                            "url": uri,
                        },
                        "document": ["Click the link to view the content."],
                        "metadata": [{"source": title}],
                    }
                )
        return formatted_sources

    async def _process_grounding_metadata(
        self,
        grounding_metadata_list: List[types.GroundingMetadata],
        text: str,
        __event_emitter__: Callable,
    ):
        """Process and emit grounding metadata events."""
        grounding_chunks = []
        web_search_queries = []
        grounding_supports = []

        for metadata in grounding_metadata_list:
            if metadata.grounding_chunks:
                grounding_chunks.extend(metadata.grounding_chunks)
            if metadata.web_search_queries:
                web_search_queries.extend(metadata.web_search_queries)
            if metadata.grounding_supports:
                grounding_supports.extend(metadata.grounding_supports)

        # Add sources to the response.
        # Emit each source individually via the "source" event type so that
        # citations are persisted by Open WebUI across page refreshes.
        # A "chat:completion" event with a "sources" payload renders citations
        # in the live response but is not stored with the message.
        if grounding_chunks:
            sources = self._format_grounding_chunks_as_sources(grounding_chunks)
            for source in sources:
                await self._emit_optional(
                    __event_emitter__, {"type": "source", "data": source}
                )

        # Add status specifying google queries used for grounding
        if web_search_queries:
            await self._emit_optional(
                __event_emitter__,
                {
                    "type": "status",
                    "data": {
                        "action": "web_search",
                        "description": "This response was grounded with Google Search",
                        "urls": [
                            f"https://www.google.com/search?q={query}"
                            for query in web_search_queries
                        ],
                    },
                },
            )

        # Add citations in the text body
        replaced_text: Optional[str] = None
        if grounding_supports:
            # Citation indexes are in bytes
            ENCODING = "utf-8"
            text_bytes = text.encode(ENCODING)
            last_byte_index = 0
            cited_chunks = []

            for support in grounding_supports:
                cited_chunks.append(
                    text_bytes[last_byte_index : support.segment.end_index].decode(
                        ENCODING
                    )
                )

                # Generate and append citations (e.g., "[1][2]")
                footnotes = "".join(
                    [f"[{i + 1}]" for i in support.grounding_chunk_indices]
                )
                cited_chunks.append(f" {footnotes}")

                # Update index for the next segment
                last_byte_index = support.segment.end_index

            # Append any remaining text after the last citation
            if last_byte_index < len(text_bytes):
                cited_chunks.append(text_bytes[last_byte_index:].decode(ENCODING))

            replaced_text = "".join(cited_chunks)

        return replaced_text if replaced_text is not None else text

    async def _handle_streaming_response(
        self,
        response_iterator,
        __event_emitter__,
        __request__=None,
        __user__=None,
        *,
        request_started_at=None,
        reasoning_level=None,
        progress_messages=None,
        client=None,
    ):
        started = request_started_at or time.perf_counter()
        stop = asyncio.Event()
        progress = (
            asyncio.create_task(
                self._run_progress_timeline(__event_emitter__, progress_messages, stop)
            )
            if progress_messages
            else None
        )
        answer, thoughts, grounding, unresolved = [], [], [], []
        usage = None
        first = None
        try:
            async for chunk in response_iterator:
                usage = getattr(chunk, "usage_metadata", None) or usage
                feedback = getattr(chunk, "prompt_feedback", None)
                blocked = getattr(feedback, "block_reason", None)
                if blocked:
                    yield f"[Blocked due to Prompt Safety: {blocked}]"
                    return
                candidates = getattr(chunk, "candidates", None) or []
                if not candidates:
                    continue  # Usage-only chunks are not safety blocks.
                candidate = candidates[0]
                if getattr(candidate, "grounding_metadata", None):
                    grounding.append(candidate.grounding_metadata)
                finish = getattr(candidate, "finish_reason", None)
                if str(getattr(finish, "value", finish)) in {
                    "SAFETY",
                    "PROHIBITED_CONTENT",
                }:
                    yield f"[Generation stopped: {finish}]"
                    return
                for part in (
                    getattr(getattr(candidate, "content", None), "parts", None) or []
                ):
                    if getattr(part, "function_call", None):
                        unresolved.append(
                            getattr(part.function_call, "name", "unknown")
                        )
                    elif getattr(part, "text", None):
                        if getattr(part, "thought", False):
                            thoughts.append(part.text)
                        else:
                            if first is None:
                                first = time.perf_counter()
                                stop.set()
                                await self._emit_live_progress(
                                    __event_emitter__, done=True, hidden=True
                                )
                            answer.append(part.text)
                            yield part.text
            if grounding:
                await self._process_grounding_metadata(
                    grounding, "".join(answer), __event_emitter__
                )
            if thoughts and self.valves.PROVIDER_THOUGHT_SUMMARY_IN_RESPONSE:
                details = self._format_provider_thought_details(
                    "".join(thoughts),
                    elapsed_s=time.perf_counter() - started,
                    reasoning_level=reasoning_level,
                )
                if details:
                    yield "\n\n" + details
            if not answer:
                yield (
                    ("[Unresolved tool call: " + ", ".join(unresolved) + "]")
                    if unresolved
                    else "[Gemini returned no answer text]"
                )
            if usage:
                yield {"usage": self._build_usage_dict(usage)}
        except Exception as exc:
            self.log.exception("Streaming failed")
            yield f"\n[Error during streaming: {exc}]"
        finally:
            stop.set()
            if progress:
                progress.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await progress
            close = getattr(response_iterator, "aclose", None)
            if close:
                await close()
            if client is not None:
                await self._close_client(client)
            await self._finish_progress_timing(
                __event_emitter__,
                started_at=started,
                reasoning_level=reasoning_level,
                first_visible_at=first,
            )

    @staticmethod
    def _build_usage_dict(usage_metadata: Any) -> Optional[Dict[str, int]]:
        """Extract token usage from Gemini usage_metadata into a standardised dict."""
        if not usage_metadata:
            return None
        usage: Dict[str, int] = {}
        if getattr(usage_metadata, "prompt_token_count", None) is not None:
            usage["prompt_tokens"] = usage_metadata.prompt_token_count
        if getattr(usage_metadata, "candidates_token_count", None) is not None:
            usage["completion_tokens"] = usage_metadata.candidates_token_count
        if usage:
            usage["total_tokens"] = usage.get("prompt_tokens", 0) + usage.get(
                "completion_tokens", 0
            )
            return usage
        return None

    def _get_safety_block_message(self, response: Any) -> Optional[str]:
        """Check for safety blocks and return appropriate message."""
        # Check prompt feedback
        if response.prompt_feedback and response.prompt_feedback.block_reason:
            return f"[Blocked due to Prompt Safety: {response.prompt_feedback.block_reason.name}]"

        # Check candidates
        if not response.candidates:
            return "[Blocked by safety settings or no candidates generated]"

        # Check candidate finish reason
        candidate = response.candidates[0]
        if candidate.finish_reason == types.FinishReason.SAFETY:
            blocking_rating = next(
                (r for r in (candidate.safety_ratings or []) if r.blocked), None
            )
            reason = f" ({blocking_rating.category.name})" if blocking_rating else ""
            return f"[Blocked by safety settings{reason}]"
        elif candidate.finish_reason == types.FinishReason.PROHIBITED_CONTENT:
            return "[Content blocked due to prohibited content policy violation]"

        return None

    async def _generate_video(
        self,
        body: Dict[str, Any],
        model_id: str,
        __event_emitter__: Callable,
        __request__: Optional[Request] = None,
        __user__: Optional[dict] = None,
        __metadata__: Optional[Dict[str, Any]] = None,
    ) -> Union[str, Dict[str, Any]]:
        """Generate video using Google Veo models (long-running operation with polling)."""

        async def emit_status(description: str, done: bool) -> None:
            if not __event_emitter__:
                return
            try:
                await self._emit_optional(
                    __event_emitter__,
                    {
                        "type": "status",
                        "data": {
                            "action": "video_generation",
                            "description": description,
                            "done": done,
                        },
                    },
                )
            except Exception as e:
                self.log.warning(f"Failed to emit video status event: {e}")

        messages = body.get("messages", [])
        last_user_msg = next(
            (m for m in reversed(messages) if m.get("role") == "user"), None
        )
        if not last_user_msg:
            return "Error: No user message found for video generation"

        prompt, images = await self._extract_images_from_message(last_user_msg)
        if not prompt:
            return "Error: No prompt provided for video generation"

        # Convert first attached image to types.Image for image-to-video
        reference_image = None
        if images:
            first_img = images[0]
            try:
                img_data = first_img.get("inline_data", {})
                raw_data = img_data.get("data", "")
                img_bytes = base64.b64decode(raw_data)
                reference_image = types.Image(
                    image_bytes=img_bytes,
                    mime_type=img_data.get("mime_type", "image/png"),
                )
                self.log.debug("Using attached image for image-to-video generation")
            except Exception as e:
                self.log.warning(f"Failed to convert image for Veo: {e}")

        config = self._build_video_generation_config(body, __user__, model_id=model_id)

        await emit_status(f"Starting video generation with {model_id}...", False)

        client = self._get_client()
        try:
            generate_kwargs: Dict[str, Any] = {
                "model": model_id,
                "prompt": prompt,
                "config": config,
            }
            if reference_image:
                generate_kwargs["image"] = reference_image
            operation = await client.aio.models.generate_videos(**generate_kwargs)
        except Exception as e:
            self.log.exception(f"Video generation request failed: {e}")
            await emit_status(f"Video generation failed: {e}", True)
            return f"Error starting video generation: {e}"

        poll_interval = max(self.valves.VIDEO_POLL_INTERVAL, 5)
        poll_timeout = max(self.valves.VIDEO_POLL_TIMEOUT, 0)
        elapsed = 0
        while not operation.done:
            await asyncio.sleep(poll_interval)
            elapsed += poll_interval
            if poll_timeout > 0 and elapsed >= poll_timeout:
                error_msg = (
                    f"Video generation timed out after {elapsed}s "
                    f"(limit: {poll_timeout}s)"
                )
                self.log.error(error_msg)
                await emit_status(error_msg, True)
                return f"Error: {error_msg}"
            try:
                operation = await client.aio.operations.get(operation)
            except Exception as e:
                self.log.warning(f"Polling error (will retry): {e}")
            await emit_status(f"Generating video... ({elapsed}s elapsed)", False)

        if operation.error:
            error_msg = str(operation.error)
            self.log.error(f"Video generation failed: {error_msg}")
            await emit_status(f"Video generation failed: {error_msg}", True)
            return f"Video generation failed: {error_msg}"

        generated_video_files: List[Dict[str, Any]] = []
        generated_video_links: List[str] = []
        upload_failure_count = 0
        attachment_skipped_count = 0
        response = operation.response
        if not response or not response.generated_videos:
            return "Error: No videos were generated"

        for idx, gen_video in enumerate(response.generated_videos):
            video = gen_video.video
            if not video:
                self.log.warning(f"Video {idx}: no video object in response")
                continue

            self.log.debug(
                f"Video {idx}: uri={getattr(video, 'uri', None)}, "
                f"name={getattr(video, 'name', None)}, "
                f"has_bytes={bool(getattr(video, 'video_bytes', None))}"
            )

            video_bytes = None
            if getattr(video, "video_bytes", None):
                video_bytes = video.video_bytes

            # Download video bytes via SDK (sync version is more reliable)
            if not video_bytes:
                try:
                    await asyncio.to_thread(client.files.download, file=video)
                    video_bytes = getattr(video, "video_bytes", None)
                    self.log.debug(
                        f"Video {idx}: SDK download complete, "
                        f"has_bytes={bool(video_bytes)}"
                    )
                except Exception as dl_err:
                    self.log.warning(f"Video {idx} SDK download failed: {dl_err}")

            # Fallback: save to temp file via SDK
            if not video_bytes:
                tmp_path = None
                try:
                    import tempfile

                    with tempfile.NamedTemporaryFile(
                        suffix=".mp4", delete=False
                    ) as tmp:
                        tmp_path = tmp.name
                    await asyncio.to_thread(video.save, tmp_path)
                    async with aiofiles.open(tmp_path, "rb") as f:
                        video_bytes = await f.read()
                    self.log.debug(
                        f"Video {idx}: temp-file download complete, "
                        f"size={len(video_bytes)} bytes"
                    )
                except Exception as save_err:
                    self.log.warning(f"Video {idx} temp-file save failed: {save_err}")
                finally:
                    if tmp_path:
                        try:
                            os.unlink(tmp_path)
                        except OSError:
                            pass

            if not video_bytes:
                self.log.warning(f"Video {idx}: could not obtain video bytes")
                continue

            mime_type = getattr(video, "mime_type", "video/mp4") or "video/mp4"

            file_entry = None
            video_url = None
            attachment_attempted = False
            if __request__ and __user__:
                attachment_attempted = True
                file_entry, video_url = await self._upload_video_with_status(
                    video_bytes,
                    mime_type,
                    __request__,
                    __user__,
                    __event_emitter__,
                    __metadata__,
                )
            else:
                video_data_b64 = base64.b64encode(video_bytes).decode("utf-8")
                video_url = f"data:{mime_type};base64,{video_data_b64}"

            if file_entry:
                generated_video_files.append(file_entry)
                if video_url:
                    generated_video_links.append(
                        f"[\U0001f3ac Generated Video {idx + 1}]({video_url})"
                    )
                continue

            if attachment_attempted:
                upload_failure_count += 1
            else:
                attachment_skipped_count += 1

            if attachment_attempted and video_url and not video_url.startswith("data:"):
                generated_video_links.append(
                    f"[\U0001f3ac Generated Video {idx + 1}]({video_url})"
                )
            elif attachment_attempted:
                generated_video_links.append(
                    f"Generated video {idx + 1}, but it could not be attached to the chat."
                )
            else:
                generated_video_links.append(f"Generated video {idx + 1}.")

        await emit_status(f"Video generation complete ({elapsed}s)", True)

        files_emitted = await self._emit_generated_video_files(
            generated_video_files, __event_emitter__
        )

        content_parts: List[str] = []
        if generated_video_files and files_emitted:
            video_count = len(generated_video_files)
            content_parts.append(
                "Generated video attached."
                if video_count == 1
                else f"Generated {video_count} videos attached."
            )
        else:
            content_parts.extend(generated_video_links)

        if generated_video_files and not files_emitted:
            content_parts.extend(generated_video_links)

        if upload_failure_count:
            content_parts.append("Some videos could not be attached directly.")

        if attachment_skipped_count:
            content_parts.append(
                "Video attachments were skipped because chat upload context was unavailable."
            )

        content = (
            "\n\n".join(part for part in content_parts if part)
            if content_parts
            else "[No video content generated]"
        )

        return {
            "choices": [{"message": {"role": "assistant", "content": content}}],
        }

    @staticmethod
    async def _close_client(client):
        with contextlib.suppress(Exception):
            await client.aio.aclose()
        with contextlib.suppress(Exception):
            client.close()

    async def _retry_with_backoff(self, func, *args, **kwargs) -> Any:
        """
        Retry a function with exponential backoff.

        Args:
            func: Async function to retry
            *args, **kwargs: Arguments to pass to the function

        Returns:
            Result from the function

        Raises:
            The last exception encountered after all retries
        """
        max_retries = self.valves.RETRY_COUNT
        retry_count = 0
        last_exception = None

        while retry_count <= max_retries:
            try:
                return await func(*args, **kwargs)
            except ServerError as e:
                # These errors might be temporary, so retry
                retry_count += 1
                last_exception = e

                if retry_count <= max_retries:
                    # Calculate backoff time (exponential with jitter)
                    wait_time = min(2**retry_count + (0.1 * retry_count), 10)
                    self.log.warning(
                        f"Temporary error from Google API: {e}. Retrying in {wait_time:.1f}s ({retry_count}/{max_retries})"
                    )
                    await asyncio.sleep(wait_time)
                else:
                    raise
            except Exception:
                # Don't retry other exceptions
                raise

        # If we get here, we've exhausted retries
        assert last_exception is not None
        raise last_exception

    @staticmethod
    async def _emit_optional(emitter, event):
        if emitter:
            try:
                await emitter(event)
            except Exception:
                if event.get("type") == "files":
                    raise  # Let file-event callers use their Markdown fallback.

    async def _emit_live_progress(
        self,
        __event_emitter__: Optional[Callable],
        description: Optional[str] = None,
        *,
        done: bool = False,
        hidden: bool = False,
    ) -> None:
        """Emit one generic Open WebUI status update.

        Intentionally omits a custom ``action`` key. Open WebUI 0.11 renders
        these generic status events in the same compact timeline style used by
        the GPT Responses manifold.
        """
        if not self.valves.LIVE_PROGRESS_STATUS or not __event_emitter__:
            return
        data: Dict[str, Any] = {
            "done": done,
            "hidden": hidden,
        }
        if description:
            data["description"] = description
        try:
            await self._emit_optional(
                __event_emitter__, {"type": "status", "data": data}
            )
        except Exception as emit_error:
            self.log.debug("Failed to emit live progress status: %s", emit_error)

    def _progress_timeline_messages(
        self,
        *,
        body: Dict[str, Any],
        metadata: Optional[Dict[str, Any]],
        ocr_mode: bool,
        supports_image_generation: bool,
        native_tools_active: bool,
    ) -> List[Tuple[float, str]]:
        """Build truthful, user-facing waiting messages.

        These messages describe pipeline activity / waiting state only. They are
        deliberately not presented as Gemini's private reasoning.
        """
        prompt = self._last_user_text(body)
        md = metadata or {}
        features = md.get("features", {}) or {}

        if supports_image_generation:
            if self._is_image_edit_request(prompt):
                return [
                    (0.0, "원본 이미지를 확인하고 있습니다…"),
                    (1.8, "이미지 수정 요청을 준비하고 있습니다…"),
                    (4.5, "Nano Banana 2의 결과를 기다리고 있습니다…"),
                ]
            return [
                (0.0, "이미지 생성 요청을 확인하고 있습니다…"),
                (1.8, "프롬프트와 이미지 설정을 준비하고 있습니다…"),
                (4.5, "Nano Banana 2의 결과를 기다리고 있습니다…"),
            ]

        if ocr_mode:
            return [
                (0.0, "첨부 문서를 확인하고 있습니다…"),
                (1.8, "OCR 전사 조건을 준비하고 있습니다…"),
                (4.5, "Gemini의 문서 판독 결과를 기다리고 있습니다…"),
            ]

        explicit_search = bool(features.get("google_search_tool", False))
        auto_search = bool(
            self.valves.AUTO_GOOGLE_SEARCH and self._should_auto_google_search(prompt)
        )
        file_count, _image_count, _document_count = self._count_request_attachments(
            body, md
        )

        messages: List[Tuple[float, str]] = [
            (0.0, "질문을 읽고 있습니다…"),
            (1.5, "답변 방향을 준비하고 있습니다…"),
        ]

        if file_count > 0:
            messages.append(
                (3.5, f"첨부 자료 {file_count}개를 함께 확인하고 있습니다…")
            )
        elif explicit_search or auto_search:
            messages.append((3.5, "최신 정보가 필요한지 확인하고 있습니다…"))
        elif native_tools_active:
            messages.append((3.5, "필요한 도구 사용을 준비하고 있습니다…"))
        else:
            messages.append((3.5, "관련 내용을 정리하고 있습니다…"))

        messages.extend(
            [
                (6.0, "Gemini의 응답을 기다리고 있습니다…"),
                (9.0, "답변을 마무리하고 있습니다…"),
            ]
        )
        return messages

    def _truncate_provider_thought_summary(self, text: str) -> str:
        clean = str(text or "").strip()
        limit = int(self.valves.PROVIDER_THOUGHT_SUMMARY_MAX_CHARS)
        if len(clean) <= limit:
            return clean
        return clean[:limit].rstrip() + "…"

    def _format_provider_thought_details(
        self,
        thought_text: str,
        *,
        elapsed_s: float,
        reasoning_level: Optional[str],
    ) -> str:
        """Format only provider-returned Gemini thought-summary content."""
        summary = self._truncate_provider_thought_summary(thought_text)
        if not summary:
            return ""
        quoted = "\n".join(f"> {line}" for line in summary.splitlines())
        level_suffix = f" · {reasoning_level}" if reasoning_level else ""
        return (
            "<details>\n"
            f"<summary>Gemini thought summary · {elapsed_s:.1f}s{level_suffix}</summary>\n\n"
            f"{quoted}\n\n"
            "</details>"
        )

    async def _run_progress_timeline(
        self,
        __event_emitter__: Optional[Callable],
        messages: List[Tuple[float, str]],
        stop_event: asyncio.Event,
    ) -> None:
        """Emit delayed progress messages until first visible model output."""
        if (
            not self.valves.LIVE_PROGRESS_STATUS
            or not self.valves.LIVE_PROGRESS_TIMELINE
            or not __event_emitter__
        ):
            return

        started = time.perf_counter()
        for delay_s, message in messages:
            remaining = max(0.0, delay_s - (time.perf_counter() - started))
            if remaining:
                try:
                    await asyncio.wait_for(stop_event.wait(), timeout=remaining)
                    return
                except asyncio.TimeoutError:
                    pass
            if stop_event.is_set():
                return
            await self._emit_live_progress(
                __event_emitter__,
                message,
                done=False,
                hidden=False,
            )

    async def _finish_progress_timing(
        self,
        __event_emitter__: Optional[Callable],
        *,
        started_at: float,
        reasoning_level: Optional[str],
        first_visible_at: Optional[float] = None,
    ) -> None:
        if not self.valves.LIVE_PROGRESS_STATUS or not __event_emitter__:
            return

        elapsed = max(0.0, time.perf_counter() - started_at)
        if self.valves.LIVE_PROGRESS_FINAL_TIMING:
            level_suffix = f" · {reasoning_level}" if reasoning_level else ""
            first_suffix = ""
            if (
                self.valves.LIVE_PROGRESS_FIRST_TOKEN_TIMING
                and first_visible_at is not None
            ):
                first_elapsed = max(0.0, first_visible_at - started_at)
                first_suffix = f" · 첫 응답 {first_elapsed:.1f}s"
            description = (
                f"Thought for {elapsed:.1f} seconds{level_suffix}{first_suffix}"
            )
            await self._emit_live_progress(
                __event_emitter__,
                description,
                done=True,
                hidden=False,
            )
        else:
            await self._emit_live_progress(
                __event_emitter__,
                done=True,
                hidden=True,
            )

    def _get_live_progress_description(
        self,
        *,
        body: Dict[str, Any],
        metadata: Optional[Dict[str, Any]],
        model_id: str,
        ocr_mode: bool,
        supports_image_generation: bool,
        native_tools_active: bool,
    ) -> str:
        """Return a concise Korean status describing the next pipeline stage."""
        if supports_image_generation:
            prompt = self._last_user_text(body)
            if self._is_image_edit_request(prompt):
                return "원본 이미지를 확인하고 수정 작업을 준비하고 있습니다…"
            return "이미지 생성 요청을 준비하고 있습니다…"

        if ocr_mode:
            return "첨부 문서를 확인하고 OCR 전사를 준비하고 있습니다…"

        md = metadata or {}
        features = md.get("features", {}) or {}
        explicit_search = bool(features.get("google_search_tool", False))
        prompt = self._last_user_text(body)
        auto_search = bool(
            self.valves.AUTO_GOOGLE_SEARCH and self._should_auto_google_search(prompt)
        )
        if explicit_search or auto_search:
            return "최신 정보를 확인하기 위해 Google Search를 준비하고 있습니다…"

        if native_tools_active:
            return "요청을 분석하고 필요한 도구 사용을 준비하고 있습니다…"

        file_count, _image_count, _document_count = self._count_request_attachments(
            body, md
        )
        if file_count > 0:
            return f"첨부 자료 {file_count}개를 확인하고 답변을 준비하고 있습니다…"

        return "요청을 분석하고 답변을 준비하고 있습니다…"

    async def pipe(
        self,
        body: Dict[str, Any],
        __metadata__: Optional[dict[str, Any]] = None,
        __event_emitter__: Optional[Callable] = None,
        __tools__: dict[str, Any] | None = None,
        __request__: Optional[Request] = None,
        __user__: Optional[dict] = None,
    ) -> Union[str, Dict[str, Any], AsyncIterator[Union[str, Dict[str, Any]]]]:
        """
        Main method for sending requests to the Google Gemini endpoint.

        Args:
            body: The request body containing messages and other parameters.
            __metadata__: Request metadata
            __event_emitter__: Event emitter for status updates
            __tools__: Available tools
            __request__: FastAPI request object (for image upload)
            __user__: User information (for image upload)

        Returns:
            Response from Google Gemini API, which could be a string or an iterator for streaming.
        """
        body = copy.deepcopy(body)
        __metadata__ = {**(body.get("metadata") or {}), **(__metadata__ or {})}
        last_user = next(
            (
                m
                for m in reversed(body.get("messages") or [])
                if m.get("role") == "user"
            ),
            {},
        )
        __metadata__["files"] = (
            list(__metadata__.get("files") or [])
            + list(body.get("files") or [])
            + list(last_user.get("files") or [])
        )
        # Setup logging for this request
        request_id = id(body)
        request_started_at = time.perf_counter()
        self.log.debug(f"Processing request {request_id}")
        self.log.debug(f"User request body: {__user__}")
        user_token = self._request_user.set(None)
        nonstream_progress_task = None
        client = None
        stream_handed_off = False
        try:
            if __user__ and __user__.get("id"):
                self.user = await Users.get_user_by_id(__user__["id"])
            # Parse and validate model ID. Preserve whether the user selected
            # the Open WebUI-only OCR alias before it is mapped to the real API model.
            requested_model_id = body.get("model", "")
            ocr_mode = self._is_ocr_virtual_model(requested_model_id)
            model_id = requested_model_id
            try:
                model_id = self._prepare_model_id(model_id)
                self.log.debug(f"Using model: {model_id}")
            except ValueError as ve:
                return f"Model Error: {ve}"

            # Auto-route explicit image generation/editing requests from a text
            # Gemini model to Nano Banana 2. OCR and background tasks are excluded.
            metadata = __metadata__ or {}
            is_background_task = bool(
                metadata.get("task") or (body.get("metadata") or {}).get("task")
            )
            if (
                self.valves.AUTO_IMAGE_ROUTING
                and not ocr_mode
                and not is_background_task
                and model_id.startswith("gemini-")
                and not self._check_image_generation_support(model_id)
                and not self._check_video_generation_support(model_id)
            ):
                last_user_text = self._last_user_text(body)
                has_user_image = self._last_user_has_image(body)
                if self._should_auto_image_route(
                    last_user_text, has_image=has_user_image
                ):
                    try:
                        routed_image_model = self._prepare_model_id(
                            self.valves.AUTO_IMAGE_MODEL
                        )
                        if not self._check_image_generation_support(routed_image_model):
                            raise ValueError(
                                "AUTO_IMAGE_MODEL is not an image-generation model: "
                                f"{routed_image_model}"
                            )
                        original_text_model = model_id
                        model_id = routed_image_model
                        self.log.info(
                            "Auto image routing: %s -> %s",
                            original_text_model,
                            model_id,
                        )
                        if self.valves.AUTO_IMAGE_ROUTING_STATUS and __event_emitter__:
                            try:
                                await self._emit_optional(
                                    __event_emitter__,
                                    {
                                        "type": "status",
                                        "data": {
                                            "action": "auto_image_routing",
                                            "description": (
                                                "Image request detected; routing to "
                                                "Nano Banana 2"
                                            ),
                                            "done": True,
                                        },
                                    },
                                )
                            except Exception as emit_error:
                                self.log.debug(
                                    "Failed to emit auto-image routing status: %s",
                                    emit_error,
                                )
                    except ValueError as image_route_error:
                        self.log.warning(
                            "Auto image routing skipped: %s", image_route_error
                        )

            # Route Veo video generation models to dedicated handler
            if self._check_video_generation_support(model_id):
                self.log.debug(f"Routing to video generation for model: {model_id}")
                return await self._generate_video(
                    body,
                    model_id,
                    __event_emitter__,
                    __request__,
                    __user__,
                    __metadata__,
                )

            # Check if this model supports image generation
            supports_image_generation = self._check_image_generation_support(model_id)

            # Get stream flag
            stream = body.get("stream", False)
            if not self.valves.STREAMING_ENABLED:
                if stream:
                    self.log.debug("Streaming disabled via GOOGLE_STREAMING_ENABLED")
                stream = False

            # google-genai automatic Python function calling is reliable in the
            # non-streaming generate_content path, while Gemini 3 streaming can
            # complete a function call with no final text. Open WebUI 0.10+
            # defaults to native function calling when the parameter is absent.
            metadata = __metadata__ or {}
            params = metadata.get("params", {}) or {}
            function_calling_mode = str(
                params.get("function_calling") or "native"
            ).lower()
            native_tools_active = (
                bool(__tools__)
                and function_calling_mode != "legacy"
                and not (ocr_mode and self.valves.OCR_DISABLE_NATIVE_TOOLS)
            )
            if (
                stream
                and native_tools_active
                and self.valves.NATIVE_TOOL_STREAMING_SAFE_MODE
                and not supports_image_generation
            ):
                self.log.info(
                    "Request %s: forcing non-streaming mode because native tools are active",
                    request_id,
                )
                stream = False
                if __event_emitter__:
                    try:
                        await self._emit_optional(
                            __event_emitter__,
                            {
                                "type": "status",
                                "data": {
                                    "action": "tool_call_safe_mode",
                                    "description": (
                                        "Gemini native tools detected; using reliable "
                                        "non-streaming tool-call mode"
                                    ),
                                    "done": True,
                                    "hidden": True,
                                },
                            },
                        )
                    except Exception as emit_error:
                        self.log.debug(
                            f"Failed to emit tool-call safe-mode status: {emit_error}"
                        )

            messages = body.get("messages", [])

            # OCR always sends full attached PDFs; ordinary chat keeps its RAG valve.
            __metadata__["_google_gemini_ocr_full_pdf"] = (
                ocr_mode and not is_background_task
            )

            # For image generation models, gather ALL images from the last user turn
            if supports_image_generation:
                try:
                    (
                        contents,
                        system_instruction,
                    ) = await self._build_image_generation_contents(
                        messages,
                        __event_emitter__,
                        body=body,
                        __metadata__=__metadata__,
                    )
                    # For image generation, system_instruction is integrated into the prompt
                    # so it will be None here (this is expected and correct)
                    self.log.debug(
                        "Image generation mode: system instruction integrated into prompt"
                    )
                except ValueError as ve:
                    return f"Error: {ve}"
            else:
                # For non-image generation models, use the full conversation history
                # Prepare content and extract system message normally
                contents, system_instruction = await self._prepare_content(
                    messages,
                    __metadata__=__metadata__,
                    __event_emitter__=__event_emitter__,
                )
                if not contents:
                    return "Error: No valid message content found"
                self.log.debug(
                    f"Text generation mode: system instruction separate (value: {system_instruction})"
                )

                if ocr_mode:
                    system_instruction = self._apply_ocr_system_prompt(
                        system_instruction
                    )
                    self.log.info(
                        "OCR virtual model enabled: base_model=%s, media_resolution=%s, thinking=%s",
                        model_id,
                        self.valves.OCR_MEDIA_RESOLUTION,
                        self.valves.OCR_THINKING_LEVEL,
                    )
                    if __event_emitter__:
                        try:
                            await self._emit_optional(
                                __event_emitter__,
                                {
                                    "type": "status",
                                    "data": {
                                        "action": "ocr_mode",
                                        "description": (
                                            "OCR mode: Korean-focused visual transcription "
                                            f"({self.valves.OCR_MEDIA_RESOLUTION} media resolution)"
                                        ),
                                        "done": True,
                                        "hidden": True,
                                    },
                                },
                            )
                        except Exception as emit_error:
                            self.log.debug(
                                f"Failed to emit OCR mode status: {emit_error}"
                            )

            # Local Auto Thinking Router (v1.21.0)
            #
            # Priority:
            #   1) explicit per-chat reasoning_effort
            #   2) OCR/image/video dedicated behavior
            #   3) AUTO_THINKING local heuristic
            #   4) THINKING_LEVEL valve
            #   5) Gemini model default
            #
            # No extra API call is made for routing.
            explicit_reasoning_effort = body.get("reasoning_effort")
            auto_thinking_reason = None
            if (
                self.valves.AUTO_THINKING
                and not explicit_reasoning_effort
                and not ocr_mode
                and not supports_image_generation
                and not is_background_task
                and self._is_auto_thinking_candidate_model(model_id)
            ):
                auto_level, auto_thinking_reason = self._select_auto_thinking_level(
                    body, model_id, __metadata__
                )
                if auto_level:
                    body["reasoning_effort"] = auto_level
                    body["_google_auto_thinking"] = True
                    body["_google_auto_thinking_reason"] = auto_thinking_reason
                    self.log.info(
                        "Auto Thinking: model=%s level=%s (%s)",
                        model_id,
                        auto_level,
                        auto_thinking_reason,
                    )
                    if (
                        self.valves.AUTO_THINKING_SHOW_STATUS
                        and not self.valves.LIVE_PROGRESS_STATUS
                        and __event_emitter__
                    ):
                        try:
                            await self._emit_optional(
                                __event_emitter__,
                                {
                                    "type": "status",
                                    "data": {
                                        "action": "auto_thinking",
                                        "description": (f"Auto Thinking: {auto_level}"),
                                        "done": True,
                                        "hidden": False,
                                    },
                                },
                            )
                        except Exception as emit_error:
                            self.log.debug(
                                "Failed to emit Auto Thinking status: %s",
                                emit_error,
                            )
            elif explicit_reasoning_effort:
                self.log.debug(
                    "Auto Thinking bypassed: explicit reasoning_effort=%s",
                    explicit_reasoning_effort,
                )

            # Configure generation parameters and safety settings
            self.log.debug(f"Supports image generation: {supports_image_generation}")
            generation_config = self._configure_generation(
                body,
                system_instruction,
                __metadata__,
                __tools__,
                __user__,
                supports_image_generation,
                model_id,
            )

            selected_reasoning_level = (
                self.valves.OCR_THINKING_LEVEL
                if ocr_mode
                else body.get("reasoning_effort") or self.valves.THINKING_LEVEL or None
            )
            progress_messages = self._progress_timeline_messages(
                body=body,
                metadata=__metadata__,
                ocr_mode=ocr_mode,
                supports_image_generation=supports_image_generation,
                native_tools_active=native_tools_active,
            )
            if (
                self.valves.LIVE_PROGRESS_SHOW_THINKING_LEVEL
                and selected_reasoning_level
                and progress_messages
                and not supports_image_generation
            ):
                delay0, msg0 = progress_messages[0]
                progress_messages[0] = (
                    delay0,
                    f"{msg0.rstrip('…')} · 추론 수준: {selected_reasoning_level}…",
                )

            # Make the API call.
            client = self._get_client()
            if stream:
                # For image generation models, disable streaming to avoid chunk size issues
                if supports_image_generation:
                    self.log.debug(
                        "Disabling streaming for image generation model to avoid chunk size issues"
                    )
                    stream = False
                else:
                    try:

                        async def get_streaming_response():
                            return await client.aio.models.generate_content_stream(
                                model=model_id,
                                contents=contents,
                                config=generation_config,
                            )

                        response_iterator = await self._retry_with_backoff(
                            get_streaming_response
                        )
                        self.log.debug(f"Request {request_id}: Got streaming response")
                        stream_handed_off = True
                        return self._handle_streaming_response(
                            response_iterator,
                            __event_emitter__,
                            __request__,
                            __user__,
                            request_started_at=request_started_at,
                            reasoning_level=selected_reasoning_level,
                            progress_messages=progress_messages,
                            client=client,
                        )

                    except Exception as e:
                        self.log.exception(
                            f"Error in streaming request {request_id}: {e}"
                        )
                        return f"Error during streaming: {e}"

            # Non-streaming path (now also used for image generation)
            if not stream or supports_image_generation:
                try:

                    async def get_response():
                        return await client.aio.models.generate_content(
                            model=model_id,
                            contents=contents,
                            config=generation_config,
                        )

                    # Measure duration for non-streaming path.
                    start_ts = time.time()
                    nonstream_progress_stop = asyncio.Event()
                    nonstream_progress_task: Optional[asyncio.Task] = None
                    if progress_messages:
                        nonstream_progress_task = asyncio.create_task(
                            self._run_progress_timeline(
                                __event_emitter__,
                                progress_messages,
                                nonstream_progress_stop,
                            )
                        )

                    # Send processing status for image generation
                    if supports_image_generation:
                        await self._emit_optional(
                            __event_emitter__,
                            {
                                "type": "status",
                                "data": {
                                    "action": "image_processing",
                                    "description": "Processing image request...",
                                    "done": False,
                                },
                            },
                        )

                    try:
                        # AFC can execute a state-changing tool before a later API failure.
                        response = (
                            await get_response()
                            if native_tools_active
                            else await self._retry_with_backoff(get_response)
                        )
                    except ClientError as first_client_error:
                        # Compatibility safety net for older google-genai builds.
                        # If the SDK still fails to transmit Gemini 3 tool-context
                        # circulation fields, retry once with *automatic* Google
                        # Search disabled. Explicit Search requests remain enabled.
                        if self._is_tool_context_circulation_error(first_client_error):
                            explicit_search_requested = bool(
                                ((__metadata__ or {}).get("features", {}) or {}).get(
                                    "google_search_tool", False
                                )
                                or ((__metadata__ or {}).get("features", {}) or {}).get(
                                    "web_search", False
                                )
                            )
                            if explicit_search_requested:
                                self.log.warning(
                                    "Gemini rejected built-in + function tool combination; "
                                    "retrying once with explicit Google Search only: %s",
                                    first_client_error,
                                )
                                fallback_tools = None
                                fallback_disable_auto_search = False
                                fallback_description = (
                                    "Gemini tool-combination compatibility fallback used; "
                                    "Open WebUI function tools were disabled for this explicit Search request."
                                )
                            else:
                                self.log.warning(
                                    "Gemini rejected built-in + function tool combination; "
                                    "retrying once without automatic Google Search: %s",
                                    first_client_error,
                                )
                                fallback_tools = __tools__
                                fallback_disable_auto_search = True
                                fallback_description = (
                                    "Gemini tool-combination compatibility fallback used; "
                                    "automatic Google Search was disabled for this request."
                                )

                            fallback_config = self._configure_generation(
                                body,
                                system_instruction,
                                __metadata__,
                                fallback_tools,
                                __user__,
                                supports_image_generation,
                                model_id,
                                disable_auto_search=fallback_disable_auto_search,
                            )

                            async def get_fallback_response():
                                return await client.aio.models.generate_content(
                                    model=model_id,
                                    contents=contents,
                                    config=fallback_config,
                                )

                            response = await get_fallback_response()
                            try:
                                await self._emit_optional(
                                    __event_emitter__,
                                    {
                                        "type": "status",
                                        "data": {
                                            "action": "tool_combination_fallback",
                                            "description": fallback_description,
                                            "done": True,
                                        },
                                    },
                                )
                            except Exception:
                                pass
                        else:
                            raise
                    self.log.debug(f"Request {request_id}: Got non-streaming response")
                    nonstream_progress_stop.set()
                    if nonstream_progress_task:
                        nonstream_progress_task.cancel()
                    await self._emit_live_progress(
                        __event_emitter__,
                        done=True,
                        hidden=True,
                    )

                    # Clear processing status for image generation
                    if supports_image_generation:
                        await self._emit_optional(
                            __event_emitter__,
                            {
                                "type": "status",
                                "data": {
                                    "action": "image_processing",
                                    "description": "Processing complete",
                                    "done": True,
                                },
                            },
                        )

                    # Handle "Thinking" and produce final formatted content
                    # Check for safety blocks first
                    safety_message = self._get_safety_block_message(response)
                    if safety_message:
                        return safety_message

                    # Get the first candidate (safety checks passed)
                    candidate = response.candidates[0]

                    # Process content parts - use new streamlined approach
                    parts = getattr(getattr(candidate, "content", None), "parts", [])
                    if not parts:
                        return "[No content generated or unexpected response structure]"

                    answer_segments: list[str] = []
                    thought_segments: list[str] = []
                    function_call_names: list[str] = []
                    generated_images: list[str] = []
                    generated_image_files: List[Dict[str, Any]] = []
                    seen_generated_image_hashes: set[str] = set()

                    for part in parts:
                        function_call = getattr(part, "function_call", None)
                        if function_call:
                            name = (
                                getattr(function_call, "name", None) or "unknown_tool"
                            )
                            function_call_names.append(str(name))
                            self.log.warning(
                                "Gemini response still contains an unresolved function call: %s",
                                name,
                            )
                        elif getattr(part, "thought", False) and getattr(
                            part, "text", None
                        ):
                            thought_segments.append(part.text)
                        elif getattr(part, "text", None):
                            answer_segments.append(part.text)
                        elif (
                            getattr(part, "inline_data", None)
                            and __request__
                            and __user__
                        ):
                            # Handle generated images with unified upload method
                            mime_type = part.inline_data.mime_type
                            image_data = part.inline_data.data

                            self.log.debug(
                                f"Processing generated image: mime_type={mime_type}, data_type={type(image_data)}, data_length={len(image_data)}"
                            )

                            image_hash = self._image_data_hash(image_data)
                            if image_hash in seen_generated_image_hashes:
                                self.log.debug(
                                    "Skipping duplicate generated image part from Gemini response"
                                )
                                continue
                            seen_generated_image_hashes.add(image_hash)

                            image_url = await self._upload_image_with_status(
                                image_data,
                                mime_type,
                                __request__,
                                __user__,
                                __event_emitter__,
                            )
                            if image_url.startswith("data:"):
                                generated_images.append(
                                    f"![Generated Image]({image_url})"
                                )
                            else:
                                generated_image_files.append(
                                    self._build_generated_image_file(
                                        content_url=image_url,
                                        mime_type=mime_type,
                                    )
                                )

                        elif getattr(part, "inline_data", None):
                            # Fallback: return as base64 data URL if no request/user context
                            mime_type = part.inline_data.mime_type
                            image_data = part.inline_data.data

                            image_hash = self._image_data_hash(image_data)
                            if image_hash in seen_generated_image_hashes:
                                self.log.debug(
                                    "Skipping duplicate generated image part from Gemini response"
                                )
                                continue
                            seen_generated_image_hashes.add(image_hash)

                            if isinstance(image_data, bytes):
                                image_data_b64 = base64.b64encode(image_data).decode(
                                    "utf-8"
                                )
                            else:
                                image_data_b64 = str(image_data)

                            data_url = f"data:{mime_type};base64,{image_data_b64}"
                            generated_images.append(f"![Generated Image]({data_url})")

                    final_answer = "".join(answer_segments)

                    # Do not silently return only a thought block when automatic
                    # function calling failed to produce the post-tool answer.
                    if not final_answer.strip() and function_call_names:
                        names = ", ".join(dict.fromkeys(function_call_names))
                        final_answer = (
                            "[Gemini produced an unresolved tool call instead of a final "
                            f"answer: {names}. Check the Open WebUI native-tool callable "
                            "and google-genai version.]"
                        )

                    # Apply grounding (if available) and send sources/status as needed
                    grounding_metadata_list = []
                    if getattr(candidate, "grounding_metadata", None):
                        grounding_metadata_list.append(candidate.grounding_metadata)
                    if grounding_metadata_list:
                        cited = await self._process_grounding_metadata(
                            grounding_metadata_list,
                            final_answer,
                            __event_emitter__,
                        )
                        final_answer = cited or final_answer

                    # Combine all content
                    full_response = ""

                    # If Gemini explicitly returned provider thought-summary parts,
                    # preserve them in a collapsed block. Never synthesize a hidden
                    # reasoning trace when the API returned none.
                    if (
                        thought_segments
                        and self.valves.PROVIDER_THOUGHT_SUMMARY_IN_RESPONSE
                    ):
                        thought_content = "".join(thought_segments).strip()
                        details_block = self._format_provider_thought_details(
                            thought_content,
                            elapsed_s=max(
                                0.0,
                                time.perf_counter() - request_started_at,
                            ),
                            reasoning_level=selected_reasoning_level,
                        )
                        if details_block:
                            full_response += details_block + "\n\n"

                    # Add the main answer
                    full_response += final_answer

                    files_emitted = await self._emit_generated_image_files(
                        generated_image_files, __event_emitter__
                    )

                    if generated_image_files and not files_emitted:
                        generated_images.extend(
                            f"![Generated Image]({image_file['url']})"
                            for image_file in generated_image_files
                        )

                    if (
                        generated_image_files
                        and files_emitted
                        and not final_answer.strip()
                    ):
                        if full_response:
                            full_response += "\n\n"
                        full_response += "Generated image."

                    # Add generated images
                    if generated_images:
                        if full_response:
                            full_response += "\n\n"
                        full_response += "\n\n".join(generated_images)

                    await self._finish_progress_timing(
                        __event_emitter__,
                        started_at=request_started_at,
                        reasoning_level=selected_reasoning_level,
                        first_visible_at=None,
                    )

                    # Build response with usage for middleware to extract and save to DB
                    usage = self._build_usage_dict(
                        getattr(response, "usage_metadata", None)
                    )

                    content = (
                        full_response if full_response else "[No content generated]"
                    )
                    # For text-generation requests, a plain string is the most
                    # reliable Pipe return type in Open WebUI. Returning an
                    # OpenAI-shaped dict here can leave a blank assistant bubble
                    # when native-tool safe mode forced a non-streaming request.
                    if not supports_image_generation:
                        return content

                    result = {
                        "choices": [
                            {"message": {"role": "assistant", "content": content}}
                        ],
                    }
                    if usage:
                        result["usage"] = usage
                    return result

                except Exception as e:
                    self.log.exception(
                        f"Error in non-streaming request {request_id}: {e}"
                    )
                    return f"Error generating content: {e}"

        except (ClientError, ServerError, APIError) as api_error:
            error_type = type(api_error).__name__
            error_msg = f"{error_type}: {api_error}"
            self.log.error(error_msg)
            return error_msg

        except ValueError as ve:
            error_msg = f"Configuration error: {ve}"
            self.log.error(error_msg)
            return error_msg

        except Exception as e:
            # Log the full error with traceback
            import traceback

            error_trace = traceback.format_exc()
            self.log.exception(f"Unexpected error: {e}\n{error_trace}")

            # Return a user-friendly error message
            return f"An error occurred while processing your request: {e}"

        finally:
            if nonstream_progress_task:
                nonstream_progress_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await nonstream_progress_task
            self._request_user.reset(user_token)
            if client is not None and not stream_handed_off:
                await self._close_client(client)
