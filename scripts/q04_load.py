"""Q04 HTTP measurements. Missing configuration/errors never count as a pass."""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from http.cookiejar import Cookie, CookieJar
from http.client import HTTPException, HTTPConnection, HTTPSConnection
from functools import partial
import ipaddress
import ssl
from html.parser import HTMLParser
import json
import math
import os
from pathlib import Path
import platform
import re
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPCookieProcessor, HTTPRedirectHandler, HTTPHandler, HTTPSHandler, Request, build_opener
from uuid import uuid4

REQUIRED = ("intake", "list", "detail", "tracking", "queue", "action")
TARGETS = {name: (1500 if name in ("queue", "action") else 2000) for name in REQUIRED}
MAX_BODY = 2 * 1024 * 1024


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class SourceHTTP(HTTPHandler):
    def __init__(self, source):
        super().__init__()
        self.source = source

    def http_open(self, request):
        return self.do_open(partial(HTTPConnection, source_address=(self.source, 0)), request)


class SourceHTTPS(HTTPSHandler):
    def __init__(self, source):
        super().__init__()
        self.source = source
        self.context = ssl.create_default_context()

    def https_open(self, request):
        return self.do_open(partial(HTTPSConnection, source_address=(self.source, 0)),
                            request, context=self.context)


class HiddenInputs(HTMLParser):
    def __init__(self):
        super().__init__()
        self.values = {}

    def handle_starttag(self, tag, attrs):
        data = dict(attrs)
        if tag == "input" and data.get("name") in {"csrfmiddlewaretoken", "request_token"}:
            self.values[data["name"]] = data.get("value", "")


def percentile(values, fraction):
    if not values:
        return None
    return sorted(values)[max(0, math.ceil(len(values) * fraction) - 1)]


def check_case(case):
    assert case["name"] in REQUIRED, "Unknown Q04 scenario name."
    assert case.get("method", "GET") in ("GET", "POST"), "Only GET/POST are supported."
    assert case.get("role") in ("ANONYMOUS", "COMPLAINANT", "HEAD", "STAFF"), "Choose a test role."
    assert 0 < case["threshold_ms"] <= TARGETS[case["name"]], "Threshold cannot weaken the SRS target."
    for path in [case["path"], case.get("prepare_path", case["path"])]:
        parsed = urlsplit(path)
        assert path.startswith("/") and not path.startswith("//") and not parsed.scheme and not parsed.netloc and not parsed.fragment, "Use same-origin relative paths."
    assert case.get("expect_pattern"), "Supply an operation-specific success pattern."
    re.compile(case["expect_pattern"])
    assert type(case.get("expect_status", 200)) is int and 200 <= case.get("expect_status", 200) < 400
    if case["name"] in {"intake", "tracking", "action"}:
        assert case.get("method") == "POST", "Benchmark a real POST operation, not its form GET."
    if case.get("method") == "POST":
        assert case.get("prepare_path"), "POST requires a fresh CSRF form."
    if case["name"] == "intake":
        assert case.get("method") == "POST" and case.get("fresh_operation_token") is True, "Intake must use a new operation token, not a replay."
    if case.get("record_pattern"):
        re.compile(case["record_pattern"])
        assert 0 <= case.get("min_records", 1) <= case["max_records"] <= 25, "Pagination maximum must be at most 25."


def read_response(opener, request, timeout):
    try:
        response = opener.open(request, timeout=timeout)
    except HTTPError as error:
        response = error
    with response:
        content = response.read(MAX_BODY + 1)
        if len(content) > MAX_BODY:
            raise ValueError("response_too_large")
        return response.status, response.headers.get("Location", ""), content.decode("utf-8", "replace")


class ActorClient:
    def __init__(self, origin, actor, cookie_name="sessionid"):
        self.origin = origin
        self.jar = CookieJar()
        if actor and actor.get("session_cookie"):
            host = urlsplit(origin).hostname
            self.jar.set_cookie(Cookie(0, cookie_name, actor["session_cookie"], None, False,
                host, False, False, "/", True, origin.startswith("https:"), None, True, None, None, {}))
        # Ignore ambient HTTP_PROXY settings; the configured test ingress is the target.
        from urllib.request import ProxyHandler
        handlers = [ProxyHandler({}), NoRedirect(), HTTPCookieProcessor(self.jar)]
        if actor and actor.get("source_address"):
            source = str(ipaddress.ip_address(actor["source_address"]))
            handlers.extend([SourceHTTP(source), SourceHTTPS(source)])
        self.opener = build_opener(*handlers)

    def operation(self, case, payload, tokens, lock, timeout=30):
        operation_start = time.perf_counter()
        request_start = None
        try:
            data = dict(payload)
            if case.get("method") == "POST":
                status, _, form = read_response(self.opener, Request(self.origin + case["prepare_path"]), timeout)
                if status != 200:
                    return {"status": status, "elapsed_ms": (time.perf_counter() - operation_start) * 1000, "error": "preparation_failed"}
                parser = HiddenInputs()
                parser.feed(form)
                csrf = parser.values.get("csrfmiddlewaretoken")
                if not csrf:
                    return {"status": None, "elapsed_ms": (time.perf_counter() - operation_start) * 1000, "error": "missing_csrf"}
                data.update(parser.values)
                if case.get("fresh_operation_token"):
                    token = parser.values.get("request_token")
                    with lock:
                        if not token or token in tokens:
                            return {"status": None, "elapsed_ms": (time.perf_counter() - operation_start) * 1000, "error": "missing_or_reused_operation_token"}
                        tokens.add(token)
                request = Request(self.origin + case["path"], data=urlencode(data).encode(), method="POST",
                    headers={"Content-Type": "application/x-www-form-urlencoded", "Origin": self.origin})
            else:
                request = Request(self.origin + case["path"])
            request_start = time.perf_counter()
            status, location, body = read_response(self.opener, request, timeout)
            elapsed = (time.perf_counter() - request_start) * 1000
            error = None
            if status != case.get("expect_status", 200):
                error = "unexpected_status"
            elif status >= 300:
                parsed = urlsplit(location)
                if (parsed.netloc and parsed.netloc != urlsplit(self.origin).netloc) or "/login" in parsed.path or not re.search(case["expect_pattern"], location):
                    error = "unexpected_redirect"
            elif not re.search(case["expect_pattern"], body):
                error = "unexpected_content"
            if error is None and case.get("record_pattern"):
                count = len(re.findall(case["record_pattern"], body))
                if not case.get("min_records", 1) <= count <= case["max_records"]:
                    error = "pagination_failed"
            return {"status": status, "elapsed_ms": elapsed, "error": error}
        except (URLError, OSError, ValueError, HTTPException):
            # Do not serialize exception text, URLs, headers, credentials or bodies.
            return {"status": None, "elapsed_ms": (time.perf_counter() - (request_start or operation_start)) * 1000, "error": "transport_or_response_error"}


def summarize(samples, threshold):
    failures = Counter(row["error"] for row in samples if row["error"])
    durations = [row["elapsed_ms"] for row in samples]
    p95 = percentile(durations, .95)
    return {"status": "PASS" if samples and not failures and p95 <= threshold else "FAIL",
            "requests": len(samples), "failed_requests": sum(failures.values()),
            "errors": dict(failures), "p50_ms": percentile(durations, .5), "p95_ms": p95,
            "maximum_ms": max(durations) if durations else None, "threshold_ms": threshold,
            "samples": samples}


def run_case(case, origin, actors, users, iterations, run_id):
    check_case(case)
    iterations = case.get("iterations_per_user", iterations)
    assert type(iterations) is int and 1 <= iterations <= 100, "Use 1–100 iterations per user."
    payload = dict(case.get("payload", {}))
    for key, variable in case.get("payload_env", {}).items():
        value = os.environ.get(variable)
        if not value:
            return {"name": case["name"], "status": "BLOCKED", "reason": "missing_payload_environment"}
        payload[key] = value
    selected = (actors.get("ANONYMOUS", [None] * users)[:users] if case["role"] == "ANONYMOUS"
                else actors.get(case["role"], [])[:users])
    if len(selected) != users or (case["role"] != "ANONYMOUS" and (
            len({row.get("account_key") for row in selected}) != users
            or any(not row.get("account_key") or not row.get("session_cookie") for row in selected)
            or len({row["session_cookie"] for row in selected}) != users)):
        return {"name": case["name"], "status": "BLOCKED", "reason": "distinct_test_accounts_required"}
    operations = None
    if case["name"] == "action":
        operations = [(actor or {}).get("operations", {}).get("action", []) for actor in selected]
        if any(len(rows) < iterations + 1 for rows in operations):
            return {"name": "action", "status": "BLOCKED", "reason": "distinct_prepared_action_targets_required"}
        keys = [row.get("target_key") for rows in operations for row in rows[:iterations + 1]]
        if any(not key for key in keys) or len(set(keys)) != users * (iterations + 1):
            return {"name": "action", "status": "BLOCKED", "reason": "distinct_prepared_action_targets_required"}
    clients = [ActorClient(origin, actor) for actor in selected]
    tokens, lock = set(), threading.Lock()

    def data(worker, iteration):
        return {key: str(value).replace("{run_id}", run_id).replace("{worker}", str(worker))
                .replace("{iteration}", str(iteration)) for key, value in payload.items()}

    def attempt(worker, iteration):
        effective = dict(case)
        fields = data(worker, iteration)
        if operations is not None:
            operation = operations[worker][iteration + 1]
            for key in ("path", "prepare_path"):
                effective[key] = operation[key]
            fields.update(operation.get("payload", {}))
            check_case(effective)
        return clients[worker].operation(effective, fields, tokens, lock)

    # One validated operation per user warms connections/permissions/CSRF. POST
    # warmups also create test records: include them in the dataset inventory.
    with ThreadPoolExecutor(max_workers=users) as pool:
        warmup = list(pool.map(lambda i: attempt(i, -1), range(users)))
    if any(row["error"] for row in warmup):
        return {"name": case["name"], "status": "BLOCKED", "reason": "warmup_validation_failed",
                "errors": dict(Counter(row["error"] for row in warmup if row["error"]))}
    barrier = threading.Barrier(users)

    def work(index):
        barrier.wait(timeout=60)
        return [attempt(index, number) for number in range(iterations)]

    with ThreadPoolExecutor(max_workers=users) as pool:
        samples = [row for rows in pool.map(work, range(users)) for row in rows]
    return {"name": case["name"], "users": users, "iterations_per_user": iterations,
            "warmup_operations": users, "pagination_checked": bool(case.get("record_pattern")),
            **summarize(samples, case["threshold_ms"])}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--actors", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    config = json.loads(args.config.read_text())
    origin = os.environ.get("SCMS_Q04_BASE_URL", "").rstrip("/")
    parsed = urlsplit(origin)
    metadata = config.get("environment", {})
    configured = (parsed.scheme in {"http", "https"} and bool(parsed.netloc)
                  and not parsed.username and not parsed.password and parsed.path in {"", "/"}
                  and not parsed.query and not parsed.fragment
                  and re.fullmatch(r"[a-f0-9]{40}", metadata.get("source_revision", ""))
                  and metadata.get("database_engine") in {"postgresql", "sqlite"}
                  and metadata.get("dataset_description") and metadata.get("network_conditions"))
    report = {"started_at_utc": datetime.now(timezone.utc).isoformat(), "run_id": uuid4().hex, "status": "BLOCKED", "results": [],
              "scope": "HTTP latency and configured pagination only; other Q04 targets remain pending",
              "runtime": {"python": platform.python_version(), "system": platform.system(), "cpus": os.cpu_count()}}
    users, iterations = config.get("users", 50), config.get("iterations_per_user", 10)
    assert users == 50 and type(iterations) is int and 1 <= iterations <= 100, "Q04 requires 50 users and 1–100 iterations."
    if not configured:
        report["reason"] = "deployment_origin_revision_dataset_and_network_details_required"
    else:
        # Metadata is deliberately explicit. Never include actors/session cookies.
        report["environment"] = {key: metadata[key] for key in (
            "source_revision", "database_engine", "dataset_description", "network_conditions")}
        report["target_origin_sha256"] = __import__("hashlib").sha256(origin.encode()).hexdigest()
        actors = json.loads(args.actors.read_text()) if args.actors else {}
        cases = config.get("cases", [])
        assert len({case["name"] for case in cases}) == len(cases), "Duplicate scenario name."
        for case in cases:
            if not case.get("enabled", False):
                report["results"].append({"name": case["name"], "status": "BLOCKED", "reason": "scenario_not_configured"})
            else:
                report["results"].append(run_case(case, origin, actors, users, iterations, report["run_id"]))
        measured = {row["name"]: row for row in report["results"]}
        complete = all(name in measured and measured[name]["status"] == "PASS" for name in REQUIRED)
        pagination = all(measured.get(name, {}).get("pagination_checked") for name in ("list", "queue"))
        report["status"] = "HTTP_CHECKS_PASS" if complete and pagination else "INCOMPLETE_OR_FAILED"
        report["remaining_q04_checks"] = ["5000_complaint_escalation", "12_month_report", "5MB_upload_at_2Mbps", "other_applicable_paginated_lists"]
    report["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as destination:
        json.dump(report, destination, indent=2)
        destination.write("\n")
    print(json.dumps({"status": report["status"], "scenarios": len(report["results"])}))
    return 0 if report["status"] == "HTTP_CHECKS_PASS" else 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (AssertionError, KeyError, ValueError, OSError, TypeError, re.error):
        raise SystemExit("Q04 configuration/output error; no performance pass recorded.") from None
