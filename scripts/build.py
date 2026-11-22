#!/usr/bin/env python3
"""Download, merge and compile sing-box rule-set sources safely and reproducibly.

支持两种配置形态：

1. 单组（兼容旧版）：
   {"output_name": "ads-tracking", "sources": [...]}

2. 多组（推荐）：
   {"groups": [{"name": "广告拦截", "output_name": "ads", "sources": [...]}, ...]}

每个组独立合并、独立编译、独立输出 .srs/.json，并生成三套链接：
原始 raw、jsDelivr(cdn.jsdelivr.net)、fastly(fastly.jsdelivr.net)。
"""
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

NAME_PATTERN = re.compile(r"[A-Za-z0-9._-]{1,80}")


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
        headers={"User-Agent": "srs-auto-merge/1.1", "Accept": "application/json, application/octet-stream"},
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
    """合并多个规则源。

    单键规则（如 {"domain_suffix": [...]}）按字段做并集去重，其余规则整体去重。
    """
    merged: list[dict[str, Any]] = []
    simple: dict[str, dict[str, Any]] = {}
    seen_complex: set[str] = set()
    input_count = 0
    for document in documents:
        for rule in document["rules"]:
            input_count += 1
            if len(rule) == 1:
                field, values = next(iter(rule.items()))
                if isinstance(values, list) and all(isinstance(v, (str, int)) for v in values):
                    target = simple.get(field)
                    if target is None:
                        target = {field: []}
                        simple[field] = target
                        merged.append(target)
                    existing = set(target[field])
                    for value in values:
                        if value not in existing:
                            target[field].append(value)
                            existing.add(value)
                    continue
            key = canonical_json(rule)
            if key not in seen_complex:
                seen_complex.add(key)
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


def resolve_links_config(config: dict[str, Any], repo: str | None, branch: str | None,
                         path_prefix: str | None) -> dict[str, str] | None:
    """合并配置、CLI、GitHub Actions 环境里的链接参数。"""
    links = config.get("links") or {}
    if not isinstance(links, dict):
        raise BuildError("links must be an object")
    repo = repo or links.get("repo") or os.environ.get("GITHUB_REPOSITORY")
    branch = branch or links.get("branch") or os.environ.get("GITHUB_REF_NAME") or "main"
    path_prefix = path_prefix or links.get("path") or "output"
    if not repo:
        return None
    if not isinstance(repo, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
        raise BuildError("links.repo must look like owner/repo")
    if not isinstance(branch, str) or not re.fullmatch(r"[A-Za-z0-9._/-]{1,120}", branch):
        raise BuildError("links.branch contains invalid characters")
    if not isinstance(path_prefix, str) or path_prefix.startswith("/") or ".." in path_prefix:
        raise BuildError("links.path must be a relative path inside the repository")
    return {"repo": repo, "branch": branch, "path": path_prefix.rstrip("/") or "output"}


def build_links(output_name: str, links: dict[str, str] | None) -> dict[str, str]:
    if not links:
        return {}
    repo, branch, prefix = links["repo"], links["branch"], links["path"]
    filename = f"{output_name}.srs"
    path = f"{prefix}/{filename}" if prefix else filename
    return {
        "raw": f"https://raw.githubusercontent.com/{repo}/{branch}/{path}",
        "jsdelivr": f"https://cdn.jsdelivr.net/gh/{repo}@{branch}/{path}",
        "fastly": f"https://fastly.jsdelivr.net/gh/{repo}@{branch}/{path}",
    }


def normalize_groups(config: dict[str, Any]) -> list[dict[str, Any]]:
    """把单组/多组配置统一成 groups 列表。"""
    if "groups" in config:
        raw_groups = config["groups"]
        if not isinstance(raw_groups, list) or not raw_groups:
            raise BuildError("groups must be a non-empty array")
    else:
        if "sources" not in config:
            raise BuildError("configuration must contain either groups or sources")
        raw_groups = [{
            "name": config.get("output_name", "merged"),
            "output_name": config.get("output_name", "merged"),
            "sources": config.get("sources"),
        }]

    groups: list[dict[str, Any]] = []
    used_names: set[str] = set()
    for position, group in enumerate(raw_groups, start=1):
        if not isinstance(group, dict):
            raise BuildError(f"group {position} must be an object")
        name = group.get("name") or group.get("output_name") or f"group-{position}"
        if not isinstance(name, str) or not name.strip():
            raise BuildError(f"group {position}: name must be a non-empty string")
        output_name = group.get("output_name") or name
        if not isinstance(output_name, str) or not NAME_PATTERN.fullmatch(output_name):
            raise BuildError(
                f"group {position}: output_name may contain only letters, digits, dot, underscore, and hyphen"
            )
        if output_name in used_names:
            raise BuildError(f"duplicate output_name: {output_name}")
        used_names.add(output_name)
        sources = group.get("sources")
        if not isinstance(sources, list) or not sources:
            raise BuildError(f"group {name}: sources must be a non-empty array")
        enabled = group.get("enabled", True)
        if not isinstance(enabled, bool):
            raise BuildError(f"group {name}: enabled must be true or false")
        groups.append({
            "name": name,
            "output_name": output_name,
            "description": group.get("description", ""),
            "sources": sources,
            "enabled": enabled,
            "output_version": group.get("output_version", config.get("output_version", MAX_VERSION)),
        })
    return groups


def collect_sources(group: dict[str, Any]) -> list[dict[str, Any]]:
    enabled: list[dict[str, Any]] = []
    for position, source in enumerate(group["sources"], start=1):
        if not isinstance(source, dict):
            raise BuildError(f"{group['name']}: source {position} must be an object")
        if source.get("enabled", True) is False:
            continue
        name = source.get("name", f"source-{position}")
        if not isinstance(name, str) or not name.strip():
            raise BuildError(f"{group['name']}: source {position}: name must be a non-empty string")
        url = validate_https_url(source.get("url"), f"{group['name']}/{name}")
        fmt = source.get("format", "auto")
        if fmt not in ("auto", "json", "srs"):
            raise BuildError(f"{group['name']}/{name}: format must be auto, json, or srs")
        license_url = source.get("license_url", "")
        if license_url:
            validate_https_url(license_url, f"{group['name']}/{name} license_url")
        enabled.append({**source, "name": name, "url": url, "format": fmt, "license_url": license_url})
    if not enabled:
        raise BuildError(f"{group['name']}: no enabled sources")
    return enabled


def build_group(group: dict[str, Any], output_dir: Path, temp_dir: Path, sing_box: Path,
                cache: dict[str, tuple[bytes, str]], max_bytes: int, timeout: int,
                links: dict[str, str] | None) -> dict[str, Any]:
    output_name = group["output_name"]
    output_version = group["output_version"]
    if not isinstance(output_version, int) or isinstance(output_version, bool) \
            or not 1 <= output_version <= MAX_VERSION:
        raise BuildError(f"{group['name']}: output_version must be an integer from 1 to {MAX_VERSION}")

    documents: list[dict[str, Any]] = []
    source_report: list[dict[str, Any]] = []
    for index, source in enumerate(collect_sources(group), start=1):
        key = source["url"]
        if key in cache:
            body, final_url = cache[key]
        else:
            body, final_url = download_source(source["url"], max_bytes, timeout)
            cache[key] = (body, final_url)
        document, detected_format = load_rule_set(
            body, source["format"], f"{group['name']}/{source['name']}", temp_dir, sing_box,
            index=f"{output_name}-{index}",
        )
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
        raise BuildError(f"{group['name']}: all enabled sources produced zero rules; refusing to publish empty output")
    merged = {"version": output_version, "rules": merged_rules}

    temporary_json = temp_dir / f"{output_name}.json"
    temporary_srs = temp_dir / f"{output_name}.srs"
    temporary_decompiled = temp_dir / f"{output_name}.verify.json"
    temporary_json.write_text(json.dumps(merged, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    run_sing_box(sing_box, "rule-set", "compile", str(temporary_json), "-o", str(temporary_srs))
    run_sing_box(sing_box, "rule-set", "decompile", str(temporary_srs), "-o", str(temporary_decompiled))
    try:
        verification = json.loads(temporary_decompiled.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BuildError(f"{group['name']}: compiled SRS could not be decompiled for verification: {exc}") from exc
    if len(verification.get("rules", [])) != len(merged_rules):
        raise BuildError(f"{group['name']}: compiled SRS verification failed: rule count changed during round-trip")

    (output_dir / f"{output_name}.json").write_bytes(temporary_json.read_bytes())
    (output_dir / f"{output_name}.srs").write_bytes(temporary_srs.read_bytes())

    return {
        "name": group["name"],
        "description": group["description"],
        "output_name": output_name,
        "output_version": output_version,
        "source_count": len(source_report),
        "input_rule_count": input_rule_count,
        "unique_rule_count": len(merged_rules),
        "duplicate_rule_count": input_rule_count - len(merged_rules),
        "srs_sha256": hashlib.sha256(temporary_srs.read_bytes()).hexdigest(),
        "links": build_links(output_name, links),
        "sources": source_report,
    }


def render_links_markdown(links: dict[str, str] | None, groups: list[dict[str, Any]]) -> str:
    lines = ["# 生成的规则集链接", ""]
    if not links:
        lines.append("> 未配置 `links.repo`（或环境变量 `GITHUB_REPOSITORY`），跳过链接生成。")
        return "\n".join(lines) + "\n"
    lines.append(f"仓库：`{links['repo']}` · 分支：`{links['branch']}` · 目录：`{links['path']}`")
    lines.append("")
    for group in groups:
        group_links = group["links"]
        lines.append(f"## {group['name']}（`{group['output_name']}`）")
        if group["description"]:
            lines.append("")
            lines.append(group["description"])
        lines.append("")
        lines.append("| 线路 | 地址 |")
        lines.append("| --- | --- |")
        lines.append(f"| 原始 raw | <{group_links['raw']}> |")
        lines.append(f"| jsDelivr | <{group_links['jsdelivr']}> |")
        lines.append(f"| fastly | <{group_links['fastly']}> |")
        lines.append("")
        lines.append(f"规则数：{group['unique_rule_count']} · 来源：{group['source_count']} 个")
        lines.append("")
        lines.append("```json")
        lines.append(json.dumps({
            "tag": group["output_name"],
            "type": "remote",
            "format": "binary",
            "url": group_links["fastly"],
            "download_detour": "direct",
            "update_interval": "24h",
        }, ensure_ascii=False, indent=2))
        lines.append("```")
        lines.append("")
    return "\n".join(lines)


def build(config_path: Path, output_dir: Path, sing_box: Path,
          expected_sing_box_version: str | None = None,
          repo: str | None = None, branch: str | None = None,
          path_prefix: str | None = None) -> dict[str, Any]:
    try:
        config = json.loads(config_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BuildError(f"cannot read configuration {config_path}: {exc}") from exc
    if not isinstance(config, dict):
        raise BuildError("configuration must be a JSON object")

    max_bytes = config.get("max_download_bytes", DEFAULT_MAX_DOWNLOAD_BYTES)
    timeout = config.get("timeout_seconds", DEFAULT_TIMEOUT_SECONDS)
    if not isinstance(max_bytes, int) or isinstance(max_bytes, bool) or max_bytes < 1:
        raise BuildError("max_download_bytes must be a positive integer")
    if not isinstance(timeout, int) or isinstance(timeout, bool) or timeout < 1:
        raise BuildError("timeout_seconds must be a positive integer")

    all_groups = normalize_groups(config)
    groups = [group for group in all_groups if group["enabled"]]
    skipped_groups = [group["name"] for group in all_groups if not group["enabled"]]
    if not groups:
        raise BuildError("all groups are disabled; enable at least one group")
    links_config = resolve_links_config(config, repo, branch, path_prefix)

    verify_compiler_version(sing_box, expected_sing_box_version)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_dir = output_dir.resolve()

    cache: dict[str, tuple[bytes, str]] = {}
    group_reports: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix=".srs-auto-merge-", dir=output_dir) as temp_name:
        temp_dir = Path(temp_name)
        for group in groups:
            group_reports.append(build_group(group, output_dir, temp_dir, sing_box, cache,
                                             max_bytes, timeout, links_config))

    manifest = {
        "format": "sing-box rule-set",
        "generated_by": "srs-auto-merge/1.1",
        "group_count": len(group_reports),
        "skipped_groups": skipped_groups,
        "links": links_config or {},
        "groups": group_reports,
    }
    (output_dir / "build-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if links_config:
        (output_dir / "links.json").write_text(json.dumps({
            "repo": links_config["repo"],
            "branch": links_config["branch"],
            "path": links_config["path"],
            "groups": [
                {"name": g["name"], "output_name": g["output_name"], "links": g["links"]}
                for g in group_reports
            ],
        }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (output_dir / "links.md").write_text(
            render_links_markdown(links_config, group_reports), encoding="utf-8")

    # 单组模式保持与旧版一致的返回结构。
    if len(group_reports) == 1 and "groups" not in config:
        single = group_reports[0]
        return {
            "output_name": single["output_name"],
            "source_count": single["source_count"],
            "input_rule_count": single["input_rule_count"],
            "unique_rule_count": single["unique_rule_count"],
            "duplicate_rule_count": single["duplicate_rule_count"],
            "srs_sha256": single["srs_sha256"],
            "links": single["links"],
        }
    return {"groups": group_reports, "links": links_config or {}}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("config/sources.json"))
    parser.add_argument("--output-dir", type=Path, default=Path("output"))
    parser.add_argument("--sing-box", type=Path, default=Path("sing-box"))
    parser.add_argument("--expected-sing-box-version", default=None)
    parser.add_argument("--repo", default=None, help="owner/repo，用于生成链接；默认读 GITHUB_REPOSITORY")
    parser.add_argument("--branch", default=None, help="分支名，默认读 GITHUB_REF_NAME 或 main")
    parser.add_argument("--path", dest="path_prefix", default=None, help="输出目录在仓库中的相对路径")
    args = parser.parse_args(argv)
    sing_box = args.sing_box.expanduser()
    if not sing_box.is_absolute():
        sing_box = (Path.cwd() / sing_box).resolve()
    try:
        report = build(args.config, args.output_dir, sing_box, args.expected_sing_box_version,
                       repo=args.repo, branch=args.branch, path_prefix=args.path_prefix)
    except BuildError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    if "groups" in report:
        for group in report["groups"]:
            print(f"[{group['name']}] {group['output_name']}: "
                  f"{group['unique_rule_count']} rules from {group['source_count']} sources")
            for label, url in group["links"].items():
                print(f"    {label}: {url}")
    else:
        print(json.dumps({key: report[key] for key in (
            "output_name", "source_count", "input_rule_count", "unique_rule_count",
            "duplicate_rule_count", "srs_sha256"
        )}, ensure_ascii=False, indent=2))
        for label, url in (report.get("links") or {}).items():
            print(f"{label}: {url}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
