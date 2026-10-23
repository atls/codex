# Model Fit for Codex Desktop

Model Fit recommends a model and reasoning effort for the **next bounded task**.
When explicitly enabled for one thread, its hook can switch the profile and
queue the complete original user input into the next turn. The user sends the
request once; the agent continues in the same thread on the selected profile.
Installation alone never activates a lifecycle hook. The package deliberately
uses project-local hook definitions with a selected thread ID so installing the
plugin cannot intercept unrelated chats.

This package is tested on Codex Desktop for macOS with an existing Codex
subscription sign-in and `codex` CLI. It uses experimental app-server methods
and the Desktop tool `mcp__codex_app__send_message_to_thread`. Verify those
capabilities on the target installation before enabling a working thread.
The package does not require an OpenAI API key.

## Install and enable

1. Keep a clone of `https://github.com/atls/codex` in a stable location. From
   that clone, run `codex plugin marketplace add "$PWD"`, restart Codex Desktop,
   and install `model-fit` from the `ATLS Codex` source in the Plugins Directory
   or with `codex plugin add model-fit@atls-codex`.
   A removed test worktree must never be the source of a working hook command.
2. Choose one project directory and one Codex thread. Tell Codex in that thread
   that Model Fit may switch its model automatically.
3. The hook command uses macOS `/usr/bin/python3` (Python 3.9 or newer); the
   skill's model-catalog projection also uses `jq`. From the stable clone, run
   the setup script first without `--write` to
   inspect the intended action, then with `--write` to add three native hooks:

   ```sh
   python3 plugins/model-fit/skills/model-fit/scripts/configure.py \
     --project "$PROJECT_DIR" --thread-id "$THREAD_ID"
   python3 plugins/model-fit/skills/model-fit/scripts/configure.py \
     --project "$PROJECT_DIR" --thread-id "$THREAD_ID" --write
   ```

   Set `PROJECT_DIR` to the absolute project directory and `THREAD_ID` to the
   exact Codex thread ID before running either command. The script preserves
   other hooks and writes only `<project>/.codex/hooks.json`. In a Git
   repository it excludes that local file through `info/exclude`; it refuses
   to write personal thread IDs into an already tracked hooks file.
4. Review and trust the exact definitions in Codex `/hooks`. Verify
   `UserPromptSubmit`, `PreToolUse` and `Stop` with `hooks/list`. An already
   loaded chat may need its normal session refresh after a definition changes.

To remove this thread's definitions, run the same command with `--remove
--write`; other project hooks stay in place.

## Daily use

Ask for ordinary work in the selected thread. For a suitable profile, Model
Fit records `keep` and work proceeds. For a justified change, the current turn
only changes the next-turn profile and queues the original request. The queued
turn checks its profile and complete input before executing the task. A
technical failure is reported instead of repeating an uncertain queue action.

The hook reads native `userMessage.content`, including ordered text and image
elements. It accepts only verified native image conversion in the queue
receipt. The answer relevance check runs on text-only replay and adds
one separate low-effort model call. It skips attachment-bearing replies.

Model Fit stores private state and a whitelist audit under `CODEX_HOME/.tmp/`.
Audit entries contain turn IDs, outcomes and bounded diagnostics; they do not
contain full prompts, tool arguments or attachment payloads. Model triage and
the text relevance check consume the signed-in Codex account's usage.

## Verify and update

Run deterministic checks without a model call:

```sh
python3 -m unittest discover -s evals/model-fit -p 'test_*.py'
python3 tools/build.py
```

The [eval README](../../evals/model-fit/README.md) explains optional live
behavioral runs. Re-run setup and review hook trust after updating the stable
clone, because changed definitions may need renewed trust. The full plugin is
distributed manually through GitHub; the separate guidance-only package is
prepared for public directory review and has no automatic switching.
After pulling a new source version, use `codex plugin marketplace upgrade
atls-codex` and `codex plugin add model-fit@atls-codex` to refresh the installed
copy, then re-run the project setup command from the stable clone.
