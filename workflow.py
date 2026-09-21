"""Send a plan to a Codex app thread and track its acknowledged lifecycle."""
import argparse
import datetime as dt
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import uuid

ROOT = Path(__file__).resolve().parent
IMPLEMENTATION_MODEL = "gpt-5.6-sol"
REVIEW_MODEL = "gpt-6-astra"
FINALS = {"complete", "blocked", "needs_design_revision"}
PENDING = {"queued", "dispatch_unknown", "running"}


class WorkflowError(RuntimeError):
    pass


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def atomic(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


class Lock:
    def __init__(self, path):
        self.path = path

    def __enter__(self):
        self.file = self.path.open("a+b")
        try:
            if os.name == "nt":
                import msvcrt
                if self.file.seek(0, 2) == 0:
                    self.file.write(b"0")
                    self.file.flush()
                self.file.seek(0)
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self.file.close()
            raise WorkflowError("workflow operation locked; retry shortly") from exc

    def __exit__(self, *_):
        self.file.close()


def contained(path, root):
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError as exc:
        raise WorkflowError("path resolves outside repository") from exc
    return path.resolve()


def taskdir(raw, repo=ROOT):
    repo = repo.resolve()
    path = contained(repo / raw, repo)
    tasks = contained(repo / "docs/tasks", repo)
    try:
        path.relative_to(tasks)
    except ValueError as exc:
        raise WorkflowError("task outside docs/tasks") from exc
    if path == tasks:
        raise WorkflowError("select a task below docs/tasks")
    plan = contained(path / "plan.md", repo)
    contained(path / ".workflow", repo)
    if not plan.is_file() or not plan.read_text(encoding="utf-8-sig").strip():
        raise WorkflowError("missing/empty plan")
    return path


def command():
    native = shutil.which("codex.exe")
    if native:
        return [native]
    node = shutil.which("node.exe") or shutil.which("node")
    wrapper = shutil.which("codex.cmd")
    if node and wrapper:
        script = Path(wrapper).parent / "node_modules/@openai/codex/bin/codex.js"
        if script.is_file():
            return [node, str(script)]
    raise WorkflowError("Codex CLI not found")


def thread(value, repo):
    if not value:
        try:
            value = read(repo / "workflow-config.json")["thread_id"]
        except (KeyError, TypeError) as exc:
            raise WorkflowError("missing thread config") from exc
    try:
        return str(uuid.UUID(value))
    except (ValueError, TypeError, AttributeError) as exc:
        raise WorkflowError("invalid thread UUID") from exc


def sig(path):
    if not path.is_file() or not path.stat().st_size:
        return None
    stat = path.stat()
    return [stat.st_mtime_ns, stat.st_size]


def quote(value):
    return "'" + str(value).replace("'", "''") + "'"


def request(task, repo, run_id):
    rel = task.relative_to(repo).as_posix()
    base = f"python workflow.py"
    args = f"--task {quote(rel)} --run-id {quote(run_id)}"
    return f"""App workflow request {run_id}.
Working directory: {repo}
Read AGENTS.md and {rel}/plan.md. Preserve existing user changes.
First execute in PowerShell:
Set-Location -LiteralPath {quote(repo)}
{base} claim {args}
If transient operation lock fails, retry shortly. If run is not active or already claimed, STOP.
After successful claim, coordinate a gpt-5.6-sol implementation subagent and a separate
gpt-6-astra review subagent. Explicitly specify models and separate contexts.
Children must not delegate again. Main checks scope and acceptance criteria and reports progress.
Review follows implementation; Sol fixes findings and Astra rechecks. Never substitute models.
Do not invoke Claude, recursively run workflow.py run, commit, push, or deploy.
Update {rel}/handoff.md and {rel}/review.md for this run.
Then record the final outcome with:
{base} finish {args} --status STATUS --summary 'SUMMARY' --implementation-model 'MODEL' --review-model 'MODEL'
Replace placeholders; STATUS is complete, blocked, or needs_design_revision.
Use complete only after fresh artifacts and required verification pass.
Model names are self-reports, not independent proof. Use empty strings for models not run.
On missing capabilities or failed verification, record blocked with a concrete reason.
Do not edit workflow state directly. Finish must succeed before reporting recorded completion.
"""


def read(path):
    try:
        result = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        raise WorkflowError(f"missing/malformed JSON: {path}") from exc
    if not isinstance(result, dict):
        raise WorkflowError(f"expected JSON object: {path}")
    return result


def save(task, state):
    state["updated_at"] = now()
    atomic(task / ".workflow" / state["run_id"] / "state.json", state)
    atomic(task / ".workflow/state.json", state)


def validate_timeout(value):
    if not math.isfinite(value) or value <= 0:
        raise WorkflowError("timeout must be positive and finite")


def run(raw, thread_id=None, dry_run=False, timeout=60, repo=ROOT):
    validate_timeout(timeout)
    repo = repo.resolve()
    task = taskdir(raw, repo)
    target = thread(thread_id, repo)
    cli = command()
    if dry_run:
        return {"command": cli + ["queue", "--thread", target, "--message", "<message>"],
                "request": request(task, repo, "<run-id>")}
    marker = contained(repo / ".workflow-active.json", repo)
    with Lock(contained(repo / ".workflow.lock", repo)):
        if marker.exists():
            raise WorkflowError("active workflow exists; inspect status before another run")
        run_id = str(uuid.uuid4())
        run_dir = task / ".workflow" / run_id
        run_dir.mkdir(parents=True)
        request_path = run_dir / "request.md"
        request_path.write_text(request(task, repo, run_id), encoding="utf-8")
        state = {
            "run_id": run_id, "task": task.relative_to(repo).as_posix(),
            "thread_id": target, "status": "dispatch_unknown", "created_at": now(),
            "request": str(request_path), "model_verification": "self_report",
            "implementation_model": "", "review_model": "",
            "before": {name: sig(task / name) for name in ("handoff.md", "review.md")},
        }
        save(task, state)
        atomic(marker, {"run_id": run_id, "task": state["task"]})

    # The app may claim and even finish while queue is still returning.
    message = f"Read and execute the workflow request at {json.dumps(str(request_path), ensure_ascii=False)}. Working directory: {json.dumps(str(repo), ensure_ascii=False)}."
    dispatched, detail = False, ""
    try:
        result = subprocess.run(
            cli + ["queue", "--thread", target, "--message", message],
            cwd=repo, capture_output=True, text=True, encoding="utf-8",
            errors="replace", shell=False, timeout=timeout,
        )
        (run_dir / "queue.stdout.log").write_text(result.stdout, encoding="utf-8")
        (run_dir / "queue.stderr.log").write_text(result.stderr, encoding="utf-8")
        dispatched = result.returncode == 0
        detail = f"queue exit {result.returncode}"
    except (subprocess.TimeoutExpired, OSError, KeyboardInterrupt) as exc:
        detail = f"dispatch uncertain: {type(exc).__name__}: {exc}"

    with Lock(repo / ".workflow.lock"):
        current = read(task / ".workflow/state.json")
        if current["run_id"] != run_id:
            return read(run_dir / "state.json")
        if current["status"] == "dispatch_unknown":
            current["status"] = "queued" if dispatched else "dispatch_unknown"
        current["dispatch_summary"] = detail
        save(task, current)
        return current


def correlated(raw, run_id, repo):
    task = taskdir(raw, repo)
    marker = repo / ".workflow-active.json"
    state = read(task / ".workflow/state.json")
    active = read(marker) if marker.exists() else {}
    if (active.get("run_id") != run_id or state.get("run_id") != run_id
            or active.get("task") != task.relative_to(repo).as_posix()):
        raise WorkflowError("run is not active")
    return task, marker, state


def claim(raw, run_id, repo=ROOT):
    repo = repo.resolve()
    with Lock(repo / ".workflow.lock"):
        task, _, state = correlated(raw, run_id, repo)
        if state["status"] not in {"queued", "dispatch_unknown"}:
            raise WorkflowError("cannot claim: already claimed or finished")
        state["status"] = "running"
        save(task, state)
        return state


def finish(raw, run_id, result, repo=ROOT):
    repo = repo.resolve()
    with Lock(repo / ".workflow.lock"):
        task, marker, state = correlated(raw, run_id, repo)
        if state["status"] in FINALS and all(state.get(key) == value for key, value in result.items()) and result.get("status") == state["status"]:
            marker.unlink()
            return state
        if state["status"] != "running" or result.get("status") not in FINALS:
            raise WorkflowError("invalid finish")
        keys = {"status", "summary", "implementation_model", "review_model"}
        if set(result) != keys or any(not isinstance(result[key], str) for key in keys):
            raise WorkflowError("invalid result fields")
        if result["status"] == "complete":
            if (result["implementation_model"] != IMPLEMENTATION_MODEL
                    or result["review_model"] != REVIEW_MODEL):
                raise WorkflowError("reported model mismatch")
            for name in ("handoff.md", "review.md"):
                if sig(task / name) is None or sig(task / name) == state["before"][name]:
                    raise WorkflowError("fresh artifacts required")
        state.update(result)
        state["finished_at"] = now()
        save(task, state)
        marker.unlink()
        return state


def abandon(raw, run_id, repo=ROOT):
    repo = repo.resolve()
    with Lock(repo / ".workflow.lock"):
        task, marker, state = correlated(raw, run_id, repo)
        state.update(status="abandoned", summary="Does not cancel app work; stop it in app before starting another run.")
        save(task, state)
        marker.unlink()
        return state


def status(raw, repo=ROOT):
    return read(taskdir(raw, repo) / ".workflow/state.json")


def wait_for(raw, timeout, repo=ROOT):
    if not math.isfinite(timeout) or timeout < 0:
        raise WorkflowError("wait timeout must be nonnegative and finite")
    end = time.monotonic() + timeout
    initial = status(raw, repo)["run_id"]
    while True:
        state = status(raw, repo)
        if state["run_id"] != initial:
            raise WorkflowError("task run changed while waiting")
        if state["status"] not in PENDING:
            return state
        if time.monotonic() >= end:
            return {**state, "wait_timed_out": True}
        time.sleep(min(1, max(0, end - time.monotonic())))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    for action in ("run", "claim", "finish", "abandon", "status", "wait"):
        child = sub.add_parser(action)
        child.add_argument("--task", required=True)
        if action in {"claim", "finish", "abandon"}:
            child.add_argument("--run-id", required=True)
        if action in {"run", "wait"}:
            child.add_argument("--timeout", type=float, default=60)
        if action == "run":
            child.add_argument("--thread")
            child.add_argument("--dry-run", action="store_true")
        if action == "finish":
            child.add_argument("--status", choices=sorted(FINALS), required=True)
            child.add_argument("--summary", required=True)
            child.add_argument("--implementation-model", default="")
            child.add_argument("--review-model", default="")
    args = parser.parse_args(argv)
    try:
        if args.action == "run":
            out = run(args.task, args.thread, args.dry_run, args.timeout)
        elif args.action == "claim":
            out = claim(args.task, args.run_id)
        elif args.action == "finish":
            out = finish(args.task, args.run_id, {
                "status": args.status, "summary": args.summary,
                "implementation_model": args.implementation_model, "review_model": args.review_model,
            })
        elif args.action == "abandon":
            out = abandon(args.task, args.run_id)
        elif args.action == "wait":
            out = wait_for(args.task, args.timeout)
        else:
            out = status(args.task)
        print(json.dumps(out, ensure_ascii=False, indent=2))
        if args.action in {"run", "wait"}:
            if out.get("wait_timed_out"):
                return 5
            return {"blocked": 3, "needs_design_revision": 4, "dispatch_unknown": 6,
                    "abandoned": 7}.get(out.get("status"), 0)
        return 0
    except (WorkflowError, OSError, UnicodeError) as exc:
        print(f"workflow: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
