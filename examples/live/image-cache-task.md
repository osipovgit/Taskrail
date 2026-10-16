```countersign-task
{
  "roots": {"app": "~/src/web-app", "ci": "~/src/ci-pipelines"},
  "verification": [
    "Two consecutive local runs: rebuild the API image without layer cache both times and use the resulting image in containers",
    "Two CI pipeline runs: rebuild the API image without layer cache both times",
    "An API image build failure stops execution instead of using an old image"
  ]
}
```

# Rebuild the API image without layer cache on every run

Each local stack start, integration suite, and CI pipeline run must rebuild the
API image without Docker layer cache. An old local image must not replace a new
build.

Known entry points:
- app/docker/api/Dockerfile
- ci/pipelines/web-app.groovy

Discover related files within these roots, trace the launch chain, and determine
the minimum change scope. Changes may affect necessary files except Git metadata
and orchestrator/agent configuration. Include each exact change path in the plan.

Requirements:
1. Disable build cache only for the API image. Preserve other image caches unless
   a necessity is demonstrated. Do not clear the global Docker cache.
2. Local and CI entry points must have the same fresh-build guarantee. Services
   started by one suite must reuse the image freshly and successfully built by
   that suite instead of rebuilding it.
3. The API and worker containers must use the current build result.
4. Build errors must stop execution instead of allowing an old image to run.
5. Preserve proxy/network settings, branch selection, and environment configuration.
6. Do not substitute --pull for --no-cache or infer source-code freshness from cache
   disabling alone. Inspect how source code enters the image.
7. Read-only Git history is allowed. Do not commit, push, or otherwise change Git
   state. Preserve existing user changes.

Run available built-in syntax checks and static review. Do not run Docker or the CI
pipeline. Report the runtime criteria above as unverified with concrete steps for
manual verification in the target environment. Prepare code for review.
