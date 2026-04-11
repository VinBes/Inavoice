import json
import sys

data = json.load(sys.stdin)
read_path = data.get("tool_input", {}).get("file_path", "") or \
            data.get("tool_input", {}).get("path", "")

if ".env" in read_path and not read_path.endswith(".env.example"):
    print("Blocked: cannot read .env files", file=sys.stderr)
    sys.exit(2)
