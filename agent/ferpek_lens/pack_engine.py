import json
import os
import re
import time
from collections import defaultdict, deque
from pathlib import Path

import yaml


PACK_ENGINE_VERSION = "0.2.0"


class PackEngine:
    def __init__(self, packs_dir, state_file=None):
        self.packs_dir = Path(packs_dir)

        self.state_file = (
            Path(state_file)
            if state_file is not None
            else None
        )

        self.rules = []

        # rule/group -> timestamps
        self.occurrences = defaultdict(deque)

        # rule/group -> collection name -> (timestamp, value)
        self.collections = defaultdict(
            lambda: defaultdict(deque)
        )

        # rule/group -> timestamp
        self.last_finding = {}

        self.state_dirty = False
        self.last_state_save = 0.0

    def load_state(self):
        if self.state_file is None:
            return

        if not self.state_file.exists():
            return

        try:
            data = json.loads(
                self.state_file.read_text(
                    encoding="utf-8"
                )
            )
        except (
            OSError,
            json.JSONDecodeError,
        ) as exc:
            print(
                f"[FERPEK Lens] Cannot load state: {exc}"
            )
            return

        occurrences_data = data.get(
            "occurrences",
            [],
        )

        collections_data = data.get(
            "collections",
            [],
        )

        last_finding_data = data.get(
            "last_finding",
            [],
        )

        now = int(time.time())

        rules_by_id = {
            rule["id"]: rule
            for rule in self.rules
        }

        for item in occurrences_data:
            try:
                rule_id = item["rule_id"]

                rule = rules_by_id.get(
                    rule_id
                )

                if rule is None:
                    continue

                group_values = tuple(
                    item.get(
                        "group_values",
                        [],
                    )
                )

                timestamps = [
                    int(value)
                    for value in item.get(
                        "timestamps",
                        [],
                    )
                ]

                window = rule["_window"]

                if window > 0:
                    cutoff = now - window

                    timestamps = [
                        value
                        for value in timestamps
                        if value >= cutoff
                    ]

                if not timestamps:
                    continue

                group_key = (
                    rule_id,
                    group_values,
                )

                self.occurrences[group_key] = (
                    deque(timestamps)
                )

            except (
                KeyError,
                TypeError,
                ValueError,
            ):
                continue

        for item in collections_data:
            try:
                rule_id = item["rule_id"]

                rule = rules_by_id.get(
                    rule_id
                )

                if rule is None:
                    continue

                group_values = tuple(
                    item.get(
                        "group_values",
                        [],
                    )
                )

                collection_name = str(
                    item["name"]
                )

                if (
                    collection_name
                    not in rule.get("_collect", {})
                ):
                    continue

                values = []

                for entry in item.get(
                    "values",
                    [],
                ):
                    timestamp = int(
                        entry["timestamp"]
                    )

                    value = str(
                        entry["value"]
                    )

                    values.append(
                        (
                            timestamp,
                            value,
                        )
                    )

                window = rule["_window"]

                if window > 0:
                    cutoff = now - window

                    values = [
                        entry
                        for entry in values
                        if entry[0] >= cutoff
                    ]

                if not values:
                    continue

                group_key = (
                    rule_id,
                    group_values,
                )

                self.collections[
                    group_key
                ][
                    collection_name
                ] = deque(values)

            except (
                KeyError,
                TypeError,
                ValueError,
            ):
                continue

        for item in last_finding_data:
            try:
                rule_id = item["rule_id"]

                if rule_id not in rules_by_id:
                    continue

                group_values = tuple(
                    item.get(
                        "group_values",
                        [],
                    )
                )

                timestamp = int(
                    item["timestamp"]
                )

                group_key = (
                    rule_id,
                    group_values,
                )

                self.last_finding[group_key] = (
                    timestamp
                )

            except (
                KeyError,
                TypeError,
                ValueError,
            ):
                continue


    def save_state(self, force=False):
        if self.state_file is None:
            return

        if not self.state_dirty and not force:
            return

        self.state_file.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        data = {
            "occurrences": [],
            "collections": [],
            "last_finding": [],
        }

        for (
            rule_id,
            group_values,
        ), timestamps in self.occurrences.items():
            if not timestamps:
                continue

            data["occurrences"].append(
                {
                    "rule_id": rule_id,
                    "group_values": list(
                        group_values
                    ),
                    "timestamps": list(
                        timestamps
                    ),
                }
            )

        for (
            rule_id,
            group_values,
        ), collections in self.collections.items():
            for name, values in collections.items():
                if not values:
                    continue

                data["collections"].append(
                    {
                        "rule_id": rule_id,
                        "group_values": list(
                            group_values
                        ),
                        "name": name,
                        "values": [
                            {
                                "timestamp": timestamp,
                                "value": value,
                            }
                            for timestamp, value in values
                        ],
                    }
                )

        for (
            rule_id,
            group_values,
        ), timestamp in self.last_finding.items():
            data["last_finding"].append(
                {
                    "rule_id": rule_id,
                    "group_values": list(
                        group_values
                    ),
                    "timestamp": timestamp,
                }
            )

        temporary = self.state_file.with_suffix(
            self.state_file.suffix + ".tmp"
        )

        temporary.write_text(
            json.dumps(
                data,
                separators=(",", ":"),
            ),
            encoding="utf-8",
        )

        os.replace(
            temporary,
            self.state_file,
        )

        self.state_dirty = False
        self.last_state_save = time.monotonic()


    def load(self):
        self.rules = []

        if not self.packs_dir.exists():
            return

        for pack_dir in sorted(self.packs_dir.iterdir()):
            if not pack_dir.is_dir():
                continue

            manifest_path = pack_dir / "manifest.yaml"
            rules_dir = pack_dir / "rules"

            if not manifest_path.exists():
                continue

            try:
                manifest = yaml.safe_load(
                    manifest_path.read_text(
                        encoding="utf-8"
                    )
                ) or {}
            except Exception as exc:
                print(
                    f"[FERPEK Lens] Cannot load "
                    f"{manifest_path}: {exc}"
                )
                continue

            if not rules_dir.is_dir():
                continue

            for rule_path in sorted(
                rules_dir.glob("*.yaml")
            ):
                try:
                    rule = yaml.safe_load(
                        rule_path.read_text(
                            encoding="utf-8"
                        )
                    ) or {}

                    self._prepare_rule(
                        manifest,
                        rule,
                        rule_path,
                    )

                except Exception as exc:
                    print(
                        f"[FERPEK Lens] Cannot load "
                        f"{rule_path}: {exc}"
                    )

    def _prepare_rule(
        self,
        manifest,
        rule,
        rule_path,
    ):
        rule_id = rule.get("id")

        if not rule_id:
            raise ValueError(
                "Rule has no id"
            )

        pack_id = manifest.get(
            "id",
            "unknown",
        )

        if not str(rule_id).startswith(
            f"{pack_id}."
        ):
            raise ValueError(
                f"{rule_id}: rule id must start with {pack_id}."
            )

        if any(
            existing.get("id") == rule_id
            for existing in self.rules
        ):
            raise ValueError(
                f"{rule_id}: duplicate rule id"
            )

        sources = rule.get("sources", [])
        source_family = rule.get("source_family")

        if not sources and not source_family:
            raise ValueError(
                f"{rule_id}: no sources or source_family configured"
            )

        match = rule.get("match", {})
        pattern = match.get("regex")

        if not pattern:
            raise ValueError(
                f"{rule_id}: match.regex missing"
            )

        aggregate = rule.get(
            "aggregate",
            {},
        )

        if not isinstance(aggregate, dict):
            raise ValueError(
                f"{rule_id}: aggregate must be a mapping"
            )

        window = int(
            aggregate.get(
                "window_seconds",
                0,
            )
        )

        threshold = int(
            aggregate.get(
                "threshold",
                1,
            )
        )

        cooldown = int(
            aggregate.get(
                "cooldown_seconds",
                0,
            )
        )

        collect = aggregate.get(
            "collect",
            {},
        )

        if collect is None:
            collect = {}

        if not isinstance(collect, dict):
            raise ValueError(
                f"{rule_id}: aggregate.collect must be a mapping"
            )

        prepared_collect = {}

        for collection_name, config in collect.items():
            collection_name = str(
                collection_name
            ).strip()

            if not collection_name:
                raise ValueError(
                    f"{rule_id}: aggregate.collect has an empty name"
                )

            if not isinstance(config, dict):
                raise ValueError(
                    f"{rule_id}: collect.{collection_name} "
                    "must be a mapping"
                )

            field = str(
                config.get(
                    "field",
                    "",
                )
            ).strip()

            if not field:
                raise ValueError(
                    f"{rule_id}: collect.{collection_name}.field "
                    "is required"
                )

            prepared_collect[
                collection_name
            ] = {
                "field": field,
                "distinct": bool(
                    config.get(
                        "distinct",
                        False,
                    )
                ),
            }

        if prepared_collect and window <= 0:
            raise ValueError(
                f"{rule_id}: aggregate.collect requires "
                "window_seconds > 0"
            )

        conditions = rule.get(
            "conditions",
            {},
        )

        if conditions is None:
            conditions = {}

        if not isinstance(conditions, dict):
            raise ValueError(
                f"{rule_id}: conditions must be a mapping"
            )

        valid_condition_keys = {
            "count",
            *(
                f"{name}_count"
                for name in prepared_collect
            ),
        }

        valid_operators = {
            "eq",
            "ne",
            "gt",
            "gte",
            "lt",
            "lte",
        }

        prepared_conditions = {}

        for key, config in conditions.items():
            key = str(key).strip()

            if key not in valid_condition_keys:
                raise ValueError(
                    f"{rule_id}: unsupported condition key: {key}"
                )

            if not isinstance(config, dict):
                raise ValueError(
                    f"{rule_id}: condition {key} must be a mapping"
                )

            if len(config) != 1:
                raise ValueError(
                    f"{rule_id}: condition {key} must contain "
                    "exactly one operator"
                )

            operator, expected = next(
                iter(config.items())
            )

            operator = str(operator).strip()

            if operator not in valid_operators:
                raise ValueError(
                    f"{rule_id}: unsupported condition operator: "
                    f"{operator}"
                )

            try:
                expected = int(expected)
            except (TypeError, ValueError):
                raise ValueError(
                    f"{rule_id}: condition {key}.{operator} "
                    "must be an integer"
                )

            prepared_conditions[key] = {
                "operator": operator,
                "value": expected,
            }

        prepared = {
            **rule,
            "_pack_id": manifest.get(
                "id",
                "unknown",
            ),
            "_pack_name": manifest.get(
                "name",
                "Unknown pack",
            ),
            "_rule_path": str(rule_path),
            "_regex": re.compile(pattern),
            "_window": window,
            "_threshold": threshold,
            "_cooldown": cooldown,
            "_collect": prepared_collect,
            "_conditions": prepared_conditions,
        }

        self.rules.append(prepared)

    def describe(self):
        return [
            {
                "pack": rule["_pack_id"],
                "id": rule["id"],
                "sources": rule.get("sources", []),
                "source_family": rule.get("source_family"),
            }
            for rule in self.rules
        ]

    def process_event(self, event):
        result = {
            "relevant": [],
            "findings": [],
        }

        for rule in self.rules:
            configured_sources = rule.get(
                "sources",
                [],
            )

            configured_family = rule.get(
                "source_family"
            )

            source_matches = (
                bool(configured_sources)
                and event.get("source_key")
                in configured_sources
            )

            family_matches = (
                bool(configured_family)
                and event.get("source_family")
                == configured_family
            )

            if not source_matches and not family_matches:
                continue

            message = event.get(
                "message",
                "",
            )

            match = rule["_regex"].search(
                message
            )

            if not match:
                continue

            fields = match.groupdict()

            relevant = self._build_relevant(
                rule,
                event,
                fields,
            )

            if relevant is not None:
                result["relevant"].append(
                    relevant
                )

            if rule.get("finding"):
                finding = self._process_match(
                    rule,
                    event,
                    fields,
                )

                if finding is not None:
                    result["findings"].append(
                        finding
                    )

        return result


    def _build_relevant(
        self,
        rule,
        event,
        fields,
    ):
        config = rule.get(
            "relevant"
        )

        if not config:
            return None

        display_fields = {}

        for name, template in rule.get(
            "fields",
            {},
        ).items():
            try:
                display_fields[name] = (
                    template.format(**fields)
                )
            except KeyError:
                display_fields[name] = template

        context = {
            **fields,
            **display_fields,
        }

        detail_template = config.get(
            "detail",
            "",
        )

        try:
            detail = detail_template.format(
                **context
            )
        except KeyError:
            detail = detail_template

        return {
            "rule_id": rule["id"],
            "pack": rule["_pack_id"],
            "service": rule["_pack_id"],
            "severity": config.get(
                "severity",
                "info",
            ),
            "title": config.get(
                "title",
                rule.get(
                    "name",
                    rule["id"],
                ),
            ),
            "detail": detail,
            "fields": display_fields,
        }


    def _process_match(
        self,
        rule,
        event,
        fields,
    ):
        timestamp = int(
            event.get(
                "timestamp",
                time.time(),
            )
        )

        group_fields = rule.get(
            "group_by",
            [],
        )

        group_values = tuple(
            fields.get(field, "")
            for field in group_fields
        )

        group_key = (
            rule["id"],
            group_values,
        )

        occurrences = self.occurrences[
            group_key
        ]

        occurrences.append(timestamp)

        collections = self.collections[
            group_key
        ]

        for (
            collection_name,
            collection_config,
        ) in rule.get(
            "_collect",
            {},
        ).items():
            field_name = collection_config[
                "field"
            ]

            value = fields.get(
                field_name
            )

            if value is None:
                continue

            value = str(value)

            if not value:
                continue

            collections[
                collection_name
            ].append(
                (
                    timestamp,
                    value,
                )
            )

        window = rule["_window"]

        if window > 0:
            cutoff = timestamp - window

            while (
                occurrences
                and occurrences[0] < cutoff
            ):
                occurrences.popleft()

            for values in collections.values():
                while (
                    values
                    and values[0][0] < cutoff
                ):
                    values.popleft()

        self.state_dirty = True

        threshold = rule["_threshold"]

        if len(occurrences) < threshold:
            return None

        collection_context = (
            self._build_collection_context(
                rule,
                group_key,
            )
        )

        condition_context = {
            "count": len(occurrences),
            **collection_context,
        }

        if not self._conditions_match(
            rule,
            condition_context,
        ):
            return None

        cooldown = rule["_cooldown"]

        last_finding = self.last_finding.get(
            group_key,
            0,
        )

        if (
            cooldown > 0
            and timestamp - last_finding
            < cooldown
        ):
            return None

        self.last_finding[group_key] = (
            timestamp
        )

        self.state_dirty = True

        finding_config = rule.get(
            "finding",
            {},
        )

        display_fields = {}

        for name, template in rule.get(
            "fields",
            {},
        ).items():
            try:
                display_fields[name] = (
                    template.format(**fields)
                )
            except KeyError:
                display_fields[name] = (
                    template
                )

        return {
            "pattern_id": rule["id"],
            "group_key": "|".join(
                str(value)
                for value in group_values
            ),
            "service": rule["_pack_id"],
            "severity": finding_config.get(
                "severity",
                "warn",
            ),
            "title": finding_config.get(
                "title",
                rule.get(
                    "name",
                    rule["id"],
                ),
            ),
            "detail": self._build_detail(
                rule,
                fields,
                display_fields,
                len(occurrences),
                collection_context,
            ),
            "source_line": event.get(
                "message",
                "",
            ),
        }

    def _conditions_match(
        self,
        rule,
        context,
    ):
        operators = {
            "eq": lambda actual, expected: actual == expected,
            "ne": lambda actual, expected: actual != expected,
            "gt": lambda actual, expected: actual > expected,
            "gte": lambda actual, expected: actual >= expected,
            "lt": lambda actual, expected: actual < expected,
            "lte": lambda actual, expected: actual <= expected,
        }

        for key, config in rule.get(
            "_conditions",
            {},
        ).items():
            actual = context.get(
                key
            )

            if not isinstance(
                actual,
                int,
            ):
                return False

            operator = config[
                "operator"
            ]

            expected = config[
                "value"
            ]

            if not operators[
                operator
            ](
                actual,
                expected,
            ):
                return False

        return True

    def _build_collection_context(
        self,
        rule,
        group_key,
    ):
        context = {}

        collections = self.collections.get(
            group_key,
            {},
        )

        for (
            collection_name,
            collection_config,
        ) in rule.get(
            "_collect",
            {},
        ).items():
            entries = collections.get(
                collection_name,
                (),
            )

            values = [
                value
                for _, value in entries
            ]

            if collection_config.get(
                "distinct",
                False,
            ):
                seen = set()
                distinct_values = []

                for value in values:
                    if value in seen:
                        continue

                    seen.add(value)
                    distinct_values.append(
                        value
                    )

                values = distinct_values

            context[collection_name] = (
                ", ".join(values)
            )

            context[
                f"{collection_name}_count"
            ] = len(values)

        return context

    def _build_detail(
        self,
        rule,
        fields,
        display_fields,
        occurrence_count,
        collection_context=None,
    ):
        finding_config = rule.get(
            "finding",
            {},
        )

        template = finding_config.get(
            "detail",
        )

        if template:
            context = {
                **fields,
                **display_fields,
                **(
                    collection_context
                    or {}
                ),
                "count": occurrence_count,
            }

            try:
                return template.format(**context)
            except KeyError:
                pass

        parts = []

        if occurrence_count > 1:
            parts.append(
                f"{occurrence_count} occurrences"
            )

        for key, value in display_fields.items():
            label = key.replace(
                "_",
                " ",
            ).capitalize()

            parts.append(
                f"{label}: {value}"
            )

        if parts:
            return " · ".join(parts)

        return rule.get(
            "name",
            rule["id"],
        )
