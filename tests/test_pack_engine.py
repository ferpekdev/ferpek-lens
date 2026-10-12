import sys
import tempfile
import time
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
AGENT_DIR = PROJECT_ROOT / "agent"

if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

from ferpek_lens.pack_engine import PackEngine


class PackEngineTestCase(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.packs_dir = self.root / "packs"
        self.packs_dir.mkdir()
        self.state_file = self.root / "pack-state.json"

    def tearDown(self):
        self.tempdir.cleanup()

    def write_pack(self, rule_text):
        pack_dir = self.packs_dir / "testpack"
        rules_dir = pack_dir / "rules"

        rules_dir.mkdir(parents=True)

        (pack_dir / "manifest.yaml").write_text(
            """
id: testpack
name: Test Pack
version: 1.0.0
""".lstrip(),
            encoding="utf-8",
        )

        (rules_dir / "rule.yaml").write_text(
            rule_text.lstrip(),
            encoding="utf-8",
        )

    def make_engine(self, state_file=None):
        engine = PackEngine(
            self.packs_dir,
            state_file=state_file,
        )
        engine.load()
        return engine

    @staticmethod
    def event(
        message,
        timestamp,
        source_key="test-source",
        source_family="test-family",
    ):
        return {
            "source_key": source_key,
            "source_family": source_family,
            "timestamp": timestamp,
            "message": message,
        }

    def test_relevant_event_is_built_from_named_fields(self):
        self.write_pack(
            r"""
id: testpack.login
name: Login event
source_family: test-family

match:
  regex: 'login user=(?P<user>\S+) ip=(?P<ip>\S+)'

relevant:
  severity: info
  title: Login observed
  detail: "{user} logged in from {ip}."

fields:
  username: "{user}"
  source_ip: "{ip}"
"""
        )

        engine = self.make_engine()

        result = engine.process_event(
            self.event(
                "login user=alice ip=192.0.2.10",
                1000,
            )
        )

        self.assertEqual(result["findings"], [])
        self.assertEqual(len(result["relevant"]), 1)

        relevant = result["relevant"][0]

        self.assertEqual(
            relevant["rule_id"],
            "testpack.login",
        )
        self.assertEqual(
            relevant["title"],
            "Login observed",
        )
        self.assertEqual(
            relevant["detail"],
            "alice logged in from 192.0.2.10.",
        )
        self.assertEqual(
            relevant["fields"]["username"],
            "alice",
        )
        self.assertEqual(
            relevant["fields"]["source_ip"],
            "192.0.2.10",
        )

    def test_finding_does_not_contain_suggest(self):
        self.write_pack(
            r"""
id: testpack.failure
name: Failure
source_family: test-family

match:
  regex: 'failure ip=(?P<ip>\S+)'

finding:
  severity: warning
  title: Failure observed
  detail: "Failure from {ip}."
"""
        )

        engine = self.make_engine()

        result = engine.process_event(
            self.event(
                "failure ip=192.0.2.20",
                1000,
            )
        )

        self.assertEqual(len(result["findings"]), 1)

        finding = result["findings"][0]

        self.assertNotIn("suggest", finding)
        self.assertEqual(
            finding["title"],
            "Failure observed",
        )
        self.assertEqual(
            finding["detail"],
            "Failure from 192.0.2.20.",
        )

    def test_threshold_requires_configured_number_of_occurrences(self):
        self.write_pack(
            r"""
id: testpack.repeated
name: Repeated event
source_family: test-family

match:
  regex: 'failure ip=(?P<ip>\S+)'

group_by:
  - ip

aggregate:
  window_seconds: 300
  threshold: 3

finding:
  severity: warning
  title: Repeated event
  detail: "{count} failures from {ip}."
"""
        )

        engine = self.make_engine()

        first = engine.process_event(
            self.event(
                "failure ip=192.0.2.30",
                1000,
            )
        )
        second = engine.process_event(
            self.event(
                "failure ip=192.0.2.30",
                1010,
            )
        )
        third = engine.process_event(
            self.event(
                "failure ip=192.0.2.30",
                1020,
            )
        )

        self.assertEqual(first["findings"], [])
        self.assertEqual(second["findings"], [])
        self.assertEqual(len(third["findings"]), 1)
        self.assertEqual(
            third["findings"][0]["detail"],
            "3 failures from 192.0.2.30.",
        )

    def test_group_by_keeps_groups_independent(self):
        self.write_pack(
            r"""
id: testpack.grouped
name: Grouped event
source_family: test-family

match:
  regex: 'failure ip=(?P<ip>\S+)'

group_by:
  - ip

aggregate:
  window_seconds: 300
  threshold: 2

finding:
  severity: warning
  title: Repeated event
  detail: "{count} failures from {ip}."
"""
        )

        engine = self.make_engine()

        engine.process_event(
            self.event(
                "failure ip=192.0.2.40",
                1000,
            )
        )

        other_group = engine.process_event(
            self.event(
                "failure ip=192.0.2.41",
                1010,
            )
        )

        result = engine.process_event(
            self.event(
                "failure ip=192.0.2.40",
                1020,
            )
        )

        self.assertEqual(
            other_group["findings"],
            [],
        )
        self.assertEqual(
            len(result["findings"]),
            1,
        )
        self.assertEqual(
            result["findings"][0]["group_key"],
            "192.0.2.40",
        )

    def test_cooldown_suppresses_repeated_finding(self):
        self.write_pack(
            r"""
id: testpack.cooldown
name: Cooldown event
source_family: test-family

match:
  regex: 'failure ip=(?P<ip>\S+)'

group_by:
  - ip

aggregate:
  window_seconds: 300
  threshold: 2
  cooldown_seconds: 60

finding:
  severity: warning
  title: Repeated event
  detail: "{count} failures from {ip}."
"""
        )

        engine = self.make_engine()

        engine.process_event(
            self.event(
                "failure ip=192.0.2.50",
                1000,
            )
        )

        first_finding = engine.process_event(
            self.event(
                "failure ip=192.0.2.50",
                1010,
            )
        )

        suppressed = engine.process_event(
            self.event(
                "failure ip=192.0.2.50",
                1020,
            )
        )

        later = engine.process_event(
            self.event(
                "failure ip=192.0.2.50",
                1071,
            )
        )

        self.assertEqual(
            len(first_finding["findings"]),
            1,
        )
        self.assertEqual(
            suppressed["findings"],
            [],
        )
        self.assertEqual(
            len(later["findings"]),
            1,
        )

    def test_window_discards_old_occurrences(self):
        self.write_pack(
            r"""
id: testpack.window
name: Window event
source_family: test-family

match:
  regex: 'failure ip=(?P<ip>\S+)'

group_by:
  - ip

aggregate:
  window_seconds: 60
  threshold: 2

finding:
  severity: warning
  title: Repeated event
  detail: "{count} failures from {ip}."
"""
        )

        engine = self.make_engine()

        engine.process_event(
            self.event(
                "failure ip=192.0.2.60",
                1000,
            )
        )

        outside_window = engine.process_event(
            self.event(
                "failure ip=192.0.2.60",
                1061,
            )
        )

        inside_window = engine.process_event(
            self.event(
                "failure ip=192.0.2.60",
                1070,
            )
        )

        self.assertEqual(
            outside_window["findings"],
            [],
        )
        self.assertEqual(
            len(inside_window["findings"]),
            1,
        )
        self.assertEqual(
            inside_window["findings"][0]["detail"],
            "2 failures from 192.0.2.60.",
        )

    def test_state_persists_occurrences_across_restart(self):
        self.write_pack(
            r"""
id: testpack.persisted
name: Persisted event
source_family: test-family

match:
  regex: 'failure ip=(?P<ip>\S+)'

group_by:
  - ip

aggregate:
  window_seconds: 300
  threshold: 3

finding:
  severity: warning
  title: Repeated event
  detail: "{count} failures from {ip}."
"""
        )

        now = int(time.time())

        first_engine = self.make_engine(
            state_file=self.state_file,
        )

        first_engine.process_event(
            self.event(
                "failure ip=192.0.2.70",
                now - 20,
            )
        )
        first_engine.process_event(
            self.event(
                "failure ip=192.0.2.70",
                now - 10,
            )
        )

        first_engine.save_state(force=True)

        second_engine = self.make_engine(
            state_file=self.state_file,
        )
        second_engine.load_state()

        result = second_engine.process_event(
            self.event(
                "failure ip=192.0.2.70",
                now,
            )
        )

        self.assertEqual(
            len(result["findings"]),
            1,
        )
        self.assertEqual(
            result["findings"][0]["detail"],
            "3 failures from 192.0.2.70.",
        )


if __name__ == "__main__":
    unittest.main()
