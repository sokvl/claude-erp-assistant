import argparse
import json
import os
import sys
import time
from collections import Counter
from datetime import date, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fastapi.testclient import TestClient  # noqa: E402

from app.assistant import chat  # noqa: E402
from app.assistant.dispatch import run_tool  # noqa: E402
from app.assistant.profiles import PROFILES, Profile  # noqa: E402
from app.assistant.tools import TOOLS  # noqa: E402
from app.assistant.usage import cost_usd, total_tokens  # noqa: E402
from app.config import API_KEY  # noqa: E402
from app.db import get_database  # noqa: E402
from app.main import app  # noqa: E402
from app.routers import chat as chat_router  # noqa: E402
from cases import CASES, Case  # noqa: E402
from grading import grade  # noqa: E402


class Recorder:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.steps: list[chat.TraceStep] = []

    def run_tool(self, db: Any, name: str, tool_input: Any) -> str:
        call = {"name": name, "input": tool_input}
        self.calls.append(call)
        try:
            call["output"] = run_tool(db, name, tool_input)
        except Exception as error:
            call["error"] = str(error)
            raise
        return call["output"]

    def record_usage(
        self, db: Any, conversation_id: str, profile: Profile, steps: list[chat.TraceStep], outcome: str
    ) -> None:
        self.steps.extend(steps)


def first_call(case: Case, recorder: Recorder, db: Any) -> tuple[str, list[str]]:
    request = chat.build_request(PROFILES[case.assistant], TOOLS[case.assistant], date.today())
    generator = chat._stream_once(chat.get_client(), request, [{"role": "user", "content": case.turns[0]}], False, recorder.steps)
    try:
        while True:
            next(generator)
    except StopIteration as stop:
        message = stop.value
    except chat.ChatError as error:
        return "", [f"[error] model call failed: {error.code}"]
    for block in (block for block in message.content if block.type == "tool_use"):
        try:
            recorder.run_tool(db, block.name, block.input)
        except Exception:
            pass
    answer = "".join(block.text for block in message.content if block.type == "text")
    needs_tool = not case.refusal and message.stop_reason != "tool_use"
    return answer, [f"[retrieval] answered without calling a tool first (stop={message.stop_reason})"] * needs_tool


def full_flow(case: Case, recorder: Recorder, http: TestClient) -> tuple[str, list[str]]:
    conversation_id, events = None, []
    for question in case.turns:
        recorder.calls.clear()
        body = {"message": question, "conversation_id": conversation_id, "assistant": case.assistant}
        response = http.post("/chat", json=body, headers={"X-API-Key": API_KEY})
        events = parse_sse(response.text) if response.status_code == 200 else [("error", {"status": response.status_code})]
        conversation_id = next((data["conversation_id"] for name, data in events if name == "conversation"), conversation_id)
        if events[-1][0] != "done":
            return "", [f"[error] turn {question[:60]!r} ended with {events[-1]}"]
    return "".join(data["text"] for name, data in events if name == "text"), []


def run_case(level: str, case: Case, db: Any, catalog: dict[str, Any], http: TestClient) -> dict[str, Any]:
    recorder = Recorder()
    chat.run_tool, chat_router.record_usage = recorder.run_tool, recorder.record_usage
    started_at = time.perf_counter()
    answer, failures = first_call(case, recorder, db) if level == "functional" else full_flow(case, recorder, http)
    failures += grade(case, db, catalog, answer, recorder.calls, final=level == "e2e")
    tokens = total_tokens(recorder.steps)
    return {
        "level": level,
        "case": case.id,
        "passed": not failures,
        "failures": failures,
        "latency_ms": round((time.perf_counter() - started_at) * 1000),
        "model_calls": sum(step.name == "model.call" for step in recorder.steps),
        "tokens": tokens,
        "cost_usd": cost_usd(tokens, PROFILES[case.assistant].model),
        "answer": answer,
        "tool_calls": [{key: value for key, value in call.items() if key != "output"} for call in recorder.calls],
        "trace": chat.format_trace(level, " | ".join(case.turns), recorder.steps, "passed" if not failures else "failed"),
    }


def parse_sse(body: str) -> list[tuple[str, dict[str, Any]]]:
    events = []
    for block in body.strip().split("\n\n"):
        fields = dict(line.split(": ", 1) for line in block.split("\n") if ": " in line and not line.startswith(":"))
        if "event" in fields:
            events.append((fields["event"], json.loads(fields["data"])))
    return events


def main() -> int:
    parser = argparse.ArgumentParser(description="Live evaluation against the real model and the seeded catalog.")
    parser.add_argument("--level", choices=("functional", "e2e", "all"), default="all")
    parser.add_argument("--case", action="append", default=[], help="run only this case id (repeatable)")
    args = parser.parse_args()
    if unknown := set(args.case) - {case.id for case in CASES}:
        parser.error(f"unknown case ids: {sorted(unknown)}")
    if not os.environ.get("ANTHROPIC_API_KEY"):
        parser.error("ANTHROPIC_API_KEY is not set; add it to .env")

    db = get_database()
    catalog = {doc["_id"]: doc for doc in db["products"].find({}, {"listPrice": 1, "category": 1})}
    http = TestClient(app)
    levels = ("functional", "e2e") if args.level == "all" else (args.level,)
    results = []
    for level in levels:
        for case in CASES:
            if (args.case and case.id not in args.case) or (level == "functional" and len(case.turns) > 1):
                continue
            result = run_case(level, case, db, catalog, http)
            results.append(result)
            print(
                f"{level:<11} {'PASS' if result['passed'] else 'FAIL'}  {case.id:<24} {result['model_calls']} calls  "
                f"{result['latency_ms']:>6}ms  {sum(result['tokens'].values()):>6} tok  ${result['cost_usd']:.4f}"
            )
            if not result["passed"]:
                print("\n".join(f"            - {failure}" for failure in result["failures"]))
                print("            " + result["trace"].replace("\n", "\n            "))

    print()
    for level in levels:
        level_results = [result for result in results if result["level"] == level]
        if level_results:
            count = len(level_results)
            tokens = sum((Counter(result["tokens"]) for result in level_results), Counter())
            categories = Counter(failure[1:].split("]")[0] for result in level_results for failure in result["failures"])
            print(
                f"{level:<11} {sum(r['passed'] for r in level_results)}/{count} passed  "
                f"avg {sum(r['model_calls'] for r in level_results) / count:.1f} calls  "
                f"avg {sum(r['latency_ms'] for r in level_results) / count:.0f}ms  "
                f"cost ${sum(r['cost_usd'] for r in level_results):.4f}  "
                f"tokens {dict(tokens)}  failures {dict(categories)}"
            )

    report = ROOT / "evals" / "results" / f"{datetime.now():%Y%m%d-%H%M%S}.json"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps(results, indent=2, default=str))
    print(f"\nreport: {report.relative_to(ROOT)}")
    return 0 if all(result["passed"] for result in results) else 1


if __name__ == "__main__":
    sys.exit(main())
