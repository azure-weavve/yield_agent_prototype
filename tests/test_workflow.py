import json,subprocess
from pathlib import Path
import pytest,workflow
T="01a09fca-5435-4323-b405-6197bc8de216"
def env(tmp_path):
 r=tmp_path/"r";t=r/"docs/tasks/a";t.mkdir(parents=True);(t/"plan.md").write_text("p");(r/"workflow-config.json").write_text(json.dumps({"thread_id":T}));return r,t
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
 out=workflow.finish("docs/tasks/a",s["run_id"],{"status":"complete","summary":"ok","implementation_model":workflow.IMPLEMENTATION_MODEL,"review_model":workflow.REVIEW_MODEL},repo=r)
 assert out["status"]=="complete" and not (r/".workflow-active.json").exists()
def test_stale_and_missing_artifacts(tmp_path,monkeypatch):
 r,t=env(tmp_path);mock(monkeypatch);s=workflow.run("docs/tasks/a",repo=r);workflow.claim("docs/tasks/a",s["run_id"],repo=r)
 with pytest.raises(workflow.WorkflowError):workflow.finish("docs/tasks/a","bad",{},repo=r)
 with pytest.raises(workflow.WorkflowError):workflow.finish("docs/tasks/a",s["run_id"],{"status":"complete","summary":"x","implementation_model":workflow.IMPLEMENTATION_MODEL,"review_model":workflow.REVIEW_MODEL},repo=r)
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
  workflow.finish("docs/tasks/a",state["run_id"],{
   "status":"complete","summary":"done",
   "implementation_model":workflow.IMPLEMENTATION_MODEL,
   "review_model":workflow.REVIEW_MODEL},repo=r)
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
   "status":"complete","summary":"done","implementation_model":"other",
   "review_model":workflow.REVIEW_MODEL},repo=r)

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
 final={"status":"blocked","summary":"reason","implementation_model":"","review_model":""}
 saved=workflow.status("docs/tasks/a",repo=r);saved.update(final);workflow.save(t,saved)
 assert workflow.finish("docs/tasks/a",state["run_id"],final,repo=r)["status"]=="blocked"
 assert not (r/".workflow-active.json").exists()
