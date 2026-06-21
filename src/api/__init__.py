"""REST API for the three-tier WAN designer.

One AWS Lambda handler per resource (``endpoints/<resource>/lambdas/handler.py``),
deployed by the OpenTofu stack beside it; the WAN itself is built by the Fargate
optimizer task under ``endpoints/wan/``.
"""
