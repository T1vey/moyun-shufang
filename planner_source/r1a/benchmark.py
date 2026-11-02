"""Deterministic host milestone: frozen vectors, paired bounded IK, raw evidence."""
import argparse
from collections import Counter
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import platform
import time
import numpy as np
from .model import Model
from .linear import step, system, independent_wls
from .solve import solve

ROOT = Path(__file__).resolve().parents[1]


def write_json(path, data):
    Path(path).write_text(json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def f32(value):
    return np.asarray(value, dtype=np.float32).astype(np.float64)


def make_vectors(model, cfg, out):
    rng = np.random.default_rng(2026092401)
    records = []
    max_py_error = 0.
    max_condition = 0.
    differences = []
    for index in range(256):
        family = index % 8
        j = rng.normal(0, .3, (6, 5))
        scales = np.ones(6)
        if family == 0:
            j = np.zeros((6, 5))
        elif family in (1, 2):
            # Exact/near rank deficiency, positive regularization remains.
            j[:, 4] = j[:, 3] + (1e-5 if family == 2 else 0) * rng.normal(size=6)
        elif family in (3, 4, 5):
            q = rng.uniform(model.limits[:, 0], model.limits[:, 1]) if family == 3 else np.zeros(5)
            if family == 5: q = model.limits[:, 1] - 1e-5
            t, _ = model.evaluate(q)
            j = model.task(q, t[:3, 3], t[:3, :3] @ model.tool_axis)[1]
            scales[:3] = 10.
        elif family == 6:
            j[4:] = 0
        elif family == 7:
            scales = np.array([.5, 2, 1, 3, .5, 1])
        weight_cases = (np.ones(6), np.array([1, .25, 4, .5, 2, 1]), np.array([1, 1, 1, 0, 0, 0]), np.zeros(6))
        w = weight_cases[(index // 8) % 4]
        mu = (1e-4, 1e-3, 1e-2, .1)[(index // 32) % 4]
        j, e, w, scales, mu = f32(j), f32(rng.normal(0, .03, 6)), f32(w), f32(scales), float(f32(mu))
        paired = []
        for mode in (0, 1):
            label = "wls" if mode == 0 else "rhs_only"
            a, b = system(j, e, w, scales, mu, label)
            reference = independent_wls(j, e, w, scales, mu) if mode == 0 else np.linalg.solve(a, b)
            python_result = step(j, e, w, scales, mu, label)
            error = float(np.max(np.abs(python_result-reference)))
            if error > 1e-8 + 1e-8 * np.max(np.abs(reference)):
                raise AssertionError(f"Python oracle mismatch {index}/{mode}: {error}")
            max_py_error = max(max_py_error, error)
            condition = float(np.linalg.cond(a))
            max_condition = max(max_condition, condition)
            records.append(dict(id=f"v{index:03d}_m{mode}", family=family, mode=mode, expected=0,
                                j=j.tolist(), e=e.tolist(), w=w.tolist(), scales=scales.tolist(), mu=mu,
                                reference=reference.tolist(), condition=condition))
            paired.append(reference)
        differences.append(float(np.linalg.norm(paired[0]-paired[1])))
    base = records[0]  # J=0, nonzero W/e, success after each injected failure.
    faults = []
    mutations = [
        ("nan_j", "j", [0, 0], "nan", 1), ("inf_e", "e", [0], "inf", 1),
        ("negative_w", "w", [0], -1, 1), ("nan_w", "w", [0], "nan", 1),
        ("zero_s", "scales", [0], 0, 1), ("inf_s", "scales", [0], "inf", 1),
        ("zero_mu", "mu", [], 0, 1), ("negative_mu", "mu", [], -1, 1),
        ("nan_mu", "mu", [], "nan", 1), ("bad_mode", "mode", [], 7, 1),
        ("overflow_equation", "j", [0, 0], 3e38, 2),
    ]
    for label, field, indices, value, expected in mutations:
        rec = json.loads(json.dumps(base))
        rec.update(id=label, expected=expected, reference=[0]*5, condition=None, family="fault")
        if indices:
            container = rec[field]
            for sub in indices[:-1]: container = container[sub]
            container[indices[-1]] = value
        else:
            rec[field] = value
        faults.append(rec)
        recovery = json.loads(json.dumps(records[20]))  # Nontrivial successful call.
        recovery["id"] = f"after_{label}"
        faults.append(recovery)
    records.extend(faults)
    write_json(out / "vectors.json", dict(seed=2026092401, contract_id=cfg["id"], count=len(records),
        note="Inputs quantized to float32 before float64 oracle; nan/inf are explicit string tokens.", records=records))
    with (out / "vectors.txt").open("w", encoding="ascii", newline="\n") as file:
        file.write(str(len(records)) + "\n")
        for r in records:
            file.write(f"{r['id']} {r['mode']} {r['expected']}\n")
            values = [v for row in r["j"] for v in row] + r["e"] + r["w"] + r["scales"] + [r["mu"]] + r["reference"]
            values += [cfg["native_dq_abs_tolerance"], cfg["native_dq_rel_tolerance"], cfg["native_backward_error_tolerance"]]
            file.write(" ".join(v if isinstance(v, str) else format(v, ".17g") for v in values) + "\n")
    return dict(cases=len(records), valid_cases=512+len(faults)//2, fault_cases=len(faults)//2,
                max_python_dq_error=max_py_error, max_normal_matrix_condition=max_condition,
                paired_formula_differences_over_1e_8=sum(d>1e-8 for d in differences),
                max_paired_formula_l2_difference=max(differences))


def make_targets(model):
    rng_target = np.random.default_rng(2026092402)
    rng_initial = np.random.default_rng(2026092403)
    records = []
    for index in range(288):
        q0 = rng_initial.uniform(model.limits[:, 0] * .8, model.limits[:, 1] * .8)
        if index < 256:
            family = "fk_random" if index < 192 else "fk_limit_neighborhood"
            generator_q = rng_target.uniform(model.limits[:, 0], model.limits[:, 1])
            if index >= 192:
                joint = index % 5
                generator_q[joint] = model.limits[joint, index % 2] + (1e-5 if index % 2 == 0 else -1e-5)
            t, _ = model.evaluate(generator_q)
            p, axis = t[:3, 3], t[:3, :3] @ model.tool_axis
        else:
            family = "independent_cartesian_unknown_feasibility"
            p = rng_target.uniform([-.2, -.2, .03], [.4, .2, .4])
            axis = rng_target.normal(size=3); axis /= np.linalg.norm(axis)
        weights = ([1]*6, [1, 1, 1, .25, .25, .25], [1, 1, 1, 0, 0, 0])[index % 3]
        # q used to generate FK targets is NOT passed to solve or exposed as q0.
        records.append(dict(id=f"t{index:03d}", family=family, position=p.tolist(), axis=axis.tolist(),
                            q0=q0.tolist(), weights=weights))
    return records


def run_paired(model, cfg, out):
    targets = make_targets(model)
    write_json(out / "targets.json", dict(target_seed=2026092402, initial_seed=2026092403,
        note="Independent RNGs; known FK targets + unproven Cartesian targets; no recovery.", targets=targets))
    counts = {mode: Counter() for mode in ("wls", "rhs_only")}
    timing = {mode: [] for mode in counts}
    success_timing = {mode: [] for mode in counts}
    family_counts = {}
    successes = {}
    with (out / "ik_results.jsonl").open("w", encoding="utf-8") as file:
        for target in targets:
            per_target = {}
            config = dict(cfg, weights=target["weights"])
            for mode in counts:
                start = time.perf_counter_ns()
                result = solve(model, target["position"], target["axis"], target["q0"], config, mode)
                ms = (time.perf_counter_ns() - start)/1e6
                counts[mode][result.status] += 1
                family_key = f"{target['family']}/{target['weights'][3]}/{mode}"
                family_counts.setdefault(family_key, Counter())[result.status] += 1
                timing[mode].append(ms)
                if any(not model.legal(item["q"]) for item in result.history):
                    raise AssertionError("out-of-limit iterate")
                if result.iterations > config["max_iterations"]:
                    raise AssertionError("iteration budget exceeded")
                if result.status == "OK":
                    if result.q_solution is None or not model.legal(result.q_solution):
                        raise AssertionError("invalid accepted q")
                    _, _, pos, tilt = model.task(result.q_solution, target["position"], target["axis"])
                    if pos > cfg["position_tolerance_m"] or tilt > cfg["tilt_tolerance_rad"]:
                        raise AssertionError("physical task gate bypass")
                    success_timing[mode].append(ms)
                elif result.q_solution is not None:
                    raise AssertionError("failed result marked valid")
                per_target[mode] = dict(elapsed_ms=ms, **asdict(result))
            successes[target["id"]] = [per_target[m]["status"] == "OK" for m in counts]
            file.write(json.dumps(dict(id=target["id"], results=per_target), allow_nan=False) + "\n")
    def percentiles(values):
        return None if not values else dict(zip(("p50", "p95", "p99"), np.percentile(values, [50, 95, 99]).tolist()))
    transitions = Counter(f"wls_{a}_rhs_{b}" for a,b in successes.values())
    return dict(target_count=len(targets), calls=len(targets)*2, status=counts,
        family_weight_status=family_counts, paired_success=transitions,
        host_elapsed_ms={m: dict(all_requests=percentiles(timing[m]), successful_requests=percentiles(success_timing[m])) for m in counts},
        scope="x86 Python simulation only; no R1b recovery; no full R0 wrapper; no FPGA or A9 speedup claim")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    parser.add_argument("--review-vectors")
    args = parser.parse_args()
    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)
    if (out / "python_summary.json").exists():
        raise SystemExit("refusing to overwrite an existing completed run")
    cfg = json.loads((ROOT / "config/contract.json").read_text())
    model = Model.load(ROOT / "config/nominal_so101.json")
    vectors = make_vectors(model, cfg, out)
    print("PYTHON_VECTOR_ORACLE_PASS " + json.dumps(vectors), flush=True)
    paired = run_paired(model, cfg, out)
    # Freeze actual paired J/e from this solver, not independent Gaussian e.
    base_records=json.loads((out/'vectors.json').read_text())["records"]
    targets={t['id']:t for t in json.loads((out/'targets.json').read_text())['targets']}
    actual=[]
    for row in map(json.loads,(out/'ik_results.jsonl').read_text().splitlines()):
        target=targets[row['id']]
        for label,mode in (("wls",0),("rhs_only",1)):
            r=row['results'][label]; history=r['history']
            if history[-1]['q']!=r['q_last'] or history[-1]['iteration']!=r['iterations']:
                raise AssertionError('terminal history mismatch')
            for i in sorted(set((0,len(history)//2,len(history)-1))):
                e,j,_,_=model.task(history[i]['q'],target['position'],target['axis'])
                j,e,w,s,mu=f32(j),f32(e),f32(target['weights']),f32(cfg['scales']),float(f32(cfg['mu']))
                a,b=system(j,e,w,s,mu,label)
                reference=independent_wls(j,e,w,s,mu) if mode==0 else np.linalg.solve(a,b)
                actual.append(dict(id=f"actual_{row['id']}_{mode}_{i}",mode=mode,expected=0,
                    j=j.tolist(),e=e.tolist(),w=w.tolist(),scales=s.tolist(),mu=mu,reference=reference.tolist()))
    base_records.extend(actual)
    write_json(out/'vectors.json',dict(contract_id=cfg['id'],records=base_records,count=len(base_records)))
    with (out/'vectors.txt').open('w',encoding='ascii',newline='\n') as f:
        old_lines=[]; old_count=0
        if args.review_vectors:
            old_lines=Path(args.review_vectors).read_text().splitlines()
            old_count=int(old_lines.pop(0))
            if len(old_lines)!=old_count*2: raise ValueError('malformed frozen review vectors')
        f.write(str(len(base_records)+old_count)+'\n')
        for r in base_records:
            f.write(f"{r['id']} {r['mode']} {r['expected']}\n")
            values=[v for row in r['j'] for v in row]+r['e']+r['w']+r['scales']+[r['mu']]+r['reference']
            values += [cfg['native_dq_abs_tolerance'],cfg['native_dq_rel_tolerance'],cfg['native_backward_error_tolerance']]
            f.write(' '.join(v if isinstance(v,str) else format(v,'.17g') for v in values)+'\n')
        for i,line in enumerate(old_lines):
            f.write(('review_'+line if i%2==0 else line)+'\n')
    vectors.update(original_cases=vectors['cases'],actual_iteration_cases=len(actual),review_regression_cases=old_count,
                   cases=len(base_records)+old_count,valid_cases=len(base_records)+old_count-vectors['fault_cases'])
    summary = dict(contract_id=cfg["id"], model_id=model.config["version"],
        python=platform.python_version(), numpy=np.__version__, platform=platform.platform(),
        vectors=vectors, ik=paired, numerical_gate="PASS", full_r0="NOT_REPRODUCED",
        hls="NOT_RUN", hardware="NOT_RUN")
    write_json(out / "python_summary.json", summary)
    print("PAIRED_IK_COMPLETE " + json.dumps({"targets":paired["target_count"], "status":paired["status"], "paired":paired["paired_success"]}), flush=True)


if __name__ == "__main__":
    main()
