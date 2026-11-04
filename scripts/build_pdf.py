"""Build report.pdf from report.md.

Pipeline: markdown -> styled HTML (A4, 小四, 1.5 行距) -> Edge headless print-to-pdf.

Run: python scripts/build_pdf.py
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import markdown

ROOT = Path(__file__).resolve().parent.parent
MD_PATH = ROOT / "report.md"
HTML_PATH = ROOT / "report.html"
PDF_PATH = ROOT / "report.pdf"

EDGE = Path("C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe")

CSS = """
@page { size: A4; margin: 20mm 18mm 18mm 18mm;
        @bottom-center { content: counter(page); } }
body { font-family: "Microsoft YaHei","SimSun",serif; font-size: 12pt;
       line-height: 1.5; color: #1a1a1a; max-width: 100%; }
h1 { font-size: 19pt; text-align: center; margin: 0 0 6pt 0; line-height:1.35; }
h2 { font-size: 15pt; margin: 20pt 0 8pt 0; padding-bottom: 4pt;
     border-bottom: 1.5pt solid #1a73e8; page-break-after: avoid; }
h3 { font-size: 13pt; margin: 14pt 0 6pt 0; page-break-after: avoid; }
p { margin: 6pt 0; text-align: justify; }
table { border-collapse: collapse; width: 100%; margin: 10pt 0; font-size: 10.5pt; }
th, td { border: 1px solid #b8bcc2; padding: 5pt 7pt; text-align: left; vertical-align: top; }
th { background: #e8f0fe; font-weight: bold; }
tr:nth-child(even) td { background: #fafbfc; }
code { font-family: Consolas, monospace; font-size: 10pt; background: #f1f3f4;
       padding: 1pt 3pt; border-radius: 2pt; }
pre { background: #f6f8fa; border: 1px solid #d0d7de; border-radius: 4pt;
      padding: 8pt 10pt; font-size: 9.5pt; line-height: 1.35; overflow-x: auto;
      page-break-inside: avoid; }
pre code { background: none; padding: 0; font-size: 9.5pt; }
blockquote { border-left: 3pt solid #f29900; background: #fff8e1; margin: 8pt 0;
             padding: 6pt 10pt; }
img { max-width: 92%; max-height: 145mm; object-fit: contain;
      display: block; margin: 8pt auto; page-break-inside: avoid; }
figure { margin: 12pt 0; text-align: center; page-break-inside: avoid; }
figcaption { font-size: 10.5pt; color: #444; margin-top: 4pt; }
hr { border: none; border-top: 1px solid #d0d7de; margin: 14pt 0; }
strong { color: #0b3d91; }
.toc { background:#f8f9fa; border:1px solid #d0d7de; padding:10pt 16pt; margin:14pt 0; }
"""


def build_html() -> None:
    text = MD_PATH.read_text(encoding="utf-8")

    html_body = markdown.markdown(
        text,
        extensions=["tables", "fenced_code", "toc", "sane_lists", "nl2br"],
    )

    # Wrap images in <figure> with captions derived from alt text.
    html_body = re.sub(r"<p><img alt=\"([^\"]*)\" src=\"([^\"]*)\" ?/?></p>",
                       lambda m: f'<figure><img src="{m.group(2)}" alt="{m.group(1)}">'
                                 f'{"<figcaption>" + m.group(1) + "</figcaption>" if m.group(1) else ""}</figure>',
                       html_body)

    html = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>校园网延迟调查 AI Agent</title>
<style>{CSS}</style></head>
<body>{html_body}</body></html>"""

    HTML_PATH.write_text(html, encoding="utf-8")
    print(f"HTML written: {HTML_PATH}")


def build_pdf() -> None:
    if not EDGE.exists():
        print("Edge not found; cannot print PDF", file=sys.stderr)
        return
    cmd = [
        str(EDGE),
        "--headless=new",
        "--disable-gpu",
        "--no-pdf-header-footer",
        f"--print-to-pdf={PDF_PATH}",
        HTML_PATH.as_uri(),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if PDF_PATH.exists():
        size = PDF_PATH.stat().st_size
        print(f"PDF written: {PDF_PATH} ({size/1024:.0f} KB)")
    else:
        print("PDF generation failed", file=sys.stderr)
        print(result.stdout[-2000:], file=sys.stderr)
        print(result.stderr[-2000:], file=sys.stderr)


if __name__ == "__main__":
    build_html()
    build_pdf()
