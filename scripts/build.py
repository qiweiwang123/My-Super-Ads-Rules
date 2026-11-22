#!/usr/bin/env python3
"""Download, merge and compile sing-box rule-set sources safely and reproducibly."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

MAX_VERSION = 5
DEFAULT_MAX_DOWNLOAD_BYTES = 64 * 1024 * 1024
DEFAULT_TIMEOUT_SECONDS = 60


class BuildError(Exception):
    """An actionable input, download, or sing-box error."""


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def validate_https_url(value: Any, label: str) -> str:
    if not isinstance(value, str):
        raise BuildError(f"{label}: URL must be a string")
    parsed = urllib.parse.urlsplit(value)
    if parsed.scheme.lower() != "https" or not parsed.hostname:
        raise BuildError(f"{label}: only public HTTPS URLs are accepted")
    if parsed.username is not None or parsed.password is not None:
        raise BuildError(f"{label}: credentials must not be embedded in URLs")
    return value


def download_source(url: str, max_bytes: int, timeout: int) -> tuple[bytes, str]:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "srs-auto-merge/1.0", "Accept": "application/json, application/octet-stream"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            final_url = response.geturl()
            validate_https_url(final_url, "redirect destination")
            body = response.read(max_bytes + 1)
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        raise BuildError(f"download failed for {safe_host(url)}: {exc}") from exc
    if len(body) > max_bytes:
        raise BuildError(f"download from {safe_host(url)} exceeds the configured {max_bytes}-byte limit")
    if not body:
        raise BuildError(f"download from {safe_host(url)} was empty")
    return body, final_url


def safe_host(url: str) -> str:
    return urllib.parse.urlsplit(url).hostname or "unknown host"


def load_rule_set(data: bytes, requested_format: str, name: str, temp_dir: Path,
                  sing_box: Path, index: int) -> tuple[dict[str, Any], str]:
    detected = requested_format
    text = None
    if requested_format == "auto":
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = None
        detected = "json" if text is not None and text.lstrip().startswith("{") else "srs"

    if detected == "json":
        if text is None:
            try:
                text = data.decode("utf-8-sig")
            except UnicodeDecodeError as exc:
                raise BuildError(f"{name}: source marked JSON is not UTF-8") from exc
        try:
            document = json.loads(text)
        except json.JSONDecodeError as exc:
            raise BuildError(f"{name}: invalid source JSON: {exc}") from exc
    elif detected == "srs":
        binary_path = temp_dir / f"source-{index}.srs"
        json_path = temp_dir / f"source-{index}.json"
        binary_path.write_bytes(data)
        run_sing_box(sing_box, "rule-set", "decompile", str(binary_path), "-o", str(json_path))
        try:
            document = json.loads(json_path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError) as exc:
            raise BuildError(f"{name}: sing-box did not produce valid source JSON: {exc}") from exc
    else:
        raise BuildError(f"{name}: format must be auto, json, or srs")

    validate_source_document(document, name)
    return document, detected


def validate_source_document(document: Any, name: str) -> None:
    if not isinstance(document, dict):
        raise BuildError(f"{name}: rule-set source must be a JSON object")
    version = document.get("version")
    if not isinstance(version, int) or isinstance(version, bool) or not 1 <= version <= MAX_VERSION:
        raise BuildError(f"{name}: unsupported source version {version!r}; expected 1..{MAX_VERSION}")
    rules = document.get("rules")
    if not isinstance(rules, list):
        raise BuildError(f"{name}: source must contain a rules array")
    for position, rule in enumerate(rules, start=1):
        if not isinstance(rule, dict):
            raise BuildError(f"{name}: rule {position} must be an object")
        if not rule:
            raise BuildError(f"{name}: rule {position} is empty and would match all traffic")


def merge_rules(documents: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    input_count = 0
    for document in documents:
        for rule in document["rules"]:
            input_count += 1
            key = canonical_json(rule)
            if key not in seen:
                seen.add(key)
                merged.append(rule)
    return merged, input_count


def run_sing_box(executable: Path, *args: str) -> str:
    try:
        result = subprocess.run(
            [str(executable), *args], check=True, capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=180,
        )
    except FileNotFoundError as exc:
        raise BuildError(f"sing-box executable not found: {executable}") from exc
    except subprocess.TimeoutExpired as exc:
        raise BuildError(f"sing-box command timed out: {' '.join(args)}") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or str(exc)).strip()
        raise BuildError(f"sing-box command failed ({' '.join(args)}): {detail}") from exc
    return (result.stdout or "") + (result.stderr or "")


def verify_compiler_version(sing_box: Path, expected: str | None) -> None:
    output = run_sing_box(sing_box, "version")
    match = re.search(r"sing-box version\s+(\S+)", output)
    if not match:
        raise BuildError("could not read the sing-box version")
    actual = match.group(1)
    if expected and actual != expected:
        raise BuildError(f"sing-box version mismatch: expected {expected}, got {actual}")


def build(config_path: Path, output_dir: Path, sing_box: Path,
          expected_sing_box_version: str | None = None) -> dict[str, Any]:
    try:
        config = json.loads(config_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BuildError(f"cannot read configuration {config_path}: {exc}") from exc
    if not isinstance(config, dict):
        raise BuildError("configuration must be a JSON object")

    output_version = config.get("output_version", MAX_VERSION)
    if not isinstance(output_version, int) or isinstance(output_version, bool) or not 1 <= output_version <= MAX_VERSION:
        raise BuildError(f"output_version must be an integer from 1 to {MAX_VERSION}")
    max_bytes = config.get("max_download_bytes", DEFAULT_MAX_DOWNLOAD_BYTES)
    timeout = config.get("timeout_seconds", DEFAULT_TIMEOUT_SECONDS)
    if not isinstance(max_bytes, int) or isinstance(max_bytes, bool) or max_bytes < 1:
        raise BuildError("max_download_bytes must be a positive integer")
    if not isinstance(timeout, int) or isinstance(timeout, bool) or timeout < 1:
        raise BuildError("timeout_seconds must be a positive integer")
    output_name = config.get("output_name", "merged")
    if not isinstance(output_name, str) or not re.fullmatch(r"[A-Za-z0-9._-]{1,80}", output_name):
        raise BuildError("output_name may contain only letters, digits, dot, underscore, and hyphen")
    sources = config.get("sources")
    if not isinstance(sources, list) or not sources:
        raise BuildError("configuration must contain a non-empty sources array")

    enabled: list[dict[str, Any]] = []
    for position, source in enumerate(sources, start=1):
        if not isinstance(source, dict):
            raise BuildError(f"source {position} must be an object")
        if source.get("enabled", True) is False:
            continue
        name = source.get("name", f"source-{position}")
        if not isinstance(name, str) or not name.strip():
            raise BuildError(f"source {position}: name must be a non-empty string")
        url = validate_https_url(source.get("url"), name)
        fmt = source.get("format", "auto")
        if fmt not in ("auto", "json", "srs"):
            raise BuildError(f"{name}: format must be auto, json, or srs")
        license_url = source.get("license_url", "")
        if license_url:
            validate_https_url(license_url, f"{name} license_url")
        enabled.append({**source, "name": name, "url": url, "format": fmt, "license_url": license_url})
    if not enabled:
        raise BuildError("no enabled sources")

    verify_compiler_version(sing_box, expected_sing_box_version)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_dir = output_dir.resolve()
    documents: list[dict[str, Any]] = []
    source_report: list[dict[str, Any]] = []

    with tempfile.TemporaryDirectory(prefix=".srs-auto-merge-", dir=output_dir) as temp_name:
        temp_dir = Path(temp_name)
        for index, source in enumerate(enabled, start=1):
            body, final_url = download_source(source["url"], max_bytes, timeout)
            document, detected_format = load_rule_set(body, source["format"], source["name"],
                                                       temp_dir, sing_box, index)
            documents.append(document)
            source_report.append({
                "name": source["name"],
                "host": safe_host(final_url),
                "format": detected_format,
                "rules": len(document["rules"]),
                "sha256": hashlib.sha256(body).hexdigest(),
                "license_url": source["license_url"],
                "attribution": source.get("attribution", ""),
            })

        merged_rules, input_rule_count = merge_rules(documents)
        if not merged_rules:
            raise BuildError("all enabled sources produced zero rules; refusing to publish empty output")
        merged = {"version": output_version, "rules": merged_rules}
        json_path = output_dir / f"{output_name}.json"
        srs_path = output_dir / f"{output_name}.srs"
        manifest_path = output_dir / "build-manifest.json"
        temporary_json = temp_dir / f"{output_name}.json"
        temporary_srs = temp_dir / f"{output_name}.srs"
        temporary_decompiled = temp_dir / "verification.json"
        temporary_json.write_text(json.dumps(merged, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        run_sing_box(sing_box, "rule-set", "compile", str(temporary_json), "-o", str(temporary_srs))
        run_sing_box(sing_box, "rule-set", "decompile", str(temporary_srs), "-o", str(temporary_decompiled))
        try:
            verification = json.loads(temporary_decompiled.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError) as exc:
            raise BuildError(f"compiled SRS could not be decompiled for verification: {exc}") from exc
        if len(verification.get("rules", [])) != len(merged_rules):
            raise BuildError("compiled SRS verification failed: rule count changed during round-trip")

        manifest = {
            "format": "sing-box rule-set",
            "output_version": output_version,
            "output_name": output_name,
            "source_count": len(source_report),
            "input_rule_count": input_rule_count,
            "unique_rule_count": len(merged_rules),
            "duplicate_rule_count": input_rule_count - len(merged_rules),
            "srs_sha256": hashlib.sha256(temporary_srs.read_bytes()).hexdigest(),
            "sources": source_report,
        }
        # Replace only after every input has downloaded and the official compiler verified the SRS.
        json_path.write_bytes(temporary_json.read_bytes())
        srs_path.write_bytes(temporary_srs.read_bytes())
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("config/sources.json"))
    parser.add_argument("--output-dir", type=Path, default=Path("output"))
    parser.add_argument("--sing-box", type=Path, default=Path("sing-box"))
    parser.add_argument("--expected-sing-box-version", default=None)
    args = parser.parse_args(argv)
    sing_box = args.sing_box.expanduser()
    if not sing_box.is_absolute():
        sing_box = (Path.cwd() / sing_box).resolve()
    try:
        report = build(args.config, args.output_dir, sing_box, args.expected_sing_box_version)
    except BuildError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({key: report[key] for key in (
        "output_name", "source_count", "input_rule_count", "unique_rule_count", "duplicate_rule_count", "srs_sha256"
    )}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
