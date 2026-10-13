import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


AGENT_PATH = Path("/home/ferpek/agent/agent.py")

sys.path.insert(
    0,
    str(AGENT_PATH.parent),
)

spec = importlib.util.spec_from_file_location(
    "ferpek_agent_test_module",
    AGENT_PATH,
)

agent = importlib.util.module_from_spec(spec)
spec.loader.exec_module(agent)


class SourceDiscoveryTests(unittest.TestCase):
    def test_exact_file_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "test.log"
            path.write_text(
                "test\\n",
                encoding="utf-8",
            )

            result = agent.discover_pack_source(
                {
                    "id": "test",
                    "discovery": [
                        {
                            "type": "file",
                            "paths": [str(path)],
                        }
                    ],
                }
            )

            self.assertTrue(result["detected"])
            self.assertEqual(
                result["source_values"],
                [str(path)],
            )
            self.assertEqual(
                result["source_value"],
                str(path),
            )

    def test_file_glob_returns_multiple_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            first = root / "postgresql-16-main.log"
            second = root / "postgresql-17-reporting.log"

            first.write_text(
                "one\\n",
                encoding="utf-8",
            )
            second.write_text(
                "two\\n",
                encoding="utf-8",
            )

            result = agent.discover_pack_source(
                {
                    "id": "postgresql",
                    "discovery": [
                        {
                            "type": "file",
                            "paths": [
                                str(
                                    root
                                    / "postgresql-*.log"
                                )
                            ],
                        }
                    ],
                }
            )

            self.assertTrue(result["detected"])

            self.assertEqual(
                result["source_values"],
                [
                    str(first),
                    str(second),
                ],
            )

    def test_missing_glob_is_not_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = agent.discover_pack_source(
                {
                    "id": "postgresql",
                    "discovery": [
                        {
                            "type": "file",
                            "paths": [
                                str(
                                    Path(tmp)
                                    / "*.log"
                                )
                            ],
                        }
                    ],
                }
            )

            self.assertFalse(result["detected"])
            self.assertEqual(
                result["source_values"],
                [],
            )

    @patch.object(
        agent,
        "journal_units_matching",
    )
    def test_journal_pattern_returns_multiple_units(
        self,
        matching,
    ):
        matching.return_value = [
            "postgresql@16-main.service",
            "postgresql@17-reporting.service",
        ]

        result = agent.discover_pack_source(
            {
                "id": "postgresql",
                "discovery": [
                    {
                        "type": "journal",
                        "units": [
                            "postgresql@*.service",
                        ],
                    }
                ],
            }
        )

        self.assertTrue(result["detected"])

        self.assertEqual(
            result["source_values"],
            [
                "postgresql@16-main.service",
                "postgresql@17-reporting.service",
            ],
        )

    def test_runtime_sources_do_not_collide(self):
        sources = [
            {
                "runtime_key": (
                    "postgresql::file::/tmp/one.log"
                ),
                "source_key": "postgresql",
                "enabled": True,
            },
            {
                "runtime_key": (
                    "postgresql::file::/tmp/two.log"
                ),
                "source_key": "postgresql",
                "enabled": True,
            },
        ]

        result = agent.pack_runtime_sources_by_key(
            sources
        )

        self.assertEqual(len(result), 2)

        self.assertEqual(
            {
                source["source_key"]
                for source in result.values()
            },
            {"postgresql"},
        )

    def test_file_offsets_use_runtime_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            first = root / "one.log"
            second = root / "two.log"

            first.write_text(
                "one\\n",
                encoding="utf-8",
            )
            second.write_text(
                "two\\n",
                encoding="utf-8",
            )

            states = {}

            sources = [
                {
                    "runtime_key": (
                        "postgresql::file::"
                        + str(first)
                    ),
                    "source_key": "postgresql",
                    "source_type": "file",
                    "name": "PostgreSQL",
                    "path": str(first),
                },
                {
                    "runtime_key": (
                        "postgresql::file::"
                        + str(second)
                    ),
                    "source_key": "postgresql",
                    "source_type": "file",
                    "name": "PostgreSQL",
                    "path": str(second),
                },
            ]

            with patch.object(
                agent,
                "save_file_offsets",
            ):
                for source in sources:
                    self.assertTrue(
                        agent.initialize_file_offset(
                            source,
                            states,
                            start_at_end=False,
                        )
                    )

            self.assertEqual(len(states), 2)

    def test_runtime_targets_have_distinct_file_event_ids(self):
        first = agent.file_event_id(
            "postgresql::file::/var/log/postgresql/a.log",
            12345,
            100,
        )

        second = agent.file_event_id(
            "postgresql::file::/mnt/logs/b.log",
            12345,
            100,
        )

        self.assertNotEqual(
            first,
            second,
        )

    def test_event_lookup_prefers_runtime_key(self):
        sources = {
            "postgresql::file::/tmp/a.log": {
                "runtime_key": (
                    "postgresql::file::/tmp/a.log"
                ),
                "source_key": "postgresql",
                "send_events": True,
            },
            "postgresql::file::/tmp/b.log": {
                "runtime_key": (
                    "postgresql::file::/tmp/b.log"
                ),
                "source_key": "postgresql",
                "send_events": False,
            },
        }

        event = {
            "source_key": "postgresql",
            "_runtime_key": (
                "postgresql::file::/tmp/b.log"
            ),
        }

        result = agent.source_config_for_event(
            sources,
            event,
        )

        self.assertFalse(
            result["send_events"]
        )


if __name__ == "__main__":
    unittest.main()
