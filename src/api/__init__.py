"""REST API for the three-tier WAN designer.

One AWS Lambda handler per resource (``endpoints/<resource>/lambdas/handler.py``),
deployed by the OpenTofu stack beside it; nested resources live under their parent
(``endpoints/carriers/merge/``, ``endpoints/customers/wan/``) just as the API nests
them. The WAN itself is built by the Fargate synthesizer task under
``endpoints/customers/wan/``.
"""
