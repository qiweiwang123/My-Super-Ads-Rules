"""Unit and end-to-end tests for SRS source merging."""
from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import build as builder

ROOT = Path(__file__).resolve().parents[1]
SING_BOX = Path(os.environ.get("SING_BOX_BIN", shutil.which("sing-box") or "sing-box"))


@unittest.skipUnless(SING_BOX.is_file() or shutil.which(str(SING_BOX)), "sing-box is not installed")
class BuildIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.previous_tempdir = tempfile.tempdir
        self.workspace_temp = ROOT / ".test-tmp"
        self.workspace_temp.mkdir(exist_ok=True)
        # Keep temporary files in the workspace so the bundled sing-box process
        # can access them in restricted desktop environments.
        tempfile.tempdir = str(self.workspace_temp)
        self.temp = tempfile.TemporaryDirectory(prefix="srs-auto-merge-test-")
        self.root = Path(self.temp.name)
        self.output = self.root / "output"
        self.config_path = self.root / "sources.json"

    def tearDown(self) -> None:
        self.temp.cleanup()
        tempfile.tempdir = self.previous_tempdir
        try:
            self.workspace_temp.rmdir()
        except OSError:
            pass

    def write_config(self, sources: list[dict], **options) -> None:
        config = {"output_name": "test-merged", "output_version": 5, "sources": sources, **options}
        self.config_path.write_text(json.dumps(config), encoding="utf-8")

    def source(self, name: str, body: bytes, fmt: str) -> dict:
        return {"name": name, "url": f"https://example.test/{name}", "format": fmt}

    def invoke_with(self, responses: dict[str, bytes]) -> dict:
        def fake_download(url: str, _max_bytes: int, _timeout: int) -> tuple[bytes, str]:
            return responses[url], url

        with patch.object(builder, "download_source", side_effect=fake_download):
            return builder.build(self.config_path, self.output, SING_BOX)

    def test_merges_json_inputs_deduplicates_exact_rule_and_round_trips_srs(self) -> None:
        shared = {"domain_suffix": ["tracker.example"]}
        first = {"version": 5, "rules": [shared, {"domain": ["ads.example"]}]}
        second = {"version": 5, "rules": [shared, {"ip_cidr": ["192.0.2.0/24"]}]}
        self.write_config([self.source("first", b"", "json"), self.source("second", b"", "json")])
        responses = {
            "https://example.test/first": json.dumps(first).encode(),
            "https://example.test/second": json.dumps(second).encode(),
        }
        report = self.invoke_with(responses)
        output = json.loads((self.output / "test-merged.json").read_text(encoding="utf-8"))
        self.assertEqual(output["rules"], first["rules"] + [second["rules"][1]])
        self.assertEqual(report["input_rule_count"], 4)
        self.assertEqual(report["unique_rule_count"], 3)
        self.assertEqual(report["duplicate_rule_count"], 1)
        self.assertTrue((self.output / "test-merged.srs").is_file())
        self.assertEqual(report["srs_sha256"], __import__("hashlib").sha256(
            (self.output / "test-merged.srs").read_bytes()
        ).hexdigest())

    def test_decompiles_srs_source_and_compiles_combined_output(self) -> None:
        source_doc = {"version": 5, "rules": [{"domain_suffix": ["ads.example"]}]}
        source_json = self.root / "input.json"
        source_srs = self.root / "input.srs"
        source_json.write_text(json.dumps(source_doc), encoding="utf-8")
        builder.run_sing_box(SING_BOX, "rule-set", "compile", str(source_json), "-o", str(source_srs))
        srs_bytes = source_srs.read_bytes()
        self.write_config([self.source("binary", b"", "srs")])
        self.invoke_with({"https://example.test/binary": srs_bytes})
        self.assertTrue((self.output / "test-merged.srs").is_file())
        result_json = json.loads((self.output / "test-merged.json").read_text(encoding="utf-8"))
        self.assertEqual(result_json["rules"], [{"domain_suffix": "ads.example"}])

    def test_rejects_empty_rule_instead_of_creating_match_all(self) -> None:
        self.write_config([self.source("bad", b"", "json")])
        with self.assertRaisesRegex(builder.BuildError, "empty and would match all traffic"):
            self.invoke_with({"https://example.test/bad": b'{"version":5,"rules":[{}]}'})


class ValidationTests(unittest.TestCase):
    def test_only_https_sources_are_accepted(self) -> None:
        for url in ("http://example.org/rules.json", "file:///etc/passwd", "https://user:pass@example.org/rules"):
            with self.subTest(url=url), self.assertRaises(builder.BuildError):
                builder.validate_https_url(url, "test")

    def test_only_exact_duplicate_rule_objects_are_removed(self) -> None:
        first = {"version": 5, "rules": [{"domain_suffix": ["example.org"]}, {"domain": ["example.org"]}]}
        second = {"version": 5, "rules": [{"domain_suffix": ["example.org"]}]}
        merged, input_count = builder.merge_rules([first, second])
        self.assertEqual(input_count, 3)
        self.assertEqual(merged, first["rules"])


if __name__ == "__main__":
    unittest.main()
