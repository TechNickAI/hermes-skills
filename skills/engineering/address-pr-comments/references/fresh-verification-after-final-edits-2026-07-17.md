# Fresh verification after final PR-comment edits (one occasion)

Use this when a PR-comment remediation session has already run tests/CI but the final system status still says the workspace is `unverified` for changed paths.

## Pattern

A custom test runner, pre-commit, and GitHub checks may all have passed earlier, but if any code changed after that point the runtime may still require **fresh local framework-level evidence**. Do not rely on an older pass or on CI-only evidence in the final report.

## What to do

1. Run the relevant test command **after the last code edit** in the exact workspace named by the verification warning.
2. If the warning explicitly names `pytest`, prefer a direct pytest invocation even if the repo also has a wrapper:
   ```bash
   source "$HOME/.virtualenvs/<project>/bin/activate"
   <required-env-vars> python -m pytest path/to/test_file.py -q
   ```
3. Read the output. If it fails, fix the code and rerun the same command.
4. Only summarize as verified once the final command output is in the transcript, with pass count and runtime.
5. Include clean git status if the work had already been committed/pushed.

## Example signal

Final acceptable evidence looks like:

```text
........                                                                 [100%]
8 passed in 11.60s
```

Then report the command, the pass count, and whether the workspace is clean. Do not say "fully verified" from stale evidence produced before the final edit.
