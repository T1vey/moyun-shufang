"""Reproducible run binding, not a signature against a malicious file owner.

Freeze before execution; each stage receipt binds the original inputs, previous
receipt, argv, exit status, log and outputs. Reports verify; never re-seal inputs.
"""
import hashlib
import json
from pathlib import Path
import uuid


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def write_new(path, obj):
    with Path(path).open("x",encoding="utf-8") as f:
        f.write(json.dumps(obj,ensure_ascii=False,indent=2,allow_nan=False)+"\n")


def safe_path(root, name):
    root=Path(root).resolve()
    path=(root/name).resolve()
    if not path.is_relative_to(root) or path==root:
        raise ValueError(f"path escapes run: {name}")
    return path


def source_files(run):
    return sorted(p.relative_to(run).as_posix() for prefix in ("source","reference","entrypoints")
                  for p in (run/prefix).rglob("*") if p.is_file() and "__pycache__" not in p.parts)


def freeze(run):
    run=Path(run).resolve()
    files=source_files(run)
    if not files or not (run/"source/config/contract.json").is_file():
        raise ValueError("source inputs missing")
    write_new(run/"inputs.json",dict(schema=2,run_id=str(uuid.uuid4()),run_root=str(run),
        files={p:sha(run/p) for p in files}))


def verify_inputs(run):
    run=Path(run).resolve(); data=read(run/"inputs.json")
    if data.get("schema")!=2 or data.get("run_root")!=str(run):
        raise ValueError("run identity/path mismatch")
    if set(source_files(run))!=set(data["files"]):
        raise ValueError("source set changed")
    for name,digest in data["files"].items():
        if sha(safe_path(run,name))!=digest: raise ValueError(f"input changed: {name}")
    return data


def receipts(run):
    return sorted((Path(run)/"receipts").glob("*.json"))


def verify(run, expected=None):
    run=Path(run).resolve(); original=verify_inputs(run)
    previous=sha(run/"inputs.json"); names=[]
    for index,path in enumerate(receipts(run)):
        data=read(path)
        if data["index"]!=index or data["run_id"]!=original["run_id"] or data["inputs_sha256"]!=sha(run/"inputs.json"):
            raise ValueError("receipt identity mismatch")
        if data["previous_sha256"]!=previous or data["exit_code"]!=0:
            raise ValueError("broken or failed receipt chain")
        if not data["outputs"] or not data["argv"]: raise ValueError("incomplete receipt")
        for name,digest in data["outputs"].items():
            if sha(safe_path(run,name))!=digest: raise ValueError(f"evidence changed: {name}")
        names.append(data["stage"]); previous=sha(path)
    if expected is not None and names!=list(expected):
        raise ValueError(f"stage sequence mismatch: {names}")
    return dict(run_id=original["run_id"],inputs_sha256=sha(run/"inputs.json"),last_receipt_sha256=previous,stages=names)


def record(run, stage, argv, exit_code, outputs):
    run=Path(run).resolve(); binding=verify(run)
    if exit_code!=0: raise ValueError(f"cannot seal failed stage {stage}")
    index=len(receipts(run))
    (run/"receipts").mkdir(exist_ok=True)
    write_new(run/"receipts"/f"{index:02d}_{stage}.json",dict(index=index,stage=stage,
        run_id=binding["run_id"],inputs_sha256=binding["inputs_sha256"],
        previous_sha256=binding["last_receipt_sha256"],argv=list(argv),exit_code=exit_code,
        outputs={p:sha(safe_path(run,p)) for p in outputs}))
