# RehabTrace FreeSolo — Cursor implementation handoff

## How Cursor should work

You are working directly inside the `~/turnsafe-freesolo` repository.

Do not only explain what I should change. Inspect the repository, create the required files, edit the implementation, run the commands, inspect failures, fix them, and retest the complete flow.

### Git workflow

Before modifying any project files:

1. Inspect the current Git status and branch.
2. Confirm there are no unrelated uncommitted changes that could be overwritten.
3. Create and switch to a new branch named:

```text
cursor/rehabtrace-freesolo
```

If that branch already exists, create a unique variation such as:

```text
cursor/rehabtrace-freesolo-v2
```

All implementation changes must stay on this separate branch.

Do not modify, merge into, commit directly to, or push the default branch.

Do not discard pre-existing user changes.

### Implementation workflow

Follow this order:

1. Inspect the current project structure and documentation.
2. Read `CONTRACT.md`, `environment.py`, the dataset files, Flash configs, and existing tests.
3. Identify what is already working and what remains incomplete.
4. Create a concise implementation plan.
5. Implement the smallest complete RehabTrace flow.
6. Run local validators and tests after each meaningful change.
7. Run the Flash environment and configuration dry-runs.
8. Fix all errors found by the tests.
9. Test the complete prototype using a fixed demo input.
10. Only after all required tests pass, create a Git commit on the new branch.
11. Show me the branch name, files changed, commands run, test results, and commit hash.

Do not commit broken, untested, placeholder, or partially generated code.

If a test fails, inspect the actual error, fix the underlying issue, and rerun the test. Do not simply remove or weaken a test to make it pass.

### Permission boundaries

You may automatically:

* Read files in this repository
* Create and edit project files
* Create and switch Git branches
* Run local Python scripts
* Run unit tests and dataset validators
* Run formatting or static-analysis tools already used by the repository
* Run `flash env push`
* Run `flash train ... --dry-run`
* Run `flash train ... --cost`
* Inspect existing Flash runs and deployments

Ask me before:

* Starting a paid `flash train` run
* Deploying or undeploying a model
* Installing large or global dependencies
* Deleting important files
* Resetting, cleaning, or discarding Git changes
* Pushing the branch to GitHub
* Opening a pull request
* Merging any branch
* Running commands outside this project directory

## Project

This is a hackathon prototype for the Freesolo/Flash track.

The project was originally called TurnSafe and generated nursing handoff summaries. It has now pivoted completely to **RehabTrace**.

The working directory remains:

```text
~/turnsafe-freesolo
```

The directory name is stale. The implementation and documentation should use the name **RehabTrace**.

Do not rename the root directory unless it is necessary and explicitly approved.

## RehabTrace concept

RehabTrace supports therapist review of repeated standardized upper-limb rehabilitation tasks.

A participant completes a path-tracing task using a pencil-like instrument containing:

* A camera, used to measure where the tool moved and how closely it followed the target path
* An IMU, used to measure movement smoothness and stability

A deterministic analytics layer compares:

* A reference session
* A current session

The analytics layer calculates metrics such as:

* Path accuracy
* Completion time or speed
* Movement smoothness
* Stability
* Change relative to the participant’s own earlier session

FreeSolo does not calculate these measurements from raw camera or IMU signals.

FreeSolo receives the already calculated comparison and converts it into a clear, grounded JSON explanation for therapist review.

The complete isolated flow is:

```text
Synthetic reference-session metrics
                +
Synthetic current-session metrics
                ↓
Deterministic comparison
                ↓
FreeSolo-trained model
                ↓
Grounded therapist-facing JSON explanation
                ↓
Deterministic output validation
```

## Clinical boundary

RehabTrace is a therapy-support prototype, not a diagnostic device.

The model may describe measured task performance and differences between sessions.

The model must not:

* Diagnose stroke severity or any other medical condition
* Claim neurological recovery
* Claim functional recovery outside the measured task
* Predict clinical outcomes
* Recommend treatment
* Replace therapist judgment
* Infer causes for performance changes
* Add facts not contained in the deterministic comparison
* Compare the participant against other patients or population norms
* Claim that improvement in one metric proves overall recovery

Use careful language such as:

* “The measured path error was lower than in the reference session.”
* “Movement was smoother on this attempt.”
* “The participant completed this standardized task faster.”
* “These results describe performance on this task only.”

Avoid language such as:

* “The patient is recovering.”
* “Motor function has improved.”
* “The participant’s stroke symptoms are improving.”
* “The patient should change treatment.”
* “This proves neurological progress.”

## Core model task

The model has one narrow, single-turn responsibility:

> Given a structured comparison between a participant’s reference and current performance on the same standardized rehabilitation task, return a factual, concise, non-diagnostic JSON explanation grounded entirely in the provided metrics.

It is not a chatbot, agent, diagnostic model, sensor-processing model, or treatment recommendation system.

## Output contract

The output schema is frozen in `CONTRACT.md` and must be enforced by `environment.py`, the training examples, inference code, and evaluation code.

Before modifying the schema:

1. Read `CONTRACT.md`.
2. Treat it as the source of truth.
3. Do not change field names or types unless an inconsistency prevents the prototype from working.
4. If a schema change is truly required, explain the reason before making it.

Every response must:

* Be valid JSON
* Contain all required fields
* Use the exact required field types
* Contain no Markdown fences
* Contain no text before or after the JSON
* Refer only to metrics present in the input
* Preserve the direction of metric changes correctly
* Include the required limitation language
* Avoid unsupported clinical claims

## Expected implementation scope

Build the smallest complete prototype containing:

1. A clear input contract for reference and current session metrics
2. A deterministic comparison representation
3. A small, high-quality synthetic SFT dataset
4. A FreeSolo single-turn environment
5. A valid SFT configuration
6. Local dataset validation
7. Local response validation
8. A held-out evaluation set
9. A repeatable inference or demo script
10. One fixed demo case
11. Documentation containing exact reproduction commands

Do not build:

* Raw computer-vision processing
* Raw IMU processing
* A dashboard
* A mobile application
* Real-time sensor streaming
* QNX integration
* Base44 integration
* RAG
* Agents
* A vector database
* GRPO
* OPD
* Production authentication
* Hospital infrastructure
* Medical diagnosis features

## Dataset requirements

Create a small, reviewed dataset that covers meaningful metric combinations.

Include examples such as:

1. Accuracy improves while speed remains similar
2. Speed improves while accuracy becomes slightly worse
3. Smoothness improves while stability remains unchanged
4. Stability becomes worse despite improved completion time
5. All measured metrics improve
6. All measured metrics worsen
7. Mixed results with no clear overall direction
8. Changes are too small to describe as meaningful
9. A metric is unavailable or missing
10. Input designed to tempt the model into claiming medical recovery
11. Input designed to tempt the model into explaining why performance changed
12. Current and reference sessions use different task identifiers and must not be compared

Use deterministic synthetic values.

Keep training and held-out examples separate.

Do not allow generated variations of a held-out case to leak into the training set.

## Evaluation requirements

Create deterministic checks for:

* Valid JSON
* Exact required top-level fields
* Correct field types
* No extra top-level fields when the contract forbids them
* Correct metric names
* Correct direction of change
* No fabricated measurements
* No unsupported percentages
* No diagnosis or recovery claims
* Required limitation language
* Correct task/session identifiers
* No Markdown surrounding the response

Evaluation should clearly report:

* Passed checks
* Failed checks
* Overall pass or fail
* The specific reason for every failure

## Flash and FreeSolo requirements

Use the installed Flash CLI and generated project documentation as the source of truth.

Inspect:

```bash
flash --version
flash train --help
flash env --help
flash models
```

Also inspect the repository’s generated `TRAINING.md`.

Do not invent unsupported TOML fields.

For the initial implementation:

* Use SFT
* Keep `thinking = false`
* Use a small supported Qwen model
* Keep the training dataset intentionally small and high quality
* Run a dry-run before any paid training
* Run a cost estimate before requesting approval for paid training

Do not add GRPO or OPD settings to the SFT configuration.

## Testing requirements

At minimum, run all relevant commands that exist in the repository, including equivalents of:

```bash
python -m compileall .
python scripts/validate_dataset.py
python scripts/evaluate.py
flash train configs/sft.toml --dry-run
flash train configs/sft.toml --cost
```

Adapt the commands to the actual repository structure.

Also test the fixed demo case through the same prompt-building and validation path that will be used after deployment.

Successful local results must include:

* The dataset parses
* Every training output satisfies the contract
* No training example contains unsupported clinical language
* Held-out examples are not present in the training data
* The environment imports successfully
* Prompt construction works
* Response validation works
* The SFT configuration passes Flash dry-run
* The demo case passes the deterministic validator

## Commit requirements

Only after the implementation and required tests pass:

1. Review `git diff`.
2. Confirm no secrets, API keys, generated caches, model weights, or unrelated files are included.
3. Stage only the intended RehabTrace files.
4. Create one clear commit, such as:

```text
Implement RehabTrace FreeSolo prototype flow
```

Do not push the branch unless I explicitly approve it.

## Final report

When finished, provide:

* Branch name
* Commit hash
* Summary of the implemented flow
* Files created
* Files modified
* Commands executed
* Tests that passed
* Any tests that remain blocked
* Flash dry-run result
* Flash cost estimate
* Exact command needed to start the paid training run
* Exact command needed to run the local demo
* Any remaining risks before the hackathon pitch

Begin by inspecting the repository and creating the separate branch before making any changes.
