"""
Flask backend for the IFC -> BIM_Ontology steel-structure platform.

Run:
    pip install -r requirements.txt
    python app.py
    # then open http://127.0.0.1:5000  (NOT the index.html file directly)

Endpoints:
    GET  /            -> upload UI
    GET  /health      -> {"ok": true}
    POST /analyse     -> multipart 'file' (.ifc); returns JSON analysis + TTL
"""
import os, tempfile, traceback
from flask import Flask, request, jsonify, Response
import engine

HERE = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__)
MAX_MB = 500
app.config["MAX_CONTENT_LENGTH"] = MAX_MB * 1024 * 1024
ALLOWED = {".ifc", ".ifczip"}


@app.route("/")
def index():
    # served as a raw UTF-8 file (no Jinja templating) so CSS/JS braces and
    # unicode glyphs can never break rendering, regardless of platform
    with open(os.path.join(HERE, "templates", "index.html"), encoding="utf-8") as fh:
        return Response(fh.read(), mimetype="text/html")


@app.route("/health")
def health():
    return jsonify({"ok": True})


@app.errorhandler(413)
def too_large(_):
    return jsonify({"error": f"file exceeds the {MAX_MB} MB limit"}), 413


@app.route("/analyse", methods=["POST"])
def analyse():
    if "file" not in request.files:
        return jsonify({"error": "no file uploaded"}), 400
    up = request.files["file"]
    if not up.filename:
        return jsonify({"error": "empty filename"}), 400
    ext = os.path.splitext(up.filename)[1].lower()
    if ext not in ALLOWED:
        return jsonify({"error": f"unsupported extension '{ext}' (expected .ifc)"}), 400

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=ext)
    try:
        up.save(tmp.name)
        tmp.close()
        size_mb = os.path.getsize(tmp.name) / 1048576
        print(f"[analyse] {up.filename}  ({size_mb:.1f} MB)")
        summary, _ = engine.analyse(tmp.name)
        print(f"[analyse] schema={summary['schema']} steel={summary['is_steel']} "
              f"elements={summary['n_elements']} connections={summary['n_connections']}")
        payload = {
            "file": up.filename,
            "schema": summary["schema"],
            "is_steel": summary["is_steel"],
            "reason": summary["reason"],
            "steel_materials": summary["steel_materials"],
            "counts": summary["counts"],
            "n_elements": summary["n_elements"],
            "n_connections": summary["n_connections"],
            "n_joints": summary["n_joints"],
            "n_fastenings": summary["n_fastenings"],
            "n_crossings": summary["n_crossings"],
            "connection_types": summary["connection_types"],
            "notes": summary.get("notes", []),
            "elements": [
                {
                    "id": e["gid"], "class": e["cls"], "ifc_type": e["ifc_type"],
                    "name": e["name"], "storey": e["storey"],
                    "width": e["width"], "height": e["depth"], "thickness": e["thickness"],
                    "length": e["length"], "area": e["area"],
                    "x": e["pos"][0] if e["pos"] else None,
                    "y": e["pos"][1] if e["pos"] else None,
                    "z": e["pos"][2] if e["pos"] else None,
                    "material": ", ".join(e["materials"]) if e["materials"] else None,
                }
                for e in summary["elements"]
            ],
            "connections": [
                {
                    "id": c["id"], "a": c["a"], "b": c["b"],
                    "type": c["ctype"], "kind": c["kind"],
                    "gap": c["gap"], "overlapZ": c["overlapZ"],
                    "contactX": c["contactX"], "contactY": c["contactY"], "contactZ": c["contactZ"],
                }
                for c in summary["connections"]
            ],
            "ttl": engine.to_ttl(summary) if summary["is_steel"] else None,
        }
        return jsonify(payload)
    except MemoryError:
        traceback.print_exc()
        return jsonify({"error": "ran out of memory parsing this model — try a smaller export "
                                 "or a single discipline/storey"}), 500
    except Exception as exc:
        traceback.print_exc()
        return jsonify({"error": f"{type(exc).__name__}: {exc}"}), 500
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass


if __name__ == "__main__":
    url = "http://127.0.0.1:5000"
    print("=" * 60)
    print("  IFC -> BIM Ontology  Steel Structure Analyser")
    print(f"  Open  {url}  in your browser")
    print("  (open this URL, do NOT double-click templates/index.html)")
    print("=" * 60)
    # threaded so a slow parse can't block the health of the server;
    # debug off by default to avoid the reloader killing long requests.
    app.run(host="127.0.0.1", port=5000, debug=False, threaded=True)
