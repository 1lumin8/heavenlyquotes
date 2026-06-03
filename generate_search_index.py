#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

from generate_quote_bank import BOOKS, clean_text


def clean_page_text(value: str) -> str:
    value = clean_text(value)
    value = re.sub(r"[\u200b\u200c\u200d\ufeff]", "", value)
    value = re.sub(r"[|_~`^]+", " ", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def main() -> int:
    pages = []
    for title, accent, source, pdf_name in BOOKS:
      cache_dir = Path("ocr_cache") / Path(pdf_name).stem
      for page_file in sorted(cache_dir.glob("page_*.txt")):
          page_number = int(page_file.stem.split("_")[-1])
          text = clean_page_text(page_file.read_text(encoding="utf-8"))
          if not text:
              continue
          pages.append({
              "title": title,
              "accent": accent,
              "source": source,
              "pdf": pdf_name,
              "page": page_number,
              "text": text,
          })

    data = {
        "generatedAt": datetime.now().isoformat(timespec="seconds"),
        "pages": pages,
    }
    payload = "window.SSN_SEARCH_INDEX = "
    payload += json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    payload += ";\n"
    Path("search-index.js").write_text(payload, encoding="utf-8")
    print(f"{len(pages)} OCR pages indexed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
