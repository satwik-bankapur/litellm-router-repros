"""A tiny OpenAI-compatible provider that misbehaves on command.

Run one per port, for example:
    python fake_provider.py --name primary --port 9101
    python fake_provider.py --name backup  --port 9102

Control it over HTTP:
    POST /control {"mode": "ok"}
    POST /control {"mode": "503", "seconds": 40}     # 503 for 40 s, then healthy
    POST /control {"mode": "429", "retry_after": 1}  # 429 on every call
    POST /control {"mode": "error", "status": 401}   # that status on every call (401, 404, 500, ...)
    POST /control {"mode": "slow", "delay": 3}       # answer after 3 s (to trigger client timeouts)
    POST /reset                                      # clear counters
    GET  /stats                                      # attempts and status log
"""

from __future__ import annotations

import argparse
import asyncio
import threading
import time
import uuid

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

_lock = threading.Lock()
_state: dict = {"mode": "ok", "until": 0.0, "retry_after": 1, "log": []}


def build_app(name: str) -> FastAPI:
    app = FastAPI(title=f"fake-provider-{name}")

    @app.post("/control")
    async def control(request: Request) -> dict:
        body = await request.json()
        with _lock:
            _state["mode"] = body.get("mode", "ok")
            _state["until"] = time.time() + float(body.get("seconds", 0))
            _state["retry_after"] = int(body.get("retry_after", 1))
            _state["delay"] = float(body.get("delay", 0))
            _state["status"] = int(body.get("status", 500))
        return {"ok": True, "mode": _state["mode"]}

    @app.post("/reset")
    async def reset() -> dict:
        with _lock:
            _state["log"] = []
        return {"ok": True}

    @app.get("/stats")
    async def stats() -> dict:
        with _lock:
            log = list(_state["log"])
        return {"name": name, "attempts": len(log), "log": log}

    @app.post("/v1/chat/completions")
    async def chat(request: Request) -> JSONResponse:
        body = await request.json()
        now = time.time()
        with _lock:
            mode = _state["mode"]
            failing = (mode == "503" and now < _state["until"]) or mode == "429"
            status = 200
            if mode == "503" and now < _state["until"]:
                status = 503
            elif mode == "429":
                status = 429
            elif mode == "error":
                status = _state["status"]
            _state["log"].append({"t": round(now, 3), "status": status})
            retry_after = _state["retry_after"]
            delay = _state.get("delay", 0) if mode == "slow" else 0

        if delay:
            await asyncio.sleep(delay)
        if mode == "error":
            return JSONResponse(
                status_code=status,
                content={"error": {"message": f"{name} returned {status}", "type": "invalid_request_error"}},
            )
        if failing and status == 503:
            return JSONResponse(
                status_code=503,
                content={"error": {"message": f"{name} is overloaded", "type": "server_error"}},
            )
        if failing and status == 429:
            return JSONResponse(
                status_code=429,
                headers={"retry-after": str(retry_after)},
                content={"error": {"message": f"{name} rate limited", "type": "rate_limit_error"}},
            )
        return JSONResponse(
            content={
                "id": f"chatcmpl-{uuid.uuid4().hex[:12]}",
                "object": "chat.completion",
                "created": int(now),
                "model": body.get("model", "fake-model"),
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": f"answered by {name}"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8},
            }
        )

    return app


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", required=True)
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    uvicorn.run(build_app(args.name), host="127.0.0.1", port=args.port, log_level="warning")
