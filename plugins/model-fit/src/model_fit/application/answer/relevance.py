from model_fit.application.answer.decoding import decode_verdict
from model_fit.application.answer.prompts.relevance import relevance_prompt
from model_fit.application.answer.types.evaluator import AnswerEvaluator
from model_fit.application.answer.types.result import AnswerVerdict


def classify_answer(
    request: str,
    task_context: str,
    answer: str,
    *,
    evaluator: AnswerEvaluator,
) -> AnswerVerdict:
    prompt = relevance_prompt(request, task_context, answer)
    return decode_verdict(evaluator(prompt))
