"""
title: Google Gemini RAG Bypass Companion
author: owndev, olivier-lacroix (companion by 나난)
project_url: https://github.com/owndev/Open-WebUI-Functions
version: 1.0.1
required_open_webui_version: 0.9.0
license: Apache License 2.0
description: Companion filter for the Google Gemini pipe (v1.17.0+). Removes attached files from the request BEFORE Open WebUI's backend RAG retrieval runs and stashes them in the request metadata, so the Google Gemini pipe can attach the original documents natively to Gemini. Modeled after the Gemini Manifold Companion filter.
"""

import os
import logging
from typing import Any, Callable, Optional

from pydantic import BaseModel, Field

# Metadata key the Google Gemini pipe looks for (see google_gemini pipe
# `_collect_metadata_files` / `_prepare_content`).
STASH_KEY = "_google_gemini_bypassed_files"

log = logging.getLogger("google_gemini.rag_bypass_filter")
if not log.level:
    log.setLevel(logging.INFO)


class Filter:
    class Valves(BaseModel):
        priority: int = Field(
            default=0,
            description="Filter priority. Lower values run earlier.",
        )
        BYPASS_BACKEND_RAG: bool = Field(
            default=os.getenv("GOOGLE_BYPASS_BACKEND_RAG", "true").lower() == "true",
            description=(
                "Remove attached files from the request before Open WebUI's "
                "backend RAG retrieval runs (no chunking/embedding context is "
                "injected) and stash them in metadata for the Google Gemini "
                "pipe to attach natively."
            ),
        )
        BYPASS_COLLECTIONS: bool = Field(
            default=True,
            description=(
                "Also bypass knowledge collections, sending every file in the "
                "collection natively to Gemini. Warning: large knowledge bases "
                "will be sent in full. If disabled, collections keep using "
                "backend RAG; in that case also disable BYPASS_BACKEND_RAG on "
                "the Google Gemini pipe so the collection context is not "
                "stripped from the prompt."
            ),
        )
        MODEL_ID_PREFIXES: str = Field(
            default="google_gemini",
            description=(
                "Comma-separated model ID prefixes this filter applies to "
                "(matched against the model ID and its base model ID). "
                "Empty applies to all models."
            ),
        )
        SHOW_STATUS: bool = Field(
            default=True,
            description="Emit a status message when files are bypassed.",
        )

    def __init__(self):
        self.valves = self.Valves()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _model_matches(
        self,
        body: dict,
        __model__: Optional[dict],
        __metadata__: Optional[dict],
    ) -> bool:
        prefixes = [
            p.strip()
            for p in (self.valves.MODEL_ID_PREFIXES or "").split(",")
            if p.strip()
        ]
        if not prefixes:
            return True

        candidates: set = set()
        model_id = body.get("model")
        if model_id:
            candidates.add(str(model_id))
        for source in ((__model__ or {}), ((__metadata__ or {}).get("model") or {})):
            if not isinstance(source, dict):
                continue
            for key in ("id", "base_model_id"):
                value = source.get(key)
                if value:
                    candidates.add(str(value))
            info = source.get("info") or {}
            if isinstance(info, dict) and info.get("base_model_id"):
                candidates.add(str(info["base_model_id"]))

        return any(c.startswith(p) for c in candidates for p in prefixes)

    @staticmethod
    def _split_files(files: list, bypass_collections: bool) -> tuple:
        """Split files into (bypassed, kept) lists."""
        bypassed, kept = [], []
        for f in files:
            if not isinstance(f, dict):
                kept.append(f)
                continue
            ftype = f.get("type", "file")
            if ftype == "file" or (ftype == "collection" and bypass_collections):
                bypassed.append(f)
            else:
                kept.append(f)
        return bypassed, kept

    # ------------------------------------------------------------------
    # Inlet
    # ------------------------------------------------------------------
    async def inlet(
        self,
        body: dict,
        __metadata__: Optional[dict] = None,
        __model__: Optional[dict] = None,
        __event_emitter__: Optional[Callable] = None,
    ) -> dict:
        if not self.valves.BYPASS_BACKEND_RAG:
            return body

        # Skip background task requests (title/tags generation, etc.)
        if (__metadata__ or {}).get("task") or (body.get("metadata") or {}).get("task"):
            return body

        files = body.get("files") or []
        if not files:
            return body

        if not self._model_matches(body, __model__, __metadata__):
            log.debug("RAG bypass skipped: model does not match MODEL_ID_PREFIXES")
            return body

        bypassed, kept = self._split_files(files, self.valves.BYPASS_COLLECTIONS)
        if not bypassed:
            return body

        # 1. Remove bypassed files from the request body so the backend RAG
        #    pipeline never retrieves/injects context for them.
        #    (Rebind, don't clear: other dicts may reference the original list.)
        body["files"] = kept

        # 2. Stash the bypassed files in every reachable metadata dict so the
        #    Google Gemini pipe can pick them up regardless of Open WebUI
        #    version differences in how metadata is threaded through.
        stash_targets = []
        if isinstance(__metadata__, dict):
            stash_targets.append(__metadata__)
        body_metadata = body.get("metadata")
        if isinstance(body_metadata, dict) and body_metadata is not __metadata__:
            stash_targets.append(body_metadata)
        if not stash_targets:
            stash_targets.append(body.setdefault("metadata", {}))

        for md in stash_targets:
            md[STASH_KEY] = bypassed
            # Keep metadata "files" consistent with the body to prevent any
            # metadata-based retrieval path from processing bypassed files.
            md["files"] = kept
            features = md.get("features")
            if isinstance(features, dict):
                features["google_gemini_rag_bypass"] = True
            else:
                md["features"] = {"google_gemini_rag_bypass": True}

        log.info(
            f"RAG bypass: stashed {len(bypassed)} attachment(s) for native "
            f"handling, {len(kept)} left for backend RAG"
        )

        if self.valves.SHOW_STATUS and __event_emitter__:
            try:
                await __event_emitter__(
                    {
                        "type": "status",
                        "data": {
                            "action": "rag_bypass",
                            "description": (
                                f"Backend RAG bypassed for {len(bypassed)} "
                                "attachment(s); sending natively to Gemini"
                            ),
                            "done": True,
                        },
                    }
                )
            except Exception as emit_error:
                log.debug(f"Failed to emit RAG bypass status: {emit_error}")

        return body
