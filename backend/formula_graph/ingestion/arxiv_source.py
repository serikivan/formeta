from __future__ import annotations

import gzip
import re
import shutil
import ssl
import subprocess
import tarfile
import tempfile
import urllib.request
import zipfile
from pathlib import Path

from backend.formula_graph.config import settings


ARXIV_ID_RE = re.compile(r"(?P<id>(?:\d{4}\.\d{4,5}|[a-z-]+(?:\.[A-Z]{2})?/\d{7})(?:v\d+)?)", re.IGNORECASE)
_ALLOWED_PREFIXES = (
    "https://arxiv.org/",
    "https://export.arxiv.org/",
    "http://arxiv.org/",
    "http://export.arxiv.org/",
)


def normalize_arxiv_id(value: str | None) -> str | None:
    if not value:
        return None
    match = ARXIV_ID_RE.search(value.strip())
    return match.group("id") if match else None


def fetch_arxiv_source(arxiv_id: str, document_id: str) -> tuple[Path | None, list[str]]:
    safe_id = re.sub(r"[^A-Za-z0-9_.-]+", "_", arxiv_id)
    target_dir = settings.sources_dir / document_id / safe_id
    target_dir.mkdir(parents=True, exist_ok=True)
    archive_path = target_dir / "source"
    extract_dir = target_dir / "extracted"

    url = f"https://arxiv.org/e-print/{arxiv_id}"
    warnings: list[str] = []
    fallback_dir = _source_cache_fallback(safe_id, extract_dir)
    try:
        archive_path.write_bytes(_download(url))
        staged_dir = target_dir / "extracted_download"
        if staged_dir.exists():
            shutil.rmtree(staged_dir)
        staged_dir.mkdir(parents=True, exist_ok=True)
        try:
            _extract_source_archive(archive_path, staged_dir)
        except Exception:
            shutil.rmtree(staged_dir, ignore_errors=True)
            raise
        if extract_dir.exists():
            shutil.rmtree(extract_dir)
        staged_dir.replace(extract_dir)
        return extract_dir, warnings
    except Exception as exc:
        reason = " ".join(str(exc).split())[:240]
        if fallback_dir is not None:
            if fallback_dir != extract_dir:
                if extract_dir.exists():
                    shutil.rmtree(extract_dir)
                shutil.copytree(fallback_dir, extract_dir)
                fallback_dir = extract_dir
            return fallback_dir, [
                f"Не удалось скачать свежий TeX-источник arXiv для {arxiv_id}: {reason}",
                f"Использован локально кэшированный TeX-источник arXiv для {arxiv_id}.",
            ]
        return None, [f"Не удалось скачать TeX-источник arXiv для {arxiv_id}: {reason}"]


def _download(url: str) -> bytes:
    return download_arxiv_url(url, timeout=45)


def download_arxiv_url(url: str, timeout: int = 45) -> bytes:
    contexts = [_default_ssl_context()]
    try:
        contexts.append(ssl.create_default_context(cafile=__import__("certifi").where()))
    except Exception:
        pass
    contexts.append(ssl._create_unverified_context())
    last_error: Exception | None = None
    for candidate in _candidate_arxiv_urls(url):
        for context in contexts:
            try:
                request = urllib.request.Request(candidate, headers={"User-Agent": "formula-graph-ocr/0.1"})
                with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
                    return response.read()
            except Exception as exc:
                last_error = exc
        curl_payload = _download_url_with_curl_fallback(candidate, timeout=timeout)
        if curl_payload is not None:
            return curl_payload
        powershell_payload = _download_url_with_powershell_fallback(candidate, timeout=timeout)
        if powershell_payload is not None:
            return powershell_payload
    assert last_error is not None
    raise last_error


def _default_ssl_context():
    return ssl.create_default_context()


def _candidate_arxiv_urls(url: str) -> list[str]:
    candidates = [url]
    for source_prefix, target_prefix in (
        ("https://export.arxiv.org/", "http://export.arxiv.org/"),
        ("https://arxiv.org/", "http://arxiv.org/"),
        ("https://arxiv.org/", "https://export.arxiv.org/"),
    ):
        if url.startswith(source_prefix):
            candidates.append(target_prefix + url.removeprefix(source_prefix))
    return list(dict.fromkeys(candidates))


def _download_url_with_curl_fallback(url: str, timeout: int = 45) -> bytes | None:
    if not url.startswith(_ALLOWED_PREFIXES):
        return None
    curl = shutil.which("curl")
    if not curl:
        return None
    try:
        completed = subprocess.run(
            [
                curl,
                "--fail",
                "--location",
                "--silent",
                "--show-error",
                "--max-time",
                str(max(5, int(timeout))),
                "--user-agent",
                "formula-graph-ocr/0.1",
                url,
            ],
            check=True,
            capture_output=True,
            timeout=max(10, int(timeout) + 5),
        )
    except Exception:
        return None
    return completed.stdout or None


def _download_url_with_powershell_fallback(url: str, timeout: int = 45) -> bytes | None:
    if not url.startswith(_ALLOWED_PREFIXES):
        return None
    powershell = shutil.which("powershell") or shutil.which("pwsh")
    if not powershell:
        return None
    with tempfile.NamedTemporaryFile(delete=False) as tmp:
        target_path = Path(tmp.name)
    try:
        escaped_url = url.replace("'", "''")
        escaped_target = str(target_path).replace("'", "''")
        command = (
            "$ProgressPreference='SilentlyContinue'; "
            "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; "
            f"Invoke-WebRequest -UseBasicParsing -Uri '{escaped_url}' "
            "-Headers @{'User-Agent'='formula-graph-ocr/0.1'} "
            f"-TimeoutSec {max(5, int(timeout))} -OutFile '{escaped_target}'"
        )
        subprocess.run(
            [powershell, "-NoProfile", "-NonInteractive", "-Command", command],
            check=True,
            capture_output=True,
            timeout=max(10, int(timeout) + 8),
        )
        payload = target_path.read_bytes()
        return payload or None
    except Exception:
        return None
    finally:
        target_path.unlink(missing_ok=True)


def _source_cache_fallback(arxiv_id: str, current_extract_dir: Path) -> Path | None:
    if current_extract_dir.exists() and any(current_extract_dir.rglob("*.tex")):
        return current_extract_dir
    return _existing_extracted_source_dir(arxiv_id, exclude=current_extract_dir)


def _existing_extracted_source_dir(arxiv_id: str, *, exclude: Path | None = None) -> Path | None:
    excluded = exclude.resolve() if exclude is not None else None
    for candidate in settings.sources_dir.rglob("extracted"):
        if excluded is not None and candidate.resolve() == excluded:
            continue
        if candidate.parent.name == arxiv_id and any(candidate.rglob("*.tex")):
            return candidate
    return None


def _extract_source_archive(archive_path: Path, extract_dir: Path) -> None:
    if tarfile.is_tarfile(archive_path):
        with tarfile.open(archive_path) as archive:
            archive.extractall(extract_dir, filter="data")
        return
    if zipfile.is_zipfile(archive_path):
        with zipfile.ZipFile(archive_path) as archive:
            archive.extractall(extract_dir)
        return
    data = archive_path.read_bytes()
    try:
        text = gzip.decompress(data)
    except OSError:
        text = data
    (extract_dir / "source.tex").write_bytes(text)
