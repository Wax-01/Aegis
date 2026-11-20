"""Registra y programa los flujos de observabilidad en el servidor Prefect local.

prefect server start                        # UI en http://127.0.0.1:4200
set PREFECT_API_URL=http://127.0.0.1:4200/api
python observability/prefect/serve.py       # deja corriendo el worker de los deployments
"""

from aegis_flows import environment_health_check, saga_consistency_audit, trace_saga
from prefect import serve

if __name__ == "__main__":
    serve(
        environment_health_check.to_deployment(
            name="health-every-2m", interval=120, tags=["aegisvolt", "health"]
        ),
        saga_consistency_audit.to_deployment(
            name="saga-audit-every-5m",
            interval=300,
            parameters={"orphan_minutes": 5, "auto_recover": False},
            tags=["aegisvolt", "saga"],
        ),
        trace_saga.to_deployment(name="trace-saga-on-demand", tags=["aegisvolt", "trace"]),
    )
