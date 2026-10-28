"""Protocol evidence, independent of parser heuristics and transport routing."""

SCHEMA = "ocr-completion/1"
TELEMETRY = (
    "prompt_eval_count",
    "eval_count",
    "prompt_eval_duration",
    "eval_duration",
    "total_duration",
    "load_duration",
)


def completion_metadata(data, family):
    """Return bounded metadata only; never reflect arbitrary API strings or content."""
    from localocr.ollama import OCRServerError

    if not isinstance(data, dict):
        raise OCRServerError("MALFORMED_API_RESPONSE")
    done = None
    if family == "chat":
        try:
            choice = data["choices"][0]
            text = choice["message"]["content"]
            reason = choice.get("finish_reason")
        except (KeyError, IndexError, TypeError, AttributeError) as error:
            raise OCRServerError("MALFORMED_API_RESPONSE") from error
    else:
        text, reason, done = data.get("response"), data.get("done_reason"), data.get("done")
    if not isinstance(text, str):
        raise OCRServerError("MALFORMED_API_RESPONSE")
    state = (
        "GENERATION_LIMIT_CONFIRMED"
        if reason == "length"
        else "NORMAL_STOP"
        if reason == "stop" and (family == "chat" or done is True)
        else "FINISH_UNKNOWN"
    )
    incomplete = family != "chat" and "done" in data and done is not True
    return {
        "schema": SCHEMA,
        "endpoint_family": family,
        "finish_state": state,
        "api_reason": reason
        if isinstance(reason, str) and reason in {"length", "stop"}
        else None
        if reason is None
        else "OTHER",
        "done": done if type(done) is bool else None,
        "transport_incomplete": incomplete,
        "telemetry": {k: data[k] for k in TELEMETRY if type(data.get(k)) in {int, float}},
    }
