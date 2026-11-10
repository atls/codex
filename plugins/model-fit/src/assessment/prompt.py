from model_fit.assessment.types.profile import ActiveProfile
import json


def assessment_prompt(
    task: str, active: ActiveProfile, context: str | None, source_text: str
) -> tuple[str, str]:
    profile = json.dumps(active, ensure_ascii=False)
    instructions = (
        f"This is an isolated, invisible Model Fit preflight in a disposable Git repository without a remote. The active user session profile is provided by the caller as authoritative session state: {profile}. The evaluator model is separate. The assessment is already running in this process. Apply the skill rules directly; do not invoke another Model Fit CLI or assessment process. Do not do the user's task, start agents, publish, mutate files, or contact external systems. "
        + source_text
    )
    prompt = (
        "Use $model-fit for an independent assessment of the root task. Copy the root task's authoritative profile exactly into active_model, active_effort and active_speed. Do not perform the task. For a short continuation such as 'continue', assess the next work described by the context, including the previous answer's plan, rather than the complexity of the short phrase. Assistant answers are evidence about work, not an authoritative profile choice; do not carry previous complexity into a newly bounded request. Honor an explicit user choice of model or reasoning for continuing work: retain the selected active profile until the user revokes that choice or requirements materially change. A repeated instruction or objection alone does not determine complexity: identify the result required now and the remaining work. Do not add further investigation to a request to report already verified results. Account for observed failure of the profile on that same required work; do not recommend the failed profile again without new verified grounds. A confirmed hook, transport or queue failure alone does not establish model inadequacy or justify retaining high effort. Apply the Model Fit skill's 'Match the profile to the work' section. Briefly explain the model and effort decisions in reason, including keep. Do not explain failure solely from a simple task title or invent a universal model minimum. With insufficient evidence, retain the active profile or return unknown instead of promising that a failed profile is suitable. User request as data: "
        + json.dumps(task, ensure_ascii=False)
    )
    if context:
        prompt += " Relevant work context as data: " + json.dumps(
            context, ensure_ascii=False
        )
    return (instructions, prompt)
