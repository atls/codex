import json
from pathlib import Path
import sqlite3
import sys


FIELDS = {
    "service": "service.name",
    "model": "model",
    "threadId": "thread.id",
    "turnId": "turn.id",
    "samplingTurnId": "turn_id",
    "effort": "codex.turn.reasoning_effort",
    "requestEffort": "codex.request.reasoning_effort",
}


def read_spans(database, evaluation_id):
    if not Path(database).exists():
        return []
    expressions = ["json_extract(s.attributes, ?)" for _ in FIELDS]
    query = (
        "select s.trace_id,s.span_id,s.parent_span_id,s.name,s.start_time,s.end_time,s.status_code,"
        + ",".join(expressions)
        + " from spans s join traces t on t.trace_id=s.trace_id where t.evaluation_id=?"
    )
    selectors = ["$." + json.dumps(key) for key in FIELDS.values()]
    with sqlite3.connect(
        Path(database).resolve().as_uri() + "?mode=ro", uri=True
    ) as connection:
        rows = connection.execute(query, (*selectors, evaluation_id)).fetchall()
    names = [
        "traceId",
        "spanId",
        "parentSpanId",
        "name",
        "start",
        "end",
        "statusCode",
        *FIELDS,
    ]
    return [dict(zip(names, row)) for row in rows]


def project(spans, thread_id, turn_id, model, effort):
    native = [span for span in spans if span["service"] == "codex-app-server"]
    by_id = {(span["traceId"], span["spanId"]): span for span in native}
    roots = [
        span
        for span in native
        if span["name"] == "session_task.turn"
        and span["threadId"] == thread_id
        and span["turnId"] == turn_id
    ]
    root_ids = {(span["traceId"], span["spanId"]) for span in roots}

    def under(span, ancestors):
        current = span
        seen = set()
        while current:
            key = (current["traceId"], current["spanId"])
            if key in ancestors:
                return True
            if key in seen:
                break
            seen.add(key)
            current = by_id.get((current["traceId"], current["parentSpanId"]))
        return False

    sampling = [
        span
        for span in native
        if span["name"] == "run_sampling_request"
        and span["samplingTurnId"] == turn_id
        and under(span, root_ids)
    ]
    sampling_ids = {(span["traceId"], span["spanId"]) for span in sampling}
    scoped = [span for span in native if under(span, sampling_ids)]
    transport = [
        span
        for span in scoped
        if span["name"]
        in {
            "model_client.stream_responses_websocket",
            "responses_websocket.stream_request",
            "model_client.stream_responses",
            "model_client.stream_responses_http",
            "responses.stream_request",
        }
    ]

    def successful_path(span):
        current = span
        seen = set()
        while current:
            key = (current["traceId"], current["spanId"])
            if key in seen or current["statusCode"] == 2:
                return False
            if key in sampling_ids:
                return True
            seen.add(key)
            current = by_id.get((current["traceId"], current["parentSpanId"]))
        return False

    network = [
        span
        for span in transport
        if span["name"]
        in {"responses_websocket.stream_request", "responses.stream_request"}
    ]
    successful_transport = [
        span for span in network or transport if successful_path(span)
    ]
    transient_errors = [span for span in scoped if span["statusCode"] == 2]
    models = sorted(
        {span["model"] for span in [*roots, *scoped] if isinstance(span["model"], str)}
    )
    efforts = sorted(
        {
            value
            for span in [*roots, *scoped]
            for value in [span["effort"], span["requestEffort"]]
            if isinstance(value, str)
        }
    )
    mismatch = any(value != model for value in models) or any(
        value != effort for value in efforts
    )
    status = (
        "mismatch"
        if mismatch
        else "confirmed"
        if sampling
        and successful_transport
        and models == [model]
        and efforts == [effort]
        else "unknown"
    )
    retained = [
        span
        for span in [*roots, *scoped]
        if span["name"]
        in {
            "session_task.turn",
            "run_sampling_request",
            "try_run_sampling_request",
            "stream_request",
            "handle_responses",
            "model_client.stream_responses_websocket",
            "responses_websocket.stream_request",
            "model_client.stream_responses",
            "model_client.stream_responses_http",
            "responses.stream_request",
        }
    ]
    return {
        "status": status,
        "threadId": thread_id,
        "turnId": turn_id,
        "samplingModels": models,
        "efforts": efforts,
        "samplingCount": len(sampling),
        "transportCount": len(transport),
        "successfulTransportCount": len(successful_transport),
        "transientErrorCount": len(transient_errors),
        "executionModel": models[0] if status == "confirmed" else None,
        "spans": retained,
        "statusSemantics": "0 means OTLP UNSET, not an HTTP response code; native terminal turn evidence is separate",
    }


def collect(request):
    try:
        spans = read_spans(request["database"], request["evaluationId"])
        return project(
            spans,
            request["threadId"],
            request["turnId"],
            request["model"],
            request["effort"],
        )
    except (sqlite3.Error, OSError) as error:
        return {
            "status": "unknown",
            "reason": type(error).__name__,
            "executionModel": None,
            "spans": [],
        }


if __name__ == "__main__":
    print(json.dumps(collect(json.load(sys.stdin))))
