from pydantic import TypeAdapter, ValidationError

from model_fit.application.answer.types.result import AnswerVerdict, RelevanceDecision


RELEVANCE_ADAPTER = TypeAdapter(RelevanceDecision)


def decode_verdict(value: object) -> AnswerVerdict:
    try:
        return RELEVANCE_ADAPTER.validate_python(value, strict=True)["verdict"]
    except ValidationError:
        raise ValueError(
            "Replay answer evaluation returned an invalid verdict"
        ) from None
