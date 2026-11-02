"""R1a bounded simulation solver. No recovery, timing scheduler or motor I/O."""
from dataclasses import dataclass
import numpy as np
from .model import finite_array
from .linear import step


@dataclass
class Result:
    status: str
    q_solution: object
    q_last: object
    iterations: int
    position_error_m: object
    tilt_error_rad: object
    history: list


def solve(model, position, axis, q0, config, mode="wls", backend=None):
    if hasattr(backend, 'solve_target'):
        return backend.solve_target(model,position,axis,q0,config,mode=mode)
    history = []
    q = None
    pos_error = tilt = None
    cost = None
    def finish(status, iterations):
        last = None if q is None else q.tolist()
        if cost is not None and np.isfinite(cost) and (not history or history[-1]["iteration"] != iterations):
            history.append({"iteration": iterations, "q": last, "cost": cost,
                            "position_m": pos_error, "tilt_rad": tilt})
        return Result(status, last if status == "OK" else None, last, iterations, pos_error, tilt, history)
    try:
        q = finite_array(q0, (5,), "q0").copy()
        if not model.legal(q):
            return finish("INVALID_INPUT", 0)
        w = finite_array(config["weights"], (6,), "W")
        s = finite_array(config["scales"], (6,), "S")
        mu = float(config["mu"])
        limit = config["max_iterations"]
        trials = config["line_search_trials"]
        window = config["stagnation_window"]
        max_step = float(config["max_joint_step_rad"])
        cost_change = float(config["stagnation_cost_change"])
        pos_tol, tilt_tol = float(config["position_tolerance_m"]), float(config["tilt_tolerance_rad"])
        if (any(type(v) is not int or v < 1 for v in (limit, trials, window)) or limit > 10000
                or trials > 32 or max_step <= 0 or pos_tol <= 0 or tilt_tol <= 0
                or not np.isfinite([max_step, pos_tol, tilt_tol, mu, cost_change]).all()
                or np.any(w < 0) or np.any(s <= 0) or mu <= 0 or cost_change < 0
                or mode not in ("wls", "rhs_only")):
            return finish("INVALID_INPUT", 0)
        if (backend is not None and hasattr(backend, "validate_model")
                and not backend.validate_model(model)):
            return finish("INVALID_INPUT", 0)
        full_task = backend is not None and hasattr(backend, "solve_task")
        position = finite_array(position, (3,), "position")
        axis = finite_array(axis, (3,), "axis")
        if not np.isclose(np.linalg.norm(axis), 1, atol=1e-8, rtol=0):
            return finish("INVALID_INPUT", 0)
        def evaluate(candidate):
            if not full_task:
                evaluate_task = getattr(model, 'task_lazy', model.task)
                return evaluate_task(candidate, position, axis)
            # PL computes J; PS independently checks FK/error without rebuilding J.
            pose = model.pose(candidate)
            current_axis = pose[:3,:3] @ model.tool_axis
            error = np.r_[position-pose[:3,3], axis-current_axis]
            pe, te = model.pose_errors(pose, position, axis)
            return error, None, pe, te
        error, j, pos_error, tilt = evaluate(q)
    except (ValueError, TypeError, KeyError, OverflowError):
        return finish("INVALID_INPUT", 0)
    pending_stall = None
    for iteration in range(limit + 1):
        with np.errstate(over="ignore", invalid="ignore"):
            cost = float(0.5 * np.dot(w, (s * error) ** 2))
        if not np.isfinite(cost):
            return finish("NUMERIC", iteration)
        history.append({"iteration": iteration, "q": q.tolist(), "cost": cost,
                        "position_m": pos_error, "tilt_rad": tilt})
        # Physical task gates are independent of W (even zero axis weights).
        if pos_error <= pos_tol and tilt <= tilt_tol:
            return finish("OK", iteration)
        if pending_stall is not None:
            return finish(pending_stall, iteration)
        if iteration == limit:
            return finish("MAX_ITER", iteration)
        try:
            if backend is not None and hasattr(backend, "solve_task"):
                # Full PL task-step ABI: FK, task Jacobian and WLS are computed
                # together. The host still validates the candidate with the
                # existing line search below.
                task_step = backend.solve_task(position, axis, q, w, s, mu,
                                                max_step=max_step, mode=mode)
                dq_value = task_step["dq"] if isinstance(task_step, dict) else task_step
            else:
                if callable(j):
                    j = j()
                dq_value = (backend or step)(j, error, w, s, mu, mode)
            dq = finite_array(dq_value, (5,), "dq").copy()
        except (ValueError, FloatingPointError, np.linalg.LinAlgError):
            return finish("NUMERIC", iteration)
        dq *= min(1.0, max_step / max(np.max(np.abs(dq)), 1e-30))
        accepted = False
        touched_limit = False
        for trial in range(trials):
            proposed = q + dq * 0.5 ** trial
            candidate = np.clip(proposed, model.limits[:, 0], model.limits[:, 1])
            touched_limit |= not np.array_equal(candidate, proposed)
            try:
                next_error, next_j, next_pos, next_tilt = evaluate(candidate)
                with np.errstate(over="raise", invalid="raise"):
                    next_cost = float(0.5 * np.dot(w, (s * next_error) ** 2))
            except (ValueError, FloatingPointError, OverflowError):
                return finish("NUMERIC", iteration + 1)
            if np.isfinite(next_cost) and next_cost < cost:
                q, error, j, pos_error, tilt = candidate, next_error, next_j, next_pos, next_tilt
                accepted = True
                break
        if not accepted:
            return finish("LIMIT_STALL" if touched_limit else "STAGNATION", iteration + 1)
        if len(history) >= window and abs(history[-window]["cost"] - next_cost) < cost_change:
            # Inspect/record the accepted candidate at the next loop head.
            # A physical success takes precedence over this pending stop.
            at_limit = bool(np.any(np.isclose(q[:, None], model.limits, atol=1e-12, rtol=0)))
            pending_stall = "LIMIT_STALL" if at_limit else "STAGNATION"
    raise AssertionError("bounded loop fell through")
