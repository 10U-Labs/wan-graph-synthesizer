# The WAN-create worker image, run as a Fargate Spot task. Build context is the
# repo root (so it can copy lib/ and the entrypoint). The build_image workflow
# pushes it to the wan-graph-synthesizer ECR repo.
#
# The entrypoint reads the customer's inputs + the substrate from the S3 store,
# runs the pipeline (home/constrain/synthesize/validate via the wan_synthesizer design
# engine beside it, over the wan_graph interchange in lib/python), and writes the
# WAN JSON back to the store -- or records a 422 reason if no valid WAN exists.
FROM python:3.13-slim

WORKDIR /app

COPY lib/python/ /app/lib/python/
COPY src/api/endpoints/customers/wan/synthesizer/ /app/synthesizer/

RUN pip install --no-cache-dir boto3 PyYAML

ENV PYTHONPATH=/app/lib/python:/app/synthesizer

# Call main() directly (rather than running the file as __main__) so the module
# stays import-clean for unit tests with no uncoverable __main__ guard.
ENTRYPOINT ["python", "-c", "import entrypoint; entrypoint.main()"]
