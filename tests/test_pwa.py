import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_pwa_installability_contract():
    manifest = json.loads((ROOT / "static" / "manifest.webmanifest").read_text(encoding="utf-8"))
    assert manifest["display"] == "standalone"
    assert manifest["start_url"] == "/"
    assert manifest["scope"] == "/"
    assert {"192x192", "512x512"} <= {icon["sizes"] for icon in manifest["icons"]}
    assert {"192x192", "512x512"} <= {icon["sizes"] for icon in manifest["icons"] if icon["type"] == "image/png"}
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


def test_install_helper_waits_for_active_worker():
    scripts = [ROOT / "static" / "pwa.js"]
    admin_script = ROOT / "termux" / "static" / "admin-pwa.js"
    if admin_script.exists():
        scripts.append(admin_script)
    for script in scripts:
        source = script.read_text(encoding="utf-8")
        assert "navigator.serviceWorker.ready" in source
        assert "navigator.serviceWorker.controller" in source
        assert "beforeinstallprompt" in source
        assert "Add to Home screen" not in source
