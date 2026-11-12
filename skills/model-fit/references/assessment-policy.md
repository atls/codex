# Assessment policy

Before substantial work, match the task requirements to the active profile and available models. For complex root work involving subagents, assess the root before the preamble and lane allocation. A recommendation does not authorize the task; follow the response rule below.

Assess when substantial work starts or its requirements materially change. Continue using an established decision while the work and profile remain the same; a new turn alone does not require rereading guidance and the catalog.

Assess a proposed child lane separately before starting it. This does not change the root profile or require another root recommendation.

## User choice

If the user explicitly retains a profile after a recommendation, honor that choice for the unchanged root task. Do not repeat the same recommendation or turn the retained choice into another admission gate. Reassess only after a material change in complexity, risk, required capabilities or scope.

## Discussion of previous work

Treat ordinary conversation with no new work requested as discussion for profile selection. A greeting, acknowledgement or personal update keeps the active profile. A new request embedded in a conversational message is assessed on the work actually requested.

First distinguish discussion of an existing result from new execution requirements. When the user asks about the previous answer, its reasoning, evidence, mistakes, wording or omitted material, retain the active model and reasoning effort. This includes annotations, corrections to the same deliverable and requests to show parts that were already requested. A brief follow-up does not become an independent lightweight task because it is short or easy to phrase.

During that discussion, an automatic recommendation must not change either profile axis. An explicit user request to reassess or change the model or effort permits profile selection again. A genuinely new task or materially changed execution requirements can also receive a fresh assessment; sharing a conversation does not make every future task a discussion follow-up. If the relationship cannot be established, preserve the current profile and report uncertainty.

## Sources

- Read current official [model-selection guidance](https://developers.openai.com/api/docs/guides/model-selection) and [reasoning guidance](https://developers.openai.com/api/docs/guides/reasoning). Use the [model catalog](https://developers.openai.com/api/docs/models) and the relevant model page for capabilities. Guidance is a starting point, not a mandatory selection
- Official documentation explains purpose and trade-offs; the local Codex catalog establishes available profiles and supported reasoning/speed. Neither source replaces the other
- Obtain the active root model, reasoning and speed only from authoritative session state. Leave missing fields unknown; do not infer them from launch settings
- Do not treat `~/.codex/config.toml` as active task state or read `~/.codex/models_cache.json` directly
- Obtain available profiles with ordinary `codex debug models`. Do not use `--bundled`; let Codex refresh its catalog, including required network access
- Do not substitute rankings, a model API or third-party summaries for official guidance and local availability. Verify version-specific behavior when needed
- Put only this bounded projection in context:

```sh
set -o pipefail
codex debug models | jq '{models: [.models[] | select(.visibility == "list") | {slug, display_name, description, supported_reasoning_levels, service_tiers, additional_speed_tiers, visibility}]}'
```

Do not run the unprojected command, save its raw result or projection, create another catalog/cache/reference/script, or recite the model list to the user. If the command, refresh, projection or required official page is unavailable, do not use raw output, caches, third-party lookup, a model API or `--bundled` as fallback. Check the complete pipeline exit status: successful `jq` must not hide a Codex failure. Do not invent a recommendation.

Briefly identify the unavailable required source and report that assessment is incomplete. An unsuccessful lookup does not establish that the current profile is suitable. If it was already shown unsuitable for the same work, a new lookup failure does not revoke that finding or authorize resuming on it. If suitability is unknown, call it neither suitable nor unsuitable; continue according to the task and verified facts.

## Match the profile to the work

Assess the next bounded work: required capabilities, result quality, acceptable time and cost, repetition and verification. Conversation length and the number of tools or systems do not establish complexity. Preserve an established user choice while requirements remain unchanged.

Compare those requirements with current official model/reasoning guidance and the capabilities of the local catalog. Documentation does not establish the active task profile or account access; use authoritative session state and the verified local catalog for those facts.

Retain the active profile unless there is a demonstrated reason to change it. A newer model, more services, a desire to be careful, or the existence of a stronger alternative is not enough. Do not present a local inference as an OpenAI recommendation.

Recommend a model or reasoning change only when verified requirements and official guidance give a concrete reason to expect a needed improvement and the candidate is available with the target settings. Account for time and cost when relevant to the user.

Evaluate model and reasoning independently. More effort on the current model may be preferable to changing models; a model change alone does not justify increasing effort. Do not assign `high`, `xhigh` or `max` from a private task taxonomy; use current official criteria and restrictions.

This independence also applies to `keep`: retaining a model does not justify retaining its effort. Effort follows the planning and verification depth needed for the next work; the same requirement can affect both axes. If the initial profile is explicitly a technical seed, rather than a user choice, absence of prior failures or a separate request to save money does not establish that high effort is appropriate. This does not override a retained user choice.

Change speed only when the user has expressed a time priority and the chosen model supports it. Leave an absent current speed unknown; do not fill in a default or propose changing an unknown field without a demonstrated goal.

## Child lane

Before a subagent starts, assess its bounded work separately:

- Consider difficulty, risk, unknowns, independence and cost
- Do not inherit a strong root profile as a minimum for simple work or under-provision complex work merely to save cost
- Choose model/reasoning using the same official guidance and verified local capabilities. Include speed only if native spawn supports a separate speed field
- Pass the selected values directly to native spawn, rather than giving the user a recommendation about the child
- Do not classify or change the root profile because a child has different requirements

If the catalog or a required capability is unavailable, do not invent an override. Report the limitation to the operation owner. Inheritance is acceptable only if the inherited profile has not already been shown unsuitable for that same child work; do not start a child on a demonstrated unsuitable profile.
