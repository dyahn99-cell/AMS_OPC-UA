"""Schedule instances: definition enablement never owns restoration responsibility."""
from copy import deepcopy
from datetime import datetime, timedelta
import uuid

LIVE = {"STARTING", "RUNNING", "PARTIAL", "RESTORING", "RECOVERY_REQUIRED"}


def window(definition, now):
    start = datetime.strptime(definition["start_time"], "%H:%M").time()
    end = datetime.strptime(definition["end_time"], "%H:%M").time()
    began = datetime.combine(now.date(), start, tzinfo=now.tzinfo)
    ended = datetime.combine(now.date(), end, tzinfo=now.tzinfo)
    if ended <= began:
        ended += timedelta(days=1)
        if now < began:
            began -= timedelta(days=1)
            ended -= timedelta(days=1)
    return began, ended


def summarize(results):
    good = [r for r in results.values() if r.get("ok") and not r.get("skipped")]
    partial = bool(good) and len(good) != len(results)
    outcome = ("partial" if partial else "verified" if good and all(r.get("verified") is True for r in good)
               and len(good) == len(results) else "applied" if good and len(good) == len(results) else "failed")
    return {"ok": bool(good) and len(good) == len(results), "partial": partial,
            "outcome": outcome, "results": results}


def response(run, result):
    return {**result, "result": deepcopy(result), "run": deepcopy(run),
            "target": run.get("target"), "mode": run.get("mode"),
            "recovery_required": run.get("state") == "RECOVERY_REQUIRED"}


class ScheduleExecution:
    def __init__(self):
        self.runs = {}
        self.epochs = {}

    def load(self, definitions):
        self.runs = {}
        self.epochs = {}
        for definition in definitions:
            run = definition.get("run")
            if isinstance(run, dict):
                run = deepcopy(run)
                if run.get("state") in LIVE:
                    run["state"] = "RECOVERY_REQUIRED"
                    run["recovery_required"] = True
                self.runs[definition["id"]] = run
            elif str(definition.get("status", "")).upper() == "RUNNING" or definition.get("return_mode") is not None:
                self.runs[definition["id"]] = {"run_id": str(uuid.uuid4()), "state": "RECOVERY_REQUIRED",
                    "targets": [], "recovery_required": True, "error": "legacy_run_ownership_unknown"}

    def live(self, schedule_id):
        return self.runs.get(schedule_id, {}).get("state") in LIVE

    def publish(self, definitions):
        for definition in definitions:
            if definition["id"] in self.runs:
                definition["run"] = deepcopy(self.runs[definition["id"]])

    def start(self, definition, now, targets, apply, persist):
        old = self.runs.get(definition["id"])
        if old and old.get("state") in LIVE:
            return response(old, {"ok": False, "partial": old["state"] == "PARTIAL", "outcome": "failed",
                                  "error": "schedule_already_running", "idempotent": True})
        targets = list(targets)
        conflicts = sorted({entry["device_id"] for other in self.runs.values()
                            if other.get("state") in LIVE
                            for entry in other.get("targets", [])
                            if entry["device_id"] in targets})
        if conflicts:
            return {"ok": False, "outcome": "conflict", "error": "schedule_target_already_owned",
                    "conflicting_devices": conflicts}
        _, deadline = window(definition, now)
        if deadline <= now:
            deadline += timedelta(days=1)
        run = {"run_id": str(uuid.uuid4()), "schedule_id": definition["id"], "state": "STARTING",
               "target": definition["remote_id"], "mode": definition["mode"], "started_at": now.isoformat(),
               "ends_at": deadline.isoformat(), "targets": [], "recovery_required": False}
        self.runs[definition["id"]] = run
        # The concrete list is fixed before the first output write.
        run["targets"] = [{"device_id": target, "state": "PENDING", "owned": False} for target in targets]
        persist()
        results = {}
        for target in run["targets"]:
            try:
                result = apply(run, target, persist)
            except Exception as exc:
                result = {"ok": False, "error": str(exc)}
                if target.get("state") == "APPLYING":
                    target["state"] = "RECOVERY_REQUIRED"
            target["result"] = result
            results[target["device_id"]] = result
            persist()
            if run.get("recovery_required"):
                raise RuntimeError("schedule_journal_persistence_failed")
        result = summarize(results)
        run["state"] = ("RECOVERY_REQUIRED" if any(t["state"] == "RECOVERY_REQUIRED" for t in run["targets"])
                        else "PARTIAL" if result["partial"] else "RUNNING" if result["ok"] else "FAILED")
        run["recovery_required"] = run["state"] == "RECOVERY_REQUIRED"
        run["last_result"] = result
        persist()
        return response(run, result)

    def stop(self, schedule_id, restore, persist):
        run = self.runs.get(schedule_id)
        if not run:
            return {"ok": False, "outcome": "failed", "error": "schedule_not_running"}
        if run["state"] == "RECOVERY_REQUIRED":
            return response(run, {"ok": False, "outcome": "failed", "error": "schedule_recovery_required"})
        if run["state"] not in LIVE:
            return response(run, {"ok": False, "outcome": "failed", "error": "schedule_not_running", "idempotent": True})
        run["state"] = "RESTORING"
        persist()
        results = {}
        for target in run["targets"]:
            if not target.get("owned"):
                continue
            try:
                result = restore(run, target)
            except Exception as exc:
                result = {"ok": False, "error": str(exc), "recovery_required": True}
            target["restore_result"] = result
            if result.get("ok") or result.get("superseded"):
                target["owned"] = False
                target["state"] = "SUPERSEDED" if result.get("superseded") else "RESTORED"
            else:
                target["state"] = "RECOVERY_REQUIRED"
            results[target["device_id"]] = result
            persist()
        result = summarize(results)
        run["state"] = "RECOVERY_REQUIRED" if any(t.get("owned") for t in run["targets"]) else "COMPLETED"
        run["recovery_required"] = run["state"] == "RECOVERY_REQUIRED"
        run["last_restore_result"] = result
        persist()
        return response(run, result)
