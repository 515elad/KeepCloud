"""Mock provider server (hard rule 1).

Answers the OpenAI-compatible chat path from a fixture template. Usage is
computed from the request, so the same request always gets the same answer:

    prompt_tokens     = ceil(bytes of the messages JSON / 4)
    completion_tokens = min(max_tokens, 16 + (SHA-256 of the messages mod 240))
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from keepair.config import Settings


def mock_usage(messages: object, max_tokens: int | None) -> tuple[int, int]:
    raw = json.dumps(messages, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    prompt_tokens = -(-len(raw) // 4)
    wanted = 16 + int.from_bytes(hashlib.sha256(raw).digest()[:4], "big") % 240
    return prompt_tokens, min(max_tokens or wanted, wanted)


def create_mock_provider(fixtures_dir: Path | None = None) -> FastAPI:
    fixtures_dir = fixtures_dir or Settings().fixtures_dir
    template = json.loads((fixtures_dir / "chat_completion.json").read_text(encoding="utf-8"))
    app = FastAPI(title="Mock provider", docs_url=None, redoc_url=None, openapi_url=None)

    @app.get("/healthz")
    def healthz() -> dict:
        return {"status": "alive", "mock": True}

    @app.post("/v1/chat/completions")
    async def chat(request: Request) -> JSONResponse:
        if not request.headers.get("authorization", "").startswith("Bearer "):
            return JSONResponse({"error": {"type": "auth_error"}}, status_code=401)
        body = await request.json()
        prompt_tokens, completion_tokens = mock_usage(body.get("messages"), body.get("max_tokens"))
        answer = copy.deepcopy(template)
        answer["model"] = body.get("model", answer["model"])
        answer["usage"] = {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        }
        return JSONResponse(answer)

    return app
