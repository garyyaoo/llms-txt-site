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
import threading
from queue import Queue

import os
from flask import Flask, Response, request, jsonify, send_from_directory

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
    url, crawl, use_llm, max_urls, max_scrape = _parse_params(body)
    if not url:
        return jsonify({"error": "url is required"}), 400

    try:
        result = run(base_url=url, max_scrape=max_scrape, force_crawl=crawl,
                     use_llm=use_llm, max_urls=max_urls)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    return jsonify(_result_to_dict(result))


# ── SSE streaming endpoint ─────────────────────────────────────────────────────

@app.route("/stream")
def stream():
    url    = request.args.get("url", "").strip()
    crawl  = request.args.get("crawl", "false").lower() == "true"
    use_llm = request.args.get("llm", "false").lower() == "true"
    max_scrape = min(int(request.args.get("max_scrape", 100)), 500)
    max_urls_raw = request.args.get("max_urls")
    max_urls = int(max_urls_raw) if max_urls_raw else None
    discovery_timeout_raw = request.args.get("max_discovery_time")
    discovery_timeout = float(discovery_timeout_raw) if discovery_timeout_raw else None
    max_depth = int(request.args.get("max_depth", 3))

    if not url:
        return jsonify({"error": "url is required"}), 400
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    q = Queue()
    _discovered = []

    def on_progress(url):
        _discovered.append(url)
        q.put({"type": "discovery", "url": url, "count": len(_discovered)})

    def on_phase(name):
        q.put({"type": "phase", "name": name})

    def pipeline():
        try:
            result = run(base_url=url, max_scrape=max_scrape, force_crawl=crawl,
                         use_llm=use_llm, max_urls=max_urls, on_progress=on_progress,
                         on_phase=on_phase, discovery_timeout=discovery_timeout,
                         max_depth=max_depth)
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

def _parse_params(body: dict):
    url = body.get("url", "").strip()
    if url and not url.startswith(("http://", "https://")):
        url = "https://" + url
    crawl      = bool(body.get("crawl", False))
    use_llm    = bool(body.get("llm", False))
    max_scrape = int(body.get("max_scrape", 100))
    max_urls   = int(body.get("max_urls")) if body.get("max_urls") else None
    return url, crawl, use_llm, max_urls, max_scrape


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
