import json
import os
import re
import time
from collections import defaultdict, deque
from pathlib import Path

import yaml


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
            "_window": int(
                aggregate.get(
                    "window_seconds",
                    0,
                )
            ),
            "_threshold": int(
                aggregate.get(
                    "threshold",
                    1,
                )
            ),
            "_cooldown": int(
                aggregate.get(
                    "cooldown_seconds",
                    0,
                )
            ),
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

        window = rule["_window"]

        if window > 0:
            cutoff = timestamp - window

            while (
                occurrences
                and occurrences[0] < cutoff
            ):
                occurrences.popleft()

        self.state_dirty = True

        threshold = rule["_threshold"]

        if len(occurrences) < threshold:
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
            ),
            "suggest": "",
            "source_line": event.get(
                "message",
                "",
            ),
        }

    def _build_detail(
        self,
        rule,
        fields,
        display_fields,
        occurrence_count,
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
