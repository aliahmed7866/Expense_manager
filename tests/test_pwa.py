import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_pwa_installability_contract():
    manifest = json.loads((ROOT / "static" / "manifest.webmanifest").read_text(encoding="utf-8"))
    assert manifest["display"] == "standalone"
    assert manifest["start_url"] == "/"
    assert manifest["scope"] == "/"
    assert {"192x192", "512x512"} <= {icon["sizes"] for icon in manifest["icons"]}\n    assert {"192x192", "512x512"} <= {icon["sizes"] for icon in manifest["icons"] if icon["type"] == "image/png"}
    for icon in manifest["icons"]:
        assert (ROOT / icon["src"].lstrip("/")).is_file()

    template = (ROOT / "templates" / "base.html").read_text(encoding="utf-8")
    assert "manifest.webmanifest" in template
    assert "pwa.js" in template

    app_source = (ROOT / "app.py").read_text(encoding="utf-8")
    assert '"/service-worker.js"' in app_source
    assert '"Service-Worker-Allowed"' in app_source

    worker = (ROOT / "static" / "service-worker.js").read_text(encoding="utf-8")
    assert 'event.request.mode==="navigate"' in worker
    assert 'url.pathname.startsWith("/static/")' in worker
