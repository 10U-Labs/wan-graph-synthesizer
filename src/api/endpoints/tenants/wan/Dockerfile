# The WAN-create worker image, run as a Fargate Spot task. Build context is the
# repo root (so it can copy the synthesizer tree and the entrypoint). The
# build_image workflow pushes it to the wan-graph-synthesizer ECR repo.
#
# The entrypoint reads the tenant's inputs + the substrate from the S3 store,
# runs the pipeline (home/constrain/synthesize/validate via the synthesizer design
# engine, which loads the inputs through its own codec module), and writes the
# WAN JSON back to the store -- or records a 422 reason if no valid WAN exists.
FROM python:3.13-slim

WORKDIR /app

COPY src/api/endpoints/tenants/wan/entrypoint.py /app/entrypoint.py
COPY src/api/endpoints/tenants/wan/synthesizer/ /app/synthesizer/

RUN pip install --no-cache-dir boto3 PyYAML

ENV PYTHONPATH=/app
# Unbuffered stdout/stderr so progress logs reach CloudWatch live, not at exit.
ENV PYTHONUNBUFFERED=1

# Call main() directly (rather than running the file as __main__) so the module
# stays import-clean for unit tests with no uncoverable __main__ guard.
ENTRYPOINT ["python", "-c", "import entrypoint; entrypoint.main()"]
