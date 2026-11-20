"""Despliegue Canary en Kubernetes con análisis automático sobre CloudWatch Logs.

Flujo por microservicio cuya imagen cambió (tag = hash del contenido de su código):
  1. canary = 1 réplica con la versión NUEVA, stable escalado a 4 réplicas con la versión ACTUAL
     -> el Service (selector solo `app`) envía ~20 % del tráfico al canary (1 de 5 endpoints).
  2. Espera readiness del canary (si no queda Ready -> rollback).
  3. Genera tráfico sintético por el endpoint GraphQL del ambiente durante --analysis-seconds.
  4. Lee de CloudWatch Logs (/aegisvolt/<env>/<servicio>) los eventos `http.request` del track canary:
        tasa de error 5xx <= --max-error-rate   (default 5 %)
        latencia p95      <= --max-p95-ms       (default 1000 ms)
        peticiones        >= --min-requests     (default 10, para que la muestra sea significativa)
        reinicios del pod canary == 0
  5. OK  -> PROMOTE: la versión nueva pasa al Deployment stable (rolling update) y el canary vuelve a 0.
     NOK -> ROLLBACK automático: canary a 0, stable intacto con la versión anterior; exit code 1.

Uso:
  python scripts/deploy/canary.py deploy --env dev                       # build + kind load + canary
  python scripts/deploy/canary.py deploy --env dev --inject-canary-error-rate 0.6   # demo de rollback
  python scripts/deploy/canary.py status --env dev
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import statistics
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import boto3
import httpx
import yaml

ROOT = Path(__file__).resolve().parents[2]
OVERLAYS = ROOT / "deploy" / "k8s" / "overlays"
GATEWAY_NODE_PORT = {"dev": 30080, "test": 30081, "prod": 30082}


@dataclass(frozen=True)
class Component:
    key: str
    deployment: str
    image_repo: str
    dockerfile: str
    context: str
    sources: tuple[str, ...]
    container: str = "app"
    canary: bool = True


COMPONENTS = [
    Component(
        "station-reservation",
        "station-reservation-service",
        "aegisvolt/station-reservation",
        "services/station-reservation/Dockerfile",
        "services",
        ("services/common", "services/station-reservation"),
    ),
    Component(
        "billing-wallet",
        "billing-wallet-service",
        "aegisvolt/billing-wallet",
        "services/billing-wallet/Dockerfile",
        "services",
        ("services/common", "services/billing-wallet"),
    ),
    Component(
        "energy-dispatch",
        "energy-dispatch-service",
        "aegisvolt/energy-dispatch",
        "services/energy-dispatch/Dockerfile",
        "services",
        ("services/common", "services/energy-dispatch"),
    ),
    Component(
        "graphql-gateway",
        "graphql-gateway",
        "aegisvolt/graphql-gateway",
        "services/graphql-gateway/Dockerfile",
        "services",
        ("services/common", "services/graphql-gateway"),
    ),
    Component(
        "frontend",
        "frontend",
        "aegisvolt/frontend",
        "frontend/Dockerfile",
        "frontend",
        ("frontend",),
        container="web",
        canary=False,
    ),
]
SKIP_DIRS = {"__pycache__", "tests", "node_modules", "dist", ".pytest_cache", "test-results", "playwright-report"}


# ----------------------------------------------------------------------------- utilidades
def log(msg: str) -> None:
    print(f"[canary] {msg}", flush=True)


def run(cmd: list[str], *, capture: bool = False, check: bool = True, input_text: str | None = None) -> str:
    result = subprocess.run(
        cmd, check=False, text=True, capture_output=capture, input=input_text, encoding="utf-8"
    )
    if check and result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip() if capture else ""
        raise RuntimeError(f"Falló: {' '.join(cmd)}\n{detail}")
    return (result.stdout or "").strip() if capture else ""


def content_tag(component: Component) -> str:
    digest = hashlib.sha256()
    for source in component.sources:
        base = ROOT / source
        for path in sorted(base.rglob("*")):
            if path.is_dir() or any(part in SKIP_DIRS for part in path.relative_to(ROOT).parts):
                continue
            digest.update(str(path.relative_to(ROOT)).replace("\\", "/").encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()[:12]


class Kube:
    def __init__(self, context: str, namespace: str):
        self.base = ["kubectl", "--context", context, "-n", namespace]
        self.namespace = namespace

    def __call__(self, *args: str, capture: bool = True, check: bool = True, input_text: str | None = None) -> str:
        return run([*self.base, *args], capture=capture, check=check, input_text=input_text)

    def image(self, deployment: str) -> str | None:
        out = self(
            "get", "deployment", deployment, "-o", "jsonpath={.spec.template.spec.containers[0].image}", check=False
        )
        return out or None

    def replicas(self, deployment: str) -> int:
        out = self("get", "deployment", deployment, "-o", "jsonpath={.spec.replicas}", check=False)
        return int(out or 0)

    def scale(self, deployment: str, replicas: int) -> None:
        self("scale", "deployment", deployment, f"--replicas={replicas}")

    def rollout(self, deployment: str, timeout: int = 180) -> bool:
        result = subprocess.run(
            [*self.base, "rollout", "status", "deployment", deployment, f"--timeout={timeout}s"],
            text=True,
            capture_output=True,
        )
        return result.returncode == 0

    def restarts(self, selector: str) -> int:
        out = self(
            "get",
            "pods",
            "-l",
            selector,
            "-o",
            "jsonpath={range .items[*]}{.status.containerStatuses[0].restartCount}{' '}{end}",
            check=False,
        )
        return sum(int(x) for x in out.split() if x.isdigit())


# ----------------------------------------------------------------------------- build
def build_images(components: list[Component], kind_cluster: str | None) -> dict[str, str]:
    images: dict[str, str] = {}
    for component in components:
        if not (ROOT / component.dockerfile).exists():
            log(f"omitido {component.key}: no existe {component.dockerfile}")
            continue
        tag = content_tag(component)
        image = f"{component.image_repo}:{tag}"
        images[component.key] = image
        log(f"build {image}")
        run(
            [
                "docker",
                "build",
                "-q",
                "-t",
                image,
                "--build-arg",
                f"APP_VERSION={tag}",
                "-f",
                str(ROOT / component.dockerfile),
                str(ROOT / component.context),
            ],
            capture=True,
        )
        if kind_cluster:
            if not shutil.which("kind"):
                raise SystemExit("kind no está instalado (winget install Kubernetes.kind)")
            run(["kind", "load", "docker-image", image, "--name", kind_cluster], capture=True)
    return images


# ----------------------------------------------------------------------------- manifiestos
def render_and_apply(kube: Kube, env: str, desired_stable: dict[str, str]) -> None:
    """Aplica el overlay preservando la imagen stable en ejecución (nunca la revierte un `apply`)."""
    rendered = run(["kubectl", "kustomize", str(OVERLAYS / env)], capture=True)
    docs = [d for d in yaml.safe_load_all(rendered) if d]
    by_deployment = {c.deployment: c for c in COMPONENTS}
    to_apply = []
    for doc in docs:
        if doc.get("kind") == "Deployment":
            name = doc["metadata"]["name"]
            component = by_deployment.get(name.removesuffix("-canary"))
            if component is not None:
                image = kube.image(name) or desired_stable.get(component.key)
                if image is None:
                    log(f"omitido {name}: aún no hay imagen construida")
                    continue
                doc["spec"]["template"]["spec"]["containers"][0]["image"] = image
        to_apply.append(doc)
    kube("apply", "-f", "-", input_text=yaml.safe_dump_all(to_apply, sort_keys=False))


# ----------------------------------------------------------------------------- tráfico + métricas
QUERIES = [
    "{ stations { id connectors { id status liveSession { energyKwh } } } }",
    "{ wallets { fleetId balance } }",
    '{ priceQuote(stationId: "BOG-NORTE", connectorId: "BOG-NORTE-C1", estimatedKwh: 20) { total } }',
    "{ serviceHealth { name status } }",
    "{ featureFlags { key enabled } }",
]


def generate_traffic(url: str, seconds: int, stop: threading.Event, counters: dict) -> None:
    deadline = time.time() + seconds
    with httpx.Client(timeout=10) as client:
        i = 0
        while time.time() < deadline and not stop.is_set():
            try:
                response = client.post(url, json={"query": QUERIES[i % len(QUERIES)]})
                counters["ok" if response.status_code < 500 else "error"] += 1
            except httpx.HTTPError:
                counters["error"] += 1
            i += 1
            time.sleep(0.12)


@dataclass
class Analysis:
    service: str
    track: str
    requests: int = 0
    errors: int = 0
    latencies: list[float] = field(default_factory=list)

    @property
    def error_rate(self) -> float:
        return self.errors / self.requests if self.requests else 0.0

    @property
    def p95_ms(self) -> float:
        if len(self.latencies) < 2:
            return self.latencies[0] if self.latencies else 0.0
        return statistics.quantiles(self.latencies, n=20)[18]


def read_cloudwatch(logs, env: str, service_log_name: str, start_ms: int) -> dict[str, Analysis]:
    """Equivalente CloudWatch Logs Insights:
    fields status, duration_ms | filter event = "http.request" | stats count(*), sum(status >= 500),
    pct(duration_ms, 95) by track
    """
    group = f"/aegisvolt/{env}/{service_log_name}"
    tracks = {t: Analysis(service_log_name, t) for t in ("stable", "canary")}
    kwargs = {"logGroupName": group, "startTime": start_ms}
    while True:
        page = logs.filter_log_events(**kwargs)
        for event in page.get("events", []):
            try:
                body = json.loads(event["message"])
            except (ValueError, KeyError):
                continue
            if body.get("event") != "http.request" or body.get("track") not in tracks:
                continue
            analysis = tracks[body["track"]]
            analysis.requests += 1
            if int(body.get("status", 0)) >= 500:
                analysis.errors += 1
            analysis.latencies.append(float(body.get("duration_ms", 0)))
        token = page.get("nextToken")
        if not token or token == kwargs.get("nextToken"):
            return tracks
        kwargs["nextToken"] = token


def publish_metrics(cloudwatch, env: str, analysis: Analysis) -> None:
    try:
        cloudwatch.put_metric_data(
            Namespace=f"AegisVolt/{env}",
            MetricData=[
                {
                    "MetricName": name,
                    "Dimensions": [{"Name": "Service", "Value": analysis.service}],
                    "Value": value,
                    "Unit": unit,
                }
                for name, value, unit in (
                    ("CanaryErrorRate", analysis.error_rate * 100, "Percent"),
                    ("CanaryP95Latency", analysis.p95_ms, "Milliseconds"),
                    ("CanaryRequests", analysis.requests, "Count"),
                )
            ],
        )
    except Exception as exc:  # noqa: BLE001
        log(f"aviso: no se publicaron métricas en CloudWatch ({exc})")


# ----------------------------------------------------------------------------- canary
def canary_release(args, kube: Kube, component: Component, new_image: str, logs, cloudwatch) -> dict:
    stable, canary = component.deployment, f"{component.deployment}-canary"
    baseline = kube.replicas(stable)
    weight = args.canary_weight
    canary_replicas = 1
    stable_during = max(baseline, math.ceil(canary_replicas * (100 - weight) / weight))
    old_image = kube.image(stable)
    report = {
        "service": component.deployment,
        "environment": args.env,
        "old_image": old_image,
        "new_image": new_image,
        "weight_percent": round(100 * canary_replicas / (canary_replicas + stable_during), 1),
        "thresholds": {
            "max_error_rate": args.max_error_rate,
            "max_p95_ms": args.max_p95_ms,
            "min_requests": args.min_requests,
        },
    }
    log(
        f"{stable}: {old_image} -> {new_image} | canary {canary_replicas} : stable {stable_during} "
        f"(~{report['weight_percent']} % del tráfico)"
    )

    def restore(promoted: bool) -> None:
        kube.scale(canary, 0)
        kube.scale(stable, baseline)
        if args.inject_canary_error_rate:
            kube("set", "env", f"deployment/{canary}", "FAULT_INJECTION_HTTP_500_RATE-", check=False)
        kube.rollout(stable)
        log(f"{stable}: {'PROMOVIDO' if promoted else 'ROLLBACK'} — stable={kube.image(stable)}")

    promoted = False
    try:
        kube("set", "image", f"deployment/{canary}", f"{component.container}={new_image}")
        if args.inject_canary_error_rate:
            log(f"inyectando FAULT_INJECTION_HTTP_500_RATE={args.inject_canary_error_rate} en el canary (demo)")
            kube("set", "env", f"deployment/{canary}", f"FAULT_INJECTION_HTTP_500_RATE={args.inject_canary_error_rate}")
        kube.scale(stable, stable_during)
        kube.scale(canary, canary_replicas)
        if not kube.rollout(canary, timeout=args.ready_timeout):
            report.update(decision="ROLLBACK", reason="el canary no alcanzó Ready")
            return report
        kube.rollout(stable, timeout=args.ready_timeout)

        start_ms = int(time.time() * 1000)
        counters = {"ok": 0, "error": 0}
        url = args.graphql_url or f"http://localhost:{GATEWAY_NODE_PORT[args.env]}/graphql"
        log(f"análisis: {args.analysis_seconds}s de tráfico sintético contra {url}")
        stop = threading.Event()
        generate_traffic(url, args.analysis_seconds, stop, counters)
        time.sleep(5)  # los servicios envían logs a CloudWatch en lotes cada 2 s

        tracks = read_cloudwatch(logs, args.env, component.deployment, start_ms)
        canary_stats, stable_stats = tracks["canary"], tracks["stable"]
        restarts = kube.restarts(f"app={component.deployment},track=canary")
        publish_metrics(cloudwatch, args.env, canary_stats)
        report.update(
            synthetic_traffic=counters,
            canary={
                "requests": canary_stats.requests,
                "errors_5xx": canary_stats.errors,
                "error_rate": round(canary_stats.error_rate, 4),
                "p95_ms": round(canary_stats.p95_ms, 1),
                "restarts": restarts,
            },
            stable={
                "requests": stable_stats.requests,
                "error_rate": round(stable_stats.error_rate, 4),
                "p95_ms": round(stable_stats.p95_ms, 1),
            },
        )
        failures = []
        if canary_stats.requests < args.min_requests:
            failures.append(f"muestra insuficiente ({canary_stats.requests} < {args.min_requests} peticiones)")
        if canary_stats.error_rate > args.max_error_rate:
            failures.append(f"tasa de error {canary_stats.error_rate:.1%} > {args.max_error_rate:.1%}")
        if canary_stats.p95_ms > args.max_p95_ms:
            failures.append(f"p95 {canary_stats.p95_ms:.0f} ms > {args.max_p95_ms} ms")
        if restarts:
            failures.append(f"{restarts} reinicios del pod canary")

        if failures:
            report.update(decision="ROLLBACK", reason="; ".join(failures))
            return report

        log(f"{stable}: métricas OK -> promoviendo al 100 %")
        kube("set", "image", f"deployment/{stable}", f"{component.container}={new_image}")
        if not kube.rollout(stable, timeout=args.ready_timeout):
            kube("rollout", "undo", f"deployment/{stable}")
            report.update(decision="ROLLBACK", reason="el rollout stable al 100 % falló")
            return report
        promoted = True
        report.update(decision="PROMOTED", reason="umbrales cumplidos")
        return report
    finally:
        restore(promoted)


def write_report(report: dict, report_dir: Path) -> None:
    report_dir.mkdir(parents=True, exist_ok=True)
    path = report_dir / f"canary-{report['environment']}-{report['service']}.json"
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    summary = os.getenv("GITHUB_STEP_SUMMARY")
    if summary:
        c = report.get("canary", {})
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write(
                f"| {report['service']} | {report['weight_percent']} % | {c.get('requests', '-')} | "
                f"{c.get('error_rate', '-')} | {c.get('p95_ms', '-')} | {c.get('restarts', '-')} | "
                f"**{report['decision']}** — {report['reason']} |\n"
            )


def cmd_deploy(args) -> int:
    namespace = f"aegisvolt-{args.env}"
    kube = Kube(args.context, namespace)
    selected = [c for c in COMPONENTS if args.services == "all" or c.key in args.services.split(",")]
    images = build_images(selected, None if args.skip_kind_load else args.kind_cluster)

    first_deploy = {c.key: kube.image(c.deployment) is None for c in selected}
    render_and_apply(kube, args.env, images)

    endpoint = os.getenv("AWS_ENDPOINT_URL", "http://localhost:4566")
    os.environ.setdefault("AWS_ACCESS_KEY_ID", "test")
    os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "test")
    logs = boto3.client("logs", endpoint_url=endpoint, region_name="us-east-1")
    cloudwatch = boto3.client("cloudwatch", endpoint_url=endpoint, region_name="us-east-1")

    summary = os.getenv("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write(f"### Canary deployment — `{args.env}`\n\n| Servicio | Peso | Peticiones canary | "
                     "Error rate | p95 ms | Reinicios | Decisión |\n|---|---|---|---|---|---|---|\n")

    failed = False
    for component in selected:
        new_image = images.get(component.key)
        if new_image is None:
            continue
        current = kube.image(component.deployment)
        if first_deploy[component.key]:
            log(f"{component.deployment}: primer despliegue (línea base) -> {new_image}, sin canary")
            kube.rollout(component.deployment, timeout=args.ready_timeout)
            continue
        if current == new_image:
            log(f"{component.deployment}: sin cambios ({new_image}), se omite")
            continue
        if not component.canary:
            log(f"{component.deployment}: rolling update -> {new_image}")
            kube("set", "image", f"deployment/{component.deployment}", f"{component.container}={new_image}")
            kube.rollout(component.deployment, timeout=args.ready_timeout)
            continue
        report = canary_release(args, kube, component, new_image, logs, cloudwatch)
        write_report(report, Path(args.report_dir))
        log(json.dumps(report, indent=2, ensure_ascii=False))
        if report["decision"] != "PROMOTED":
            failed = True
            if not args.continue_on_failure:
                break
    return 1 if failed else 0


def cmd_status(args) -> int:
    kube = Kube(args.context, f"aegisvolt-{args.env}")
    print(kube("get", "deployments", "-o", "custom-columns=DEPLOYMENT:.metadata.name,TRACK:.metadata.labels.track,"
               "REPLICAS:.spec.replicas,READY:.status.readyReplicas,IMAGE:.spec.template.spec.containers[0].image"))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    deploy = sub.add_parser("deploy")
    deploy.add_argument("--env", required=True, choices=["dev", "test", "prod"])
    deploy.add_argument("--services", default="all", help="all o lista: station-reservation,graphql-gateway,...")
    deploy.add_argument("--context", default="kind-aegisvolt")
    deploy.add_argument("--kind-cluster", default="aegisvolt")
    deploy.add_argument("--skip-kind-load", action="store_true")
    deploy.add_argument("--canary-weight", type=int, default=20)
    deploy.add_argument("--analysis-seconds", type=int, default=45)
    deploy.add_argument("--max-error-rate", type=float, default=0.05)
    deploy.add_argument("--max-p95-ms", type=float, default=1000)
    deploy.add_argument("--min-requests", type=int, default=10)
    deploy.add_argument("--ready-timeout", type=int, default=180)
    deploy.add_argument("--graphql-url")
    deploy.add_argument("--inject-canary-error-rate", type=float, default=0.0)
    deploy.add_argument("--continue-on-failure", action="store_true")
    deploy.add_argument("--report-dir", default=str(ROOT / ".canary-reports"))
    deploy.set_defaults(func=cmd_deploy)

    status = sub.add_parser("status")
    status.add_argument("--env", required=True, choices=["dev", "test", "prod"])
    status.add_argument("--context", default="kind-aegisvolt")
    status.set_defaults(func=cmd_status)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
