from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from src.config import SOURCE_PAGE_URL, SOURCE_PRINT_URL


@dataclass(frozen=True)
class SourceDocument:
    content: bytes
    file_hash: str
    source_file_url: str
    source_page_url: str
    edition_date: date | None


def build_http_session() -> requests.Session:
    retry = Retry(
        total=4,
        connect=4,
        read=4,
        backoff_factor=1.2,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET"}),
    )
    adapter = HTTPAdapter(max_retries=retry)
    session = requests.Session()
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (compatible; TerritoriesMonitor/2.0; "
                "+https://github.com/)"
            ),
            "Accept-Language": "uk-UA,uk;q=0.9,en;q=0.6",
        }
    )
    return session


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _parse_ukrainian_date(value: str) -> date | None:
    for pattern in ("%d.%m.%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, pattern).date()
        except ValueError:
            continue
    return None


def extract_edition_date(html: str) -> date | None:
    text = BeautifulSoup(html, "html.parser").get_text(" ", strip=True)
    patterns = (
        r"поточна\s+редакція\s*[—-]?\s*редакція\s+від\s+(\d{2}\.\d{2}\.\d{4})",
        r"поточна\s+редакція\s*[—-]?\s*(\d{2}\.\d{2}\.\d{4})",
        r"редакція\s+від\s+(\d{2}\.\d{2}\.\d{4})",
    )
    lowered = text.lower()
    for pattern in patterns:
        match = re.search(pattern, lowered)
        if match:
            return _parse_ukrainian_date(match.group(1))

    soup = BeautifulSoup(html, "html.parser")
    for selector in (
        ('meta', {"property": "article:modified_time"}),
        ('meta', {"name": "dateModified"}),
    ):
        tag = soup.find(*selector)
        if tag and tag.get("content"):
            raw = str(tag["content"])[:10]
            parsed = _parse_ukrainian_date(raw)
            if parsed:
                return parsed
    return None


def _candidate_docx_links(html: str, base_url: str) -> list[tuple[int, str]]:
    soup = BeautifulSoup(html, "html.parser")
    candidates: list[tuple[int, str]] = []

    for link in soup.find_all("a", href=True):
        href = str(link["href"]).strip()
        absolute = urljoin(base_url, href)
        href_lower = href.lower()
        label = link.get_text(" ", strip=True).lower()

        looks_like_docx = ".docx" in href_lower
        mentions_word = "docx" in label or "word" in label
        if not looks_like_docx and not mentions_word:
            continue

        score = 0
        if looks_like_docx:
            score += 10
        if "перелік" in label:
            score += 4
        if "додат" in label:
            score += 3
        if "зміни" in label:
            score -= 2
        candidates.append((score, absolute))

    return sorted(set(candidates), key=lambda item: item[0], reverse=True)


def discover_current_docx(
    session: requests.Session,
    timeout: int = 60,
) -> tuple[str, str, date | None]:
    errors: list[str] = []
    for page_url in (SOURCE_PRINT_URL, SOURCE_PAGE_URL):
        try:
            response = session.get(page_url, timeout=timeout)
            response.raise_for_status()
            html = response.text
            candidates = _candidate_docx_links(html, page_url)
            if candidates:
                return candidates[0][1], html, extract_edition_date(html)
            errors.append(f"{page_url}: посилання DOCX не знайдено")
        except requests.RequestException as exc:
            errors.append(f"{page_url}: {exc}")

    raise RuntimeError("Не вдалося знайти актуальний DOCX. " + " | ".join(errors))


def download_current_document(timeout: int = 60) -> SourceDocument:
    session = build_http_session()
    docx_url, html, edition_date = discover_current_docx(session, timeout=timeout)
    response = session.get(docx_url, timeout=timeout)
    response.raise_for_status()
    content = response.content

    # DOCX is a ZIP container and normally starts with the PK signature.
    if len(content) < 1000 or not content.startswith(b"PK"):
        content_type = response.headers.get("content-type", "unknown")
        raise RuntimeError(
            "Завантажений файл не схожий на DOCX: "
            f"content-type={content_type}, size={len(content)} bytes"
        )

    return SourceDocument(
        content=content,
        file_hash=sha256_bytes(content),
        source_file_url=docx_url,
        source_page_url=SOURCE_PAGE_URL,
        edition_date=edition_date or extract_edition_date(html),
    )


def load_local_document(path: str | Path, edition_date: date | None = None) -> SourceDocument:
    file_path = Path(path)
    content = file_path.read_bytes()
    if not content.startswith(b"PK"):
        raise ValueError(f"Файл {file_path} не схожий на DOCX.")
    return SourceDocument(
        content=content,
        file_hash=sha256_bytes(content),
        source_file_url=file_path.resolve().as_uri(),
        source_page_url=SOURCE_PAGE_URL,
        edition_date=edition_date,
    )
