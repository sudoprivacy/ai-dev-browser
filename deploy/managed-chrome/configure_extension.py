"""Package the public bridge for Chrome's supported Linux policy installation.

Run only while constructing the isolated runtime image. The Chrome profile
remains outside the image; no user profile or credentials are copied here.
"""

import hashlib
import json
import pathlib
import re
import subprocess
import sys
import xml.etree.ElementTree as ET

root = pathlib.Path("/opt/browser")
key = pathlib.Path(sys.argv[1])
assert key.is_file(), "An administrator-owned stable extension signing key is required"
source = root / "sdk/ai_dev_browser/extension"
output = root / "extension"
output.mkdir()
packed = subprocess.run(
    [
        "google-chrome",
        "--no-sandbox",
        "--headless=new",
        f"--pack-extension={source}",
        f"--pack-extension-key={key}",
    ],
    capture_output=True,
    timeout=30,
)
if packed.returncode:
    raise RuntimeError(packed.stderr.decode(errors="replace"))
# Derive the extension ID from its generated signing public key. This is a
# runtime-image identity, unrelated to any user's private key or browser data.
public = subprocess.check_output(
    [
        "openssl",
        "pkey",
        "-in",
        str(key),
        "-pubout",
        "-outform",
        "DER",
    ],
)
extension_id = "".join(
    chr(ord("a") + int(nibble, 16))
    for nibble in hashlib.sha256(public).hexdigest()[:32]
)
assert re.fullmatch("[a-p]{32}", extension_id)
version = json.loads((source / "manifest.json").read_text())["version"]
source.with_suffix(".crx").replace(output / "bridge.crx")
update = ET.Element(
    "gupdate", xmlns="http://www.google.com/update2/response", protocol="2.0"
)
app = ET.SubElement(update, "app", appid=extension_id)
ET.SubElement(
    app, "updatecheck", codebase="http://127.0.0.1:8080/bridge.crx", version=version
)
ET.ElementTree(update).write(
    output / "update.xml", encoding="utf-8", xml_declaration=True
)
(output / "identity.json").write_text(
    json.dumps({"id": extension_id, "version": version})
)
policy = {
    "3rdparty": {"extensions": {extension_id: {"ManagedBrowserProfile": True}}},
    "ExtensionSettings": {
        extension_id: {
            "installation_mode": "force_installed",
            "update_url": "http://127.0.0.1:8080/update.xml",
            "override_update_url": True,
            "minimum_version_required": version,
        }
    },
}
pathlib.Path("/etc/opt/chrome/policies/managed/ai-dev-browser.json").write_text(
    json.dumps(policy)
)
