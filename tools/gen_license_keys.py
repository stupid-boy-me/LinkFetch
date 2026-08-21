"""Generate LinkFetch one-time license keys for sale.

Usage:
  .venv\\Scripts\\python.exe tools\\gen_license_keys.py 20
  .venv\\Scripts\\python.exe tools\\gen_license_keys.py 20 -o keys.txt

Keep this script private. Do not publish generated keys.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from linkfetch.license_gate import generate_key, verify_key_format  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description="Generate LinkFetch buyout license keys")
    ap.add_argument("count", type=int, nargs="?", default=1, help="how many keys (default: 1)")
    ap.add_argument("-o", "--output", default="", help="optional output file")
    args = ap.parse_args()
    n = max(1, min(int(args.count), 5000))
    keys: list[str] = []
    seen: set[str] = set()
    while len(keys) < n:
        k = generate_key()
        if k in seen:
            continue
        assert verify_key_format(k)
        seen.add(k)
        keys.append(k)
    text = "\n".join(keys) + "\n"
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
        print(f"Wrote {n} keys -> {args.output}")
    else:
        print(text, end="")


if __name__ == "__main__":
    main()
