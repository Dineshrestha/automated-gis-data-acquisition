# Tests

Testing will be added in layers:

1. Pure-Python unit tests for request/batching/configuration logic.
2. ArcPy-dependent tests executed inside an ArcGIS Pro Python environment.
3. Provider integration tests against small public-data AOIs.
4. Large-AOI regression tests for corridor-scale acquisition behavior.

Client or proprietary project data should not be committed as test fixtures.
