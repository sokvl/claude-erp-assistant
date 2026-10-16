import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCENARIOS = [
    ("A", "w=1, primary cut off", ["scripts/cap/split_primary.sh", "1"]),
    ("B", "w=majority, primary cut off", ["scripts/cap/split_primary.sh", "majority"]),
    ("CD", "set-wide client and local vs majority reads", ["scripts/cap/split_clients.sh"]),
]


def run(logs):
    summaries = {}
    for key, title, command in SCENARIOS:
        summary = logs / f"{key}.summary.json"
        output = logs / f"{key}.log"
        print(f"{key:<3}{title:<46}", end="", flush=True)
        started = time.monotonic()
        with output.open("w") as stream:
            result = subprocess.run(
                command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT,
                env={**os.environ, "CAP_LOGS": str(logs), "CAP_SUMMARY": str(summary)},
            )
        if result.returncode != 0 or not summary.exists():
            print(f"FAILED, see {output}")
            sys.exit(1)
        print(f"done in {time.monotonic() - started:.0f} s")
        summaries[key] = json.loads(summary.read_text())
    return summaries


def isolated_window(summary):
    log = json.loads(Path(summary["log"]).read_text())["log"]
    during = [e for e in log if summary["isolate_at"] <= e["at"] < summary["heal_at"] and e["outcome"] == "acked"]
    return len(during), (during[-1]["at"] - summary["isolate_at"] if during else 0.0)


def longest_gap(log_path):
    acked = [e["at"] for e in json.loads(Path(log_path).read_text())["log"] if e["outcome"] == "acked"]
    return max(later - earlier for earlier, later in zip(acked, acked[1:]))


def errors(failed):
    return ", ".join(f"{count}x {name}" for name, count in sorted(failed.items())) or "-"


def table(title, header, rows):
    widths = [max(len(str(row[i])) for row in [header, *rows]) for i in range(len(header))]
    line = "  ".join("{:<%d}" % w for w in widths)
    print(f"\n{title}")
    print(line.format(*header))
    print(line.format(*("-" * w for w in widths)))
    for row in rows:
        print(line.format(*row))


def report(s):
    a, b, cd = s["A"], s["B"], s["CD"]
    window = {key: isolated_window(s[key]) for key in ("A", "B")}
    table(
        "A/B  writes straight to the primary while it is cut off for 15 s",
        ["", "A  w=1", "B  w=majority"],
        [
            ["primary cut off", a["node"], b["node"]],
            ["new primary", a["new_primary"], b["new_primary"]],
            ["writes attempted", a["check"]["attempted"], b["check"]["attempted"]],
            ["acknowledged", a["check"]["acked"], b["check"]["acked"]],
            ["acknowledged while cut off", window["A"][0], window["B"][0]],
            ["last ack after the cut (s)", f"{window['A'][1]:.1f}", f"{window['B'][1]:.1f}"],
            ["ACKNOWLEDGED BUT LOST", a["check"]["lost"], b["check"]["lost"]],
            ["stored although reported failed", a["check"]["stored_failed"], b["check"]["stored_failed"]],
            ["orders in rollback files", a["rolled_back"], b["rolled_back"]],
            ["slowest write (ms)", a["check"]["slowest_ms"], b["check"]["slowest_ms"]],
            ["errors", errors(a["check"]["failed"]), errors(b["check"]["failed"])],
        ],
    )
    c = cd["c_check"]
    table(
        "C  client connected to the whole set, w=majority",
        ["", "value"],
        [
            ["primary cut off / new primary", f"{cd['node']} / {cd['new_primary']}"],
            ["longest stretch without an ack (s)", f"{longest_gap(cd['c_log']):.1f}"],
            ["acknowledged / attempted", f"{c['acked']} / {c['attempted']}"],
            ["ACKNOWLEDGED BUT LOST", c["lost"]],
            ["errors", errors(c["failed"])],
        ],
    )
    table(
        "D  reads on the node that was cut off",
        ["moment", "role", "local sees", "majority sees"],
        [
            *[[row["label"], row["role"], row["local"], row["majority"]] for row in cd["d_rows"]],
            ["after heal, whole set", "", "", cd["d_after_heal"]],
            ["orders in rollback files", "", "", cd["rolled_back"]],
        ],
    )


def main():
    logs = Path(tempfile.mkdtemp(prefix="cap_lab_"))
    print(f"full logs in {logs}\n")
    report(run(logs))


if __name__ == "__main__":
    main()
