# Evaluation plan

No evaluation results have been measured yet. This document defines the later reproducible evaluation rather than publishing placeholder scores.

## Scenario dataset

Store fixed scenarios with an injected cause, expected affected services, evidence available, and expected ambiguity/abstention behavior. Include payment delay, payment failures, inventory failures, downstream timeout, retries, service unavailability, and incomplete telemetry cases. Each scenario must be resettable without deleting unrelated developer data.

## Metrics

- **Top-1 root-cause accuracy:** investigations whose first ranked cause matches the scenario's labeled cause divided by evaluated scenarios with a determinate label.
- **Top-3 root-cause recall:** determinate scenarios where the labeled cause appears among the first three candidates divided by determinate scenarios.
- **Evidence-reference validity:** cited evidence IDs present in the bounded evidence package divided by all cited IDs.
- **Unsupported-claim rate:** claims labeled as factual that cannot be supported by retrieved observations divided by reviewed factual claims. Report the review method and sample size.
- **Investigation latency:** wall-clock time from request acceptance to persisted report; report sample count and percentiles.
- **Cost per investigation:** provider-reported or calculated token cost only when provider pricing and token counts are available. Otherwise report as unavailable.

Publish dataset version, counts, timestamp, environment, excluded cases, and limitations with every run. An ambiguous case is not scored as a failure when a well-grounded investigator abstains as designed; report abstention behavior separately.
