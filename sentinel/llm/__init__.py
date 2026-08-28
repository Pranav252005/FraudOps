"""LLM integration, kept in its own package and behind a hard contract.

Nothing in the detector, the scorer, or the calibration loop may import from
here. An LLM is non-deterministic and its output cannot be resampled into a
confidence interval, so routing any measured path through one would
contaminate exactly the numbers this project reports. The only sanctioned
use is narrative drafting, where the output is prose for a human to read and
every factual claim in it is mechanically verified before it can be filed
(`sentinel.narrative.citation`).
"""
