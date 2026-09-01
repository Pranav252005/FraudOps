"""Generated domains.

Everything in here CONSTRUCTS a dataset rather than reading one. That makes the
leak boundary different in kind from the rest of the project: the generator
writes the labels, so a feature that reads a generator parameter is a leak by
construction and not by prevalence. The boundary is enforced structurally --
observables and ground truth are separate objects and the observable record has
no label field -- rather than by a threshold on how good a feature is.
"""
