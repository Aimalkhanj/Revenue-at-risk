"""Step 3 - inject the analysis results into the dashboard template and write a standalone web page."""
import json, sys
from pathlib import Path
import pandas as pd
ROOT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[1]
d = json.loads((ROOT / "data" / "dashboard_data.json").read_text())
d["cleaning"] = pd.read_csv(ROOT / "data" / "cleaning_log.csv").to_dict("records")
tpl = (ROOT / "dashboard" / "template.html").read_text()
body = tpl.replace("/*__DATA__*/null", json.dumps(d, separators=(",", ":"), default=float))
cut = body.index('<div class="board">')
page = ('<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
        '<style>html{color-scheme:light}body{margin:0}[hidden]{display:none!important}img{max-width:100%}</style>\n'
        + body[:cut] + '</head>\n<body>\n' + body[cut:] + '\n</body>\n</html>\n')
for out in (ROOT / "dashboard" / "revenue-at-risk.html", ROOT / "index.html"):
    out.write_text(page)
print("built", len(page) // 1024, "KB")
