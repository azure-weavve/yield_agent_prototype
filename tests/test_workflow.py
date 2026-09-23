import json,subprocess
from pathlib import Path
import pytest,workflow
T="01a09fca-5435-4323-b405-6197bc8de216"
def env(tmp_path):
 r=tmp_path/"r";t=r/"docs/tasks/a";t.mkdir(parents=True);(t/"plan.md").write_text("p");(r/"workflow-config.json").write_text(json.dumps({"thread_id":T}));return r,t
def complete(summary="ok"):
 return {"status":"complete","summary":summary,
  "implementation_model":workflow.IMPLEMENTATION_MODEL,
  "scoped_review_model":workflow.SCOPED_REVIEW_MODEL,
  "scoped_review_effort":workflow.SCOPED_REVIEW_EFFORT,
  "review_model":workflow.REVIEW_MODEL,"review_effort":workflow.REVIEW_EFFORT}
def mock(monkeypatch,code=0,timeout=False):
 calls=[]
 monkeypatch.setattr(workflow,"command",lambda:["node","codex.js"])
 def f(a,**k):
  calls.append((a,k))
  if timeout:raise subprocess.TimeoutExpired(a,1)
  return subprocess.CompletedProcess(a,code,"ok","err")
 monkeypatch.setattr(subprocess,"run",f);return calls
def test_dry_run_no_write(tmp_path,monkeypatch):
 r,t=env(tmp_path);calls=mock(monkeypatch);before=list(r.rglob("*"));x=workflow.run("docs/tasks/a",dry_run=True,repo=r)
 assert before==list(r.rglob("*")) and not calls and x["command"][-1]=="<message>"
def test_queue_claim_finish_and_global_lock(tmp_path,monkeypatch):
 r,t=env(tmp_path);calls=mock(monkeypatch);s=workflow.run("docs/tasks/a",repo=r)
 assert s["status"]=="queued" and calls[0][1]["shell"] is False
 with pytest.raises(workflow.WorkflowError):workflow.run("docs/tasks/a",repo=r)
 workflow.claim("docs/tasks/a",s["run_id"],repo=r)
 with pytest.raises(workflow.WorkflowError):workflow.claim("docs/tasks/a",s["run_id"],repo=r)
 (t/"handoff.md").write_text("h");(t/"review.md").write_text("r")
 out=workflow.finish("docs/tasks/a",s["run_id"],complete(),repo=r)
 assert out["status"]=="complete" and not (r/".workflow-active.json").exists()
def test_stale_and_missing_artifacts(tmp_path,monkeypatch):
 r,t=env(tmp_path);mock(monkeypatch);s=workflow.run("docs/tasks/a",repo=r);workflow.claim("docs/tasks/a",s["run_id"],repo=r)
 with pytest.raises(workflow.WorkflowError):workflow.finish("docs/tasks/a","bad",{},repo=r)
 with pytest.raises(workflow.WorkflowError):workflow.finish("docs/tasks/a",s["run_id"],complete("x"),repo=r)
def test_ambiguous_retained_until_abandon(tmp_path,monkeypatch):
 r,t=env(tmp_path);mock(monkeypatch,timeout=True);s=workflow.run("docs/tasks/a",repo=r)
 assert s["status"]=="dispatch_unknown" and (r/".workflow-active.json").exists()
 workflow.abandon("docs/tasks/a",s["run_id"],repo=r)
 with pytest.raises(workflow.WorkflowError):workflow.claim("docs/tasks/a",s["run_id"],repo=r)
def test_wait_does_not_cancel(tmp_path,monkeypatch):
 r,t=env(tmp_path);mock(monkeypatch);workflow.run("docs/tasks/a",repo=r)
 assert workflow.wait_for("docs/tasks/a",0,repo=r)["wait_timed_out"] and (r/".workflow-active.json").exists()

def test_immediate_app_finish_not_overwritten_by_dispatch(tmp_path, monkeypatch):
 r,t=env(tmp_path)
 monkeypatch.setattr(workflow,"command",lambda:["node","codex.js"])
 def consume(argv, **kwargs):
  state=workflow.status("docs/tasks/a",repo=r)
  workflow.claim("docs/tasks/a",state["run_id"],repo=r)
  (t/"handoff.md").write_text("new implementation")
  (t/"review.md").write_text("new review")
  workflow.finish("docs/tasks/a",state["run_id"],complete("done"),repo=r)
  return subprocess.CompletedProcess(argv,0,"queued","")
 monkeypatch.setattr(subprocess,"run",consume)
 assert workflow.run("docs/tasks/a",repo=r)["status"]=="complete"
 assert not (r/".workflow-active.json").exists()

def test_cross_task_block_and_wrong_model(tmp_path,monkeypatch):
 r,t=env(tmp_path);mock(monkeypatch)
 other=r/"docs/tasks/b";other.mkdir();(other/"plan.md").write_text("plan")
 state=workflow.run("docs/tasks/a",repo=r)
 with pytest.raises(workflow.WorkflowError,match="active"):
  workflow.run("docs/tasks/b",repo=r)
 workflow.claim("docs/tasks/a",state["run_id"],repo=r)
 with pytest.raises(workflow.WorkflowError,match="model"):
  workflow.finish("docs/tasks/a",state["run_id"],{
   **complete("done"),"implementation_model":"other"},repo=r)

def test_request_quotes_paths_and_queue_pointer_absolute(tmp_path,monkeypatch):
 r,t=env(tmp_path);calls=mock(monkeypatch)
 special=r/"docs/tasks/한글 task's";special.mkdir();(special/"plan.md").write_text("plan")
 state=workflow.run("docs/tasks/한글 task's",repo=r)
 text=Path(state["request"]).read_text(encoding="utf-8")
 assert "--task 'docs/tasks/한글 task''s'" in text
 assert str(r) in text
 assert Path(state["request"]).is_absolute()
 assert json.dumps(state["request"],ensure_ascii=False) in calls[0][0][-1]

@pytest.mark.parametrize("value",["-"*36,"bad",123])
def test_invalid_thread(tmp_path,value):
 with pytest.raises(workflow.WorkflowError):workflow.thread(value,tmp_path)

@pytest.mark.parametrize("value",[-1,0,float("nan"),float("inf")])
def test_invalid_timeout(tmp_path,value):
 with pytest.raises(workflow.WorkflowError):workflow.run("anything",timeout=value,repo=tmp_path)

def test_oserror_retains_active_marker(tmp_path,monkeypatch):
 r,t=env(tmp_path);mock(monkeypatch)
 def fail(*args,**kwargs):raise OSError("launch failed")
 monkeypatch.setattr(subprocess,"run",fail)
 assert workflow.run("docs/tasks/a",repo=r)["status"]=="dispatch_unknown"
 assert (r/".workflow-active.json").exists()

def test_path_escape_rejected(tmp_path):
 r,t=env(tmp_path)
 with pytest.raises(workflow.WorkflowError):workflow.taskdir("../outside",r)

def test_finish_recovers_marker_after_final_write(tmp_path,monkeypatch):
 r,t=env(tmp_path);mock(monkeypatch);state=workflow.run("docs/tasks/a",repo=r)
 workflow.claim("docs/tasks/a",state["run_id"],repo=r)
 final={"status":"blocked","summary":"reason","implementation_model":"",
  "scoped_review_model":"","scoped_review_effort":"","review_model":"","review_effort":""}
 saved=workflow.status("docs/tasks/a",repo=r);saved.update(final);workflow.save(t,saved)
 assert workflow.finish("docs/tasks/a",state["run_id"],final,repo=r)["status"]=="blocked"
 assert not (r/".workflow-active.json").exists()

def test_request_describes_ownership_review_order_and_docs(tmp_path):
 r,t=env(tmp_path);text=workflow.request(t,r,"run")
 for phrase in (
  "owner: codex", "needs_design_revision", "gpt-5.6-terra",
  "gpt-5.6-sol at high effort", "Only after Sol passes",
  "gpt-6-astra at low effort", "reviewers never edit product code",
  "Astra never edits product code", "Codex scoped review — Sol (high effort)",
 "Integrated final review — Astra (low effort)", "self-reports, not independent proof",
  "--scoped-review-model", "--scoped-review-effort", "--review-effort",
  "Sonnet and reviewed by Opus at high", "no\nblocking findings remain",
 ):
  assert phrase in text
 finish_line=next(line for line in text.splitlines() if line.startswith("python workflow.py finish"))
 assert "\\" not in finish_line
 for flag in ("--implementation-model", "--scoped-review-model", "--scoped-review-effort", "--review-model", "--review-effort"):
  assert flag in finish_line

def test_complete_persists_all_reports(tmp_path,monkeypatch):
 r,t=env(tmp_path);mock(monkeypatch);state=workflow.run("docs/tasks/a",repo=r)
 workflow.claim("docs/tasks/a",state["run_id"],repo=r)
 (t/"handoff.md").write_text("h");(t/"review.md").write_text("r")
 assert workflow.finish("docs/tasks/a",state["run_id"],complete(),repo=r) == workflow.status("docs/tasks/a",repo=r)
 saved=workflow.status("docs/tasks/a",repo=r)
 for key,value in complete().items(): assert saved[key] == value

@pytest.mark.parametrize("field,value",[
 ("scoped_review_model",""),("scoped_review_effort","medium"),("review_effort","high"),
])
def test_complete_rejects_missing_or_wrong_review_reports_without_finishing(tmp_path,monkeypatch,field,value):
 r,t=env(tmp_path);mock(monkeypatch);state=workflow.run("docs/tasks/a",repo=r)
 workflow.claim("docs/tasks/a",state["run_id"],repo=r)
 (t/"handoff.md").write_text("h");(t/"review.md").write_text("r")
 result=complete();result[field]=value
 with pytest.raises(workflow.WorkflowError): workflow.finish("docs/tasks/a",state["run_id"],result,repo=r)
 assert workflow.status("docs/tasks/a",repo=r)["status"] == "running"
 assert (r/".workflow-active.json").exists()

def test_complete_legacy_reports_cannot_bypass_new_contract(tmp_path,monkeypatch):
 r,t=env(tmp_path);mock(monkeypatch);state=workflow.run("docs/tasks/a",repo=r)
 workflow.claim("docs/tasks/a",state["run_id"],repo=r)
 (t/"handoff.md").write_text("h");(t/"review.md").write_text("r")
 legacy={key:complete()[key] for key in workflow.LEGACY_RESULT_FIELDS}
 with pytest.raises(workflow.WorkflowError,match="invalid result"):
  workflow.finish("docs/tasks/a",state["run_id"],legacy,repo=r)
 assert workflow.status("docs/tasks/a",repo=r)["status"] == "running"

@pytest.mark.parametrize("status",["blocked","needs_design_revision"])
def test_noncomplete_legacy_reports_normalize_without_models(tmp_path,monkeypatch,status):
 r,t=env(tmp_path);mock(monkeypatch);state=workflow.run("docs/tasks/a",repo=r)
 workflow.claim("docs/tasks/a",state["run_id"],repo=r)
 legacy={"status":status,"summary":"reason","implementation_model":"","review_model":""}
 saved=workflow.finish("docs/tasks/a",state["run_id"],legacy,repo=r)
 assert saved["status"] == status
 assert all(saved[key] == "" for key in ("implementation_model","scoped_review_model","scoped_review_effort","review_model","review_effort"))
 assert not (r/".workflow-active.json").exists()

def test_main_finish_wires_all_review_fields(monkeypatch):
 calls=[]
 monkeypatch.setattr(workflow,"finish",lambda *args,**kwargs: calls.append((args,kwargs)) or {"status":"blocked"})
 assert workflow.main(["finish","--task","docs/tasks/a","--run-id","id","--status","blocked","--summary","reason",
  "--implementation-model","terra","--scoped-review-model","sol","--scoped-review-effort","high",
  "--review-model","astra","--review-effort","low"]) == 0
 result=calls[0][0][2]
 assert result == {"status":"blocked","summary":"reason","implementation_model":"terra",
  "scoped_review_model":"sol","scoped_review_effort":"high","review_model":"astra","review_effort":"low"}
