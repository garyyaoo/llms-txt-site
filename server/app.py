"""
Flask server for llms.txt generation.

POST /generate          — blocking, returns full result
GET  /stream?url=...    — SSE stream of progress events + final result

SSE event types:
  {"type": "discovery", "count": N}   — URL count updating during discovery
  {"type": "done", "llms_txt": "...", "why": "..."}
  {"type": "error", "message": "..."}
"""
import json
import logging
import os
import threading
from queue import Queue

from flask import Flask, Response, request, jsonify, send_from_directory

logging.basicConfig(level=logging.INFO, format="%(name)s %(levelname)s %(message)s")

from main import run

_STATIC = os.path.join(os.path.dirname(__file__), "fe/dist")

app = Flask(__name__, static_folder=_STATIC, static_url_path="")

_SENTINEL = object()


def _cors(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return response


@app.after_request
def after_request(response):
    return _cors(response)


# ── Blocking endpoint (kept for non-streaming clients) ────────────────────────

@app.route("/generate", methods=["POST", "OPTIONS"])
def generate():
    if request.method == "OPTIONS":
        return jsonify({}), 200

    body = request.get_json(force=True, silent=True) or {}
    params = _parse_params(body)
    if not params["url"]:
        return jsonify({"error": "url is required"}), 400

    try:
        result = run(base_url=params["url"], max_scrape=params["max_scrape"],
                     force_crawl=params["crawl"], use_llm=params["use_llm"],
                     max_urls=params["max_urls"])
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    return jsonify(_result_to_dict(result))


# ── SSE streaming endpoint ─────────────────────────────────────────────────────

@app.route("/stream")
def stream():
    params = _parse_params(request.args)
    url = params["url"]

    if not url:
        return jsonify({"error": "url is required"}), 400

    q = Queue()
    _discovered = []

    def on_progress(url):
        _discovered.append(url)
        q.put({"type": "discovery", "url": url, "count": len(_discovered)})

    def on_phase(name):
        q.put({"type": "phase", "name": name})

    def pipeline():
        try:
            result = run(base_url=url, max_scrape=params["max_scrape"], force_crawl=params["crawl"],
                         use_llm=params["use_llm"], max_urls=params["max_urls"], on_progress=on_progress,
                         on_phase=on_phase, discovery_timeout=params["discovery_timeout"],
                         max_depth=params["max_depth"])
            q.put({"type": "done", **_result_to_dict(result)})
        except Exception as e:
            q.put({"type": "error", "message": str(e)})
        finally:
            q.put(_SENTINEL)

    threading.Thread(target=pipeline, daemon=True).start()

    def event_stream():
        while True:
            item = q.get()
            if item is _SENTINEL:
                break
            yield f"data: {json.dumps(item)}\n\n"

    return Response(event_stream(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_params(source) -> dict:
    """Parse request parameters from either a JSON body dict or request.args."""
    def _bool(key, default=False):
        val = source.get(key, default)
        return val if isinstance(val, bool) else str(val).lower() == "true"

    def _int(key, default):
        val = source.get(key)
        return int(val) if val is not None else default

    def _float(key):
        val = source.get(key)
        return float(val) if val is not None else None

    url = (source.get("url") or "").strip()
    if url and not url.startswith(("http://", "https://")):
        url = "https://" + url

    return {
        "url":               url,
        "crawl":             _bool("crawl"),
        "use_llm":           _bool("llm"),
        "max_scrape":        min(_int("max_scrape", 100), 500),
        "max_urls":          _int("max_urls", None),
        "discovery_timeout": _float("max_discovery_time"),
        "max_depth":         _int("max_depth", 3),
    }


def _result_to_dict(result) -> dict:
    d = {"llms_txt": result["llms_txt"]}
    if result.get("why"):
        d["why"] = result["why"]
    if result.get("insights"):
        d["insights"] = result["insights"]
    return d


@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def serve_frontend(path):
    if path and os.path.exists(os.path.join(_STATIC, path)):
        return send_from_directory(_STATIC, path)
    return send_from_directory(_STATIC, "index.html")


if __name__ == "__main__":
    app.run(debug=True, port=5001, threaded=True)
