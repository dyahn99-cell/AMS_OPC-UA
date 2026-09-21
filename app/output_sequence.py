"""Stop multi-output writes at the first failure; preserve uncertain application."""


def execute_output_sequence(steps):
    results = []
    for step in steps:
        try:
            result = dict(step())
        except Exception as exc:
            result = {"ok": False, "error": str(exc), "applied": True,
                      "recovery_required": True}
        results.append(result)
        if not result.get("ok"):
            # A negative readback can follow a successful physical write.
            return {"ok": False, "partial": any(r.get("ok") for r in results),
                    "applied": True, "recovery_required": True,
                    "error": result.get("error", "output_sequence_failed"), "results": results}
    result = {"ok": True, "applied": bool(results), "results": results}
    if results and all(r.get("verified") is True for r in results):
        result["verified"] = True
    return result
