"""GridShift -- move flexible electricity demand to the cleanest hours.

Public surface:

    from gridshift import JobSpec, optimize, forecast_region

"""

from .scheduler import (  # noqa: F401
    Block,
    JobSpec,
    ScheduleError,
    ScheduleResult,
    optimize,
    savings_capture_rate,
)

__version__ = "0.1.0"
__all__ = [
    "JobSpec", "ScheduleResult", "Block", "ScheduleError",
    "optimize", "savings_capture_rate", "__version__",
]
