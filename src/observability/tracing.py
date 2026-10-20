from __future__ import annotations

import time
from contextlib import contextmanager
from typing import Dict, Generator


class PipelineTracer:
    """
    Observability & tracing component measuring latency per stage
    and estimating token consumption and API cost.
    """

    def __init__(self) -> None:
        self.latencies_ms: Dict[str, float] = {}
        self.input_tokens: int = 0
        self.output_tokens: int = 0

    @contextmanager
    def time_step(self, step_name: str) -> Generator[None, None, None]:
        t0 = time.perf_counter()
        try:
            yield
        finally:
            elapsed = (time.perf_counter() - t0) * 1000.0
            self.latencies_ms[step_name] = round(elapsed, 2)

    def track_tokens(self, prompt_text: str, response_text: str) -> None:
        self.input_tokens += max(1, len(prompt_text) // 4)
        self.output_tokens += max(1, len(response_text) // 4)

    def estimate_cost_usd(self) -> float:
        # Standard blending rate for modern small models ($0.15/1M in, $0.60/1M out)
        cost_in = (self.input_tokens / 1_000_000.0) * 0.15
        cost_out = (self.output_tokens / 1_000_000.0) * 0.60
        return round(cost_in + cost_out, 6)
