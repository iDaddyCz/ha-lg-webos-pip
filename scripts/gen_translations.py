"""Expands [%key:...%] references in strings.json into translations/en.json.

Home Assistant resolves these references only for core integrations, so a
custom integration has to ship the expanded file.

    python3 scripts/gen_translations.py          # write
    python3 scripts/gen_translations.py --check  # fail if out of date (CI)
"""

from __future__ import annotations

import json
from pathlib import Path
import re
import sys

COMPONENT = Path(__file__).resolve().parent.parent / "custom_components" / "lg_webos_pip"
REF = re.compile(r"^\[%key:component::lg_webos_pip::(.+)%\]$")


def expand(node, root):
    if isinstance(node, dict):
        return {k: expand(v, root) for k, v in node.items()}
    if isinstance(node, str) and (m := REF.match(node)):
        target = root
        for part in m.group(1).split("::"):
            target = target[part]
        return expand(target, root)
    return node


def main() -> int:
    strings = json.loads((COMPONENT / "strings.json").read_text())
    out = json.dumps(expand(strings, strings), indent=2, ensure_ascii=False) + "\n"
    target = COMPONENT / "translations" / "en.json"
    if "--check" in sys.argv:
        if not target.exists() or target.read_text() != out:
            print("translations/en.json is out of date: run python3 scripts/gen_translations.py")
            return 1
        return 0
    target.parent.mkdir(exist_ok=True)
    target.write_text(out)
    print(f"wrote {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
