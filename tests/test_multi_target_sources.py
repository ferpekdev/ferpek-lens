import ast
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path("/home/ferpek")
AGENT_PATH = ROOT / "agent" / "agent.py"
SERVER_PATH = ROOT / "server" / "main.py"

sys.path.insert(
    0,
    str(AGENT_PATH.parent),
)

agent_spec = importlib.util.spec_from_file_location(
    "ferpek_agent_integration",
    AGENT_PATH,
)

agent = importlib.util.module_from_spec(
    agent_spec
)

agent_spec.loader.exec_module(agent)


def load_server_runtime_helper():
    source = SERVER_PATH.read_text(
        encoding="utf-8"
    )

    tree = ast.parse(source)

    wanted = {
        "build_discovered_runtime_sources",
    }

    functions = [
        node
        for node in tree.body
        if (
            isinstance(
                node,
                ast.FunctionDef,
            )
            and node.name in wanted
        )
    ]

    if len(functions) != 1:
        raise RuntimeError(
            "Could not load server runtime helper"
        )

    module = ast.Module(
        body=functions,
        type_ignores=[],
    )

    namespace = {}

    exec(
        compile(
            module,
            str(SERVER_PATH),
            "exec",
        ),
        namespace,
    )

    return namespace[
        "build_discovered_runtime_sources"
    ]


build_runtime_sources = (
    load_server_runtime_helper()
)


class MultiTargetIntegrationTests(
    unittest.TestCase
):
    def test_two_postgresql_files_end_to_end(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            first = (
                root
                / "postgresql-16-main.log"
            )

            second = (
                root
                / "postgresql-17-reporting.log"
            )

            first.write_text(
                "existing first line\n",
                encoding="utf-8",
            )

            second.write_text(
                "existing second line\n",
                encoding="utf-8",
            )

            discovery = agent.discover_pack_source(
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

            self.assertTrue(
                discovery["detected"]
            )

            self.assertEqual(
                discovery["source_type"],
                "file",
            )

            self.assertEqual(
                len(
                    discovery[
                        "source_values"
                    ]
                ),
                2,
            )

            stored_values = json.loads(
                json.dumps(
                    discovery[
                        "source_values"
                    ]
                )
            )

            runtime_sources = (
                build_runtime_sources(
                    "postgresql",
                    "PostgreSQL",
                    discovery[
                        "source_type"
                    ],
                    discovery[
                        "source_value"
                    ],
                    stored_values,
                )
            )

            self.assertEqual(
                len(runtime_sources),
                2,
            )

            self.assertEqual(
                {
                    source["source_key"]
                    for source
                    in runtime_sources
                },
                {"postgresql"},
            )

            runtime_by_key = (
                agent
                .pack_runtime_sources_by_key(
                    runtime_sources
                )
            )

            self.assertEqual(
                len(runtime_by_key),
                2,
            )

            self.assertEqual(
                len(
                    set(
                        runtime_by_key.keys()
                    )
                ),
                2,
            )

            states = {}

            with patch.object(
                agent,
                "save_file_offsets",
            ):
                for source in (
                    runtime_by_key.values()
                ):
                    self.assertTrue(
                        agent
                        .initialize_file_offset(
                            source,
                            states,
                            start_at_end=False,
                        )
                    )

            self.assertEqual(
                len(states),
                2,
            )

            self.assertEqual(
                set(states),
                set(runtime_by_key),
            )

            first_runtime = next(
                source
                for source
                in runtime_sources
                if source["path"]
                == str(first)
            )

            second_runtime = next(
                source
                for source
                in runtime_sources
                if source["path"]
                == str(second)
            )

            first_event = (
                agent.normalize_file_event(
                    first_runtime,
                    b"first event\n",
                )
            )

            second_event = (
                agent.normalize_file_event(
                    second_runtime,
                    b"second event\n",
                )
            )

            self.assertEqual(
                first_event["source_key"],
                "postgresql",
            )

            self.assertEqual(
                second_event["source_key"],
                "postgresql",
            )

            self.assertNotEqual(
                first_event[
                    "_runtime_key"
                ],
                second_event[
                    "_runtime_key"
                ],
            )

            first_id = agent.file_event_id(
                first_event[
                    "_runtime_key"
                ],
                777,
                100,
            )

            second_id = agent.file_event_id(
                second_event[
                    "_runtime_key"
                ],
                777,
                100,
            )

            self.assertNotEqual(
                first_id,
                second_id,
            )


if __name__ == "__main__":
    unittest.main()
