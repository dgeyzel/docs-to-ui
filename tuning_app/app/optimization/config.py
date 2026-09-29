"""Tracing DSPy's modules and optimizer steps, in the Tuning app only (SPEC §11.1).

The shared telemetry setup instruments LiteLLM for both apps; DSPy exists
only here, so its instrumentation is attached here, after the shared tracer
provider is in place.
"""

from openinference.instrumentation.dspy import DSPyInstrumentor
from plain.packages import PackageConfig, register_config


@register_config
class OptimizationConfig(PackageConfig):
    package_label = "optimization"

    def ready(self) -> None:
        instrumentor = DSPyInstrumentor()
        if not instrumentor.is_instrumented_by_opentelemetry:
            instrumentor.instrument()
