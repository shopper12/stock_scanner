from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from chat_picks import (
    add_chat_recommendation,
    build_chat_recommendation_message,
    make_chat_recommendation,
)
from notifier import send_telegram_message

APP_VERSION = "1.0.1"
MAX_ITEMS = 10


def _truthy(value) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _clean_text(value, default: str = "") -> str:
    text = str(value or "").strip()
    return text or default


def _item_to_entry(item: dict) -> dict:
    code = _clean_text(item.get("code") or item.get("ticker"))
    name = _clean_text(item.get("name"))

    if not code or not name:
        raise ValueError("Each item requires code and name.")

    entry = make_chat_recommendation(
        code=code,
        name=name,
        market=_clean_text(item.get("market"), "KRX"),
        sector=_clean_text(item.get("sector"), "기타"),
        strategy_type=_clean_text(item.get("strategy_type"), "custom_gpt_action"),
        current_price=item.get("current_price") or item.get("price_at_recommendation"),
        entry=item.get("entry"),
        entry_low=item.get("entry_low"),
        entry_high=item.get("entry_high"),
        stop_loss=item.get("stop_loss"),
        target1=item.get("target1"),
        target2=item.get("target2"),
        rationale=_clean_text(item.get("rationale") or item.get("reason")),
        risk=_clean_text(item.get("risk")),
        source_note=_clean_text(item.get("source_note"), "Custom GPT Action"),
        recommended_at_kst=item.get("recommended_at_kst"),
    )

    stable_id = _clean_text(item.get("id"))
    if stable_id:
        entry["source_id"] = f"custom_gpt:{stable_id}"

    entry["source"] = "custom_gpt_action"
    return entry


def _save_payload(payload: dict) -> dict:
    items = payload.get("items")

    if not isinstance(items, list) or not items:
        raise ValueError("Request body must include non-empty items array.")

    if len(items) > MAX_ITEMS:
        raise ValueError(f"items length must be <= {MAX_ITEMS}.")

    entries = []
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("Each item must be an object.")
        entries.append(_item_to_entry(item))

    for entry in entries:
        add_chat_recommendation(entry, notify=False)

    notified = False
    if _truthy(payload.get("notify", True)):
        send_telegram_message(
            build_chat_recommendation_message(
                entries,
                title="Custom GPT 추천 저장",
            )
        )
        notified = True

    return {
        "ok": True,
        "saved_count": len(entries),
        "notified": notified,
        "items": [
            {
                "code": entry.get("code"),
                "name": entry.get("name"),
                "source_id": entry.get("source_id"),
            }
            for entry in entries
        ],
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "StockScannerGPTAction/1.0"

    def do_GET(self) -> None:
        path = urlparse(self.path).path.rstrip("/") or "/"

        if path in {"/", "/health"}:
            self._send_json(
                200,
                {
                    "ok": True,
                    "service": "stock_scanner_gpt_action",
                    "version": APP_VERSION,
                    "endpoints": ["/api/chatgpt-picks"],
                    "auth": "none",
                },
            )
            return

        self._send_json(404, {"ok": False, "error": "not_found", "path": path})

    def do_POST(self) -> None:
        path = urlparse(self.path).path.rstrip("/") or "/"

        if path != "/api/chatgpt-picks":
            self._send_json(404, {"ok": False, "error": "not_found", "path": path})
            return

        try:
            payload = self._read_body_json()
            self._send_json(200, _save_payload(payload))
        except Exception as exc:
            self._send_json(
                400,
                {
                    "ok": False,
                    "error": exc.__class__.__name__,
                    "message": str(exc),
                },
            )

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self._send_cors_headers()
        self.end_headers()

    def _read_body_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0") or "0")
        raw = self.rfile.read(length).decode("utf-8") if length else "{}"
        data = json.loads(raw or "{}")

        if not isinstance(data, dict):
            raise ValueError("JSON body must be an object.")

        return data

    def _send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")

        self.send_response(status)
        self._send_cors_headers()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_cors_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def log_message(self, fmt: str, *args) -> None:
        print(f"{self.address_string()} - {fmt % args}")


def main() -> None:
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8010"))

    server = ThreadingHTTPServer((host, port), Handler)
    print(f"Stock Scanner GPT Action API listening on http://{host}:{port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
