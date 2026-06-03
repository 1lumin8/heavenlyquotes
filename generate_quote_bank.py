#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import warnings
from datetime import datetime
from io import BytesIO
from pathlib import Path

from PIL import Image
from pypdf import PdfReader

warnings.filterwarnings("ignore", message="'pin_memory' argument is set as true.*")


BOOKS = [
    ("예수 그리스도 행전", "accent-green", "PDF 1", "ssn_book_1.pdf"),
    ("요한계시록의 실상", "accent-blue", "PDF 2", "ssn_book_2.pdf"),
    ("십자가의 길", "accent-gold", "PDF 3", "ssn_book_3.pdf"),
]


def has_hangul(value: str) -> bool:
    return bool(re.search(r"[가-힣]", value))


def looks_like_toc_page(lines: list[str]) -> bool:
    if not lines:
        return True
    joined = " ".join(lines)
    compact = re.sub(r"\s+", "", joined)
    if "차례" in compact or "차레" in compact:
        return True
    if len(re.findall(r"\d{1,3}\s*[.)]\s*[가-힣]", joined)) >= 5:
        return True
    if len(re.findall(r"[가-힣][가-힣\s,()·:-]{4,}\s+\d{1,3}(?=\s|$)", joined)) >= 6:
        return True
    toc_markers = sum(1 for line in lines if "차례" in line or re.search(r"\.{3,}", line))
    numbered = sum(1 for line in lines if re.match(r"^\s*\d{1,3}[.)]\s+.+\s+\d{1,4}\s*$", line))
    short_heading_like = sum(1 for line in lines if len(line) < 34 and re.search(r"\d{1,4}\s*$", line))
    return toc_markers >= 1 or numbered >= 4 or short_heading_like >= max(6, len(lines) // 2)


def clean_text(text: str) -> str:
    text = re.sub(r"[\u200b\u200c\u200d\ufeff]", "", text)
    text = re.sub(r"[|_~`^]+", " ", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{2,}", "\n", text)
    return text.strip()


def clean_excerpt(value: str) -> str:
    value = re.sub(r"\s+", " ", value).strip(" -–—·•,;:")
    value = re.sub(r"\[[^\]]*\d+[^\]]*\]", " ", value)
    value = re.sub(r"\([^)]*\d+[^)]*\)", " ", value)
    value = re.sub(r"(?:마|막|눅|요|행|계|히|롬|창|출|고전|고후|벧전|벧후|살전|살후)\s*[:.]\s*[\d\s,\\-~]*", " ", value)
    value = re.sub(r"\d+\s*[-~]\s*\d+\s*절|\d+\s*절", " ", value)
    value = re.sub(r"(?<![가-힣A-Za-z])\d{1,4}(?![가-힣A-Za-z])", " ", value)
    value = re.sub(r"[A-Za-z]+", " ", value)
    value = re.sub(r"\d+", " ", value)
    value = re.sub(r"[()\\[\\]{}<>]", " ", value)
    value = re.sub(r"[^\w\s가-힣.,!?\"'“”]", " ", value)
    value = re.sub(r"[:;]\s*[:;]+", " ", value)
    value = re.sub(r"\s+", " ", value).strip(" -–—·•,;:")
    value = re.sub(r"\s+([.!?])", r"\1", value)
    value = re.sub(r"[:;]+(?=\\s|$)", ".", value)
    value = re.sub(r"([.!?]){2,}", r"\1", value)
    if value and has_hangul(value) and not re.search(r"[.!?。]$", value):
        value += "."
    return value


def looks_like_noise(value: str) -> bool:
    compact = re.sub(r"\s+", "", value)
    if not has_hangul(value):
        return True
    if "차례" in compact or "차레" in compact:
        return True
    if re.search(r"\.{3,}|^제\s*\d+\s*장", value):
        return True
    if len(re.findall(r"\d{1,3}\s*[.)]\s*[가-힣]", value)) >= 2:
        return True
    if len(re.findall(r"[가-힣][가-힣\s,()·:-]{4,}\s+\d{1,3}(?=\s|$)", value)) >= 3:
        return True
    if len(re.findall(r"\d", value)) > 8:
        return True
    if len(re.findall(r"[:;]", value)) > 6:
        return True
    hangul_count = len(re.findall(r"[가-힣]", value))
    ascii_count = len(re.findall(r"[A-Za-z]", value))
    if ascii_count > hangul_count:
        return True
    return False


def has_clean_start(value: str) -> bool:
    value = value.strip(" “\"'([{<")
    if not value:
        return False
    blocked_prefixes = (
        "은 ", "는 ", "이 ", "가 ", "을 ", "를 ", "에 ", "에게 ", "에서 ",
        "으로 ", "로 ", "와 ", "과 ", "도 ", "만 ", "의 ", "며 ", "고 ", "거나 ",
        "그리고 ", "그러나 ", "또한 ", "즉 ", "이는 ", "이것은 ", "그것은 ",
        "그들은 ", "그가 ", "그의 ", "그를 ", "그에게 "
    )
    if value.startswith(blocked_prefixes):
        return False
    if re.match(r"^제\\s*\\W*\\s*\\d*\\s*장", value) or re.match(r"^제\\s+장", value):
        return False
    if re.match(r"^[,.;:!?\\-–—·)]", value):
        return False
    return True


def excerpt_candidates(text: str) -> list[str]:
    text = clean_text(text)
    raw_lines = [line.strip() for line in text.splitlines() if line.strip()]
    lines: list[str] = []
    for line in raw_lines:
        line = clean_excerpt(line)
        if len(line) < 12:
            continue
        if looks_like_noise(line):
            continue
        lines.append(line)

    text = " ".join(lines)
    text = clean_excerpt(text)
    parts = re.split(r"(?<=[.!?。])\s+", text)
    parts = [clean_excerpt(part) for part in parts if clean_excerpt(part)]
    parts = [part for part in parts if len(part) >= 28 and re.search(r"[.!?。]$", part)]

    candidates: list[str] = []
    chunk = ""
    for part in parts:
        if looks_like_noise(part) or not has_clean_start(part):
            continue
        next_chunk = f"{chunk} {part}".strip()
        if len(next_chunk) < 220:
            chunk = next_chunk
            continue
        if len(next_chunk) <= 460:
            candidate = next_chunk
            chunk = ""
        else:
            candidate = chunk if len(chunk) >= 140 else part[:460].strip()
            chunk = part if candidate != part else ""
        candidate = clean_excerpt(candidate)
        if 140 <= len(candidate) <= 500 and re.search(r"[.!?。]$", candidate) and has_clean_start(candidate) and not looks_like_noise(candidate):
            candidates.append(candidate)

    chunk = clean_excerpt(chunk)
    if 140 <= len(chunk) <= 500 and re.search(r"[.!?。]$", chunk) and has_clean_start(chunk) and not looks_like_noise(chunk):
        candidates.append(chunk)

    return candidates


def page_image(page) -> Image.Image | None:
    images = list(page.images)
    if not images:
        return None
    image = Image.open(BytesIO(images[0].data)).convert("RGB")
    image.thumbnail((1000, 1600))
    return image


def tesseract_ocr(image: Image.Image, temp_dir: Path) -> str:
    image_path = temp_dir / "page.jpg"
    image.save(image_path, "JPEG", quality=92)
    language = "kor+eng"
    result = subprocess.run(
        ["tesseract", str(image_path), "stdout", "-l", language, "--psm", "6"],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "Tesseract failed")
    return result.stdout


def easyocr_reader():
    try:
        import easyocr
    except ImportError:
        return None
    return easyocr.Reader(
        ["ko", "en"],
        gpu=False,
        model_storage_directory="/private/tmp/easyocr_models",
        user_network_directory="/private/tmp/easyocr_models",
        verbose=False,
    )


def easyocr_ocr(reader, image: Image.Image, temp_dir: Path) -> str:
    image_path = temp_dir / "page.jpg"
    image.save(image_path, "JPEG", quality=92)
    lines = reader.readtext(str(image_path), detail=0, paragraph=True)
    return "\n".join(lines)


def ocr_engine():
    if os.environ.get("SSN_REPROCESS_ONLY"):
        return "cache", None
    reader = easyocr_reader()
    if reader is not None:
        return "easyocr", reader
    if shutil.which("tesseract"):
        return "tesseract", None
    raise SystemExit(
        "No OCR engine found. Install EasyOCR or Tesseract with Korean language data, then rerun this script."
    )


def build_book(title: str, accent: str, source: str, pdf_name: str, engine_name: str, engine) -> dict:
    pdf_path = Path(pdf_name)
    reader = PdfReader(str(pdf_path))
    quotes: list[dict] = []
    seen: set[str] = set()
    cache_dir = Path("ocr_cache") / pdf_path.stem
    cache_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as raw_temp:
        temp_dir = Path(raw_temp)
        max_pages = int(os.environ.get("SSN_MAX_PAGES", "0") or "0")
        pages = reader.pages[:max_pages] if max_pages else reader.pages
        for page_number, page in enumerate(pages, start=1):
            image = page_image(page)
            if image is None:
                continue
            cache_file = cache_dir / f"page_{page_number:04d}.txt"
            if cache_file.exists():
                text = cache_file.read_text(encoding="utf-8")
            else:
                if engine_name == "cache":
                    continue
                elif engine_name == "easyocr":
                    text = easyocr_ocr(engine, image, temp_dir)
                else:
                    text = tesseract_ocr(image, temp_dir)
                cache_file.write_text(text, encoding="utf-8")
            lines = [line.strip() for line in clean_text(text).splitlines() if line.strip()]
            if looks_like_toc_page(lines):
                continue
            for excerpt in excerpt_candidates("\n".join(lines)):
                key = re.sub(r"\s+", "", excerpt)
                if key in seen:
                    continue
                seen.add(key)
                quotes.append({"text": excerpt, "page": page_number})
            if page_number % 10 == 0 or max_pages:
                print(f"{source}: scanned {page_number}/{len(pages)} pages, {len(quotes)} quotes", flush=True)

    return {
        "title": title,
        "accent": accent,
        "source": source,
        "pdf": pdf_name,
        "quotes": quotes,
    }


def main() -> int:
    engine_name, engine = ocr_engine()
    print(f"Using {engine_name}", flush=True)
    books = [build_book(*book, engine_name, engine) for book in BOOKS]
    data = {
        "generatedAt": datetime.now().isoformat(timespec="seconds"),
        "mode": "full_pdf_ocr",
        "note": "Generated from OCR text extracted from the scanned PDFs.",
        "books": books,
    }
    payload = "window.SSN_QUOTE_BANK = "
    payload += json.dumps(data, ensure_ascii=False, indent=2)
    payload += ";\n"
    Path("quote-bank.js").write_text(payload, encoding="utf-8")
    for book in books:
        print(f"{book['source']}: {len(book['quotes'])} quotes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
