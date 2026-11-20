"""Levanta la plataforma local COMPLETA para la demo: kind + Floci persistente + Terraform (3 workspaces) +
despliegue de los 3 ambientes. Idempotente: se puede volver a ejecutar.

  python scripts/platform_up.py                 # todo
  python scripts/platform_up.py --envs dev      # solo dev
  python scripts/platform_up.py --skip-deploy   # solo infraestructura

Requisitos en PATH: docker, kind, kubectl, terraform  (winget install Kubernetes.kind Hashicorp.Terraform)
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
INFRA = ROOT / "infra"
CLUSTER = "aegisvolt"


def sh(*cmd: str, cwd: Path | None = None, check: bool = True, capture: bool = False) -> str:
    print(f"$ {' '.join(cmd)}", flush=True)
    result = subprocess.run(cmd, cwd=cwd, text=True, capture_output=capture, check=False)
    if check and result.returncode != 0:
        if capture:
            print(result.stdout, result.stderr)
        raise SystemExit(f"Falló: {' '.join(cmd)}")
    return (result.stdout or "").strip() if capture else ""


def require(*tools: str) -> None:
    missing = [t for t in tools if not shutil.which(t)]
    if missing:
        raise SystemExit(
            f"Faltan herramientas: {', '.join(missing)}\n"
            "  winget install Kubernetes.kind Hashicorp.Terraform   (y reabre la terminal)"
        )


def wait_http(url: str, timeout: int = 90) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            httpx.get(url, timeout=3)
            return
        except httpx.HTTPError:
            time.sleep(2)
    raise SystemExit(f"{url} no respondió en {timeout}s")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--envs", default="dev,test,prod")
    parser.add_argument("--skip-deploy", action="store_true")
    args = parser.parse_args()
    envs = [e.strip() for e in args.envs.split(",") if e.strip()]
    require("docker", "kind", "kubectl", "terraform")

    # 1) Clúster kind (crea la red docker `kind`)
    clusters = sh("kind", "get", "clusters", capture=True).split()
    if CLUSTER not in clusters:
        sh("kind", "create", "cluster", "--config", str(ROOT / "deploy/kind/cluster.yaml"))
    sh("kubectl", "config", "use-context", f"kind-{CLUSTER}")

    # 2) Floci persistente en la red de kind (el stack standalone de docker-compose.yml debe estar abajo)
    sh("docker", "compose", "-f", str(ROOT / "docker-compose.yml"), "down", check=False)
    sh("docker", "compose", "-f", str(ROOT / "deploy/floci/compose.yml"), "up", "-d")
    wait_http("http://localhost:4566/_localstack/health")

    # 3) Terraform bootstrap (bucket versionado + locks) — estado local
    boot = INFRA / "bootstrap"
    sh("terraform", "init", "-input=false", cwd=boot)
    sh("terraform", "apply", "-auto-approve", "-input=false", "-var-file=floci.tfvars", cwd=boot)

    # 4) Terraform por workspace (cada ambiente = su propio estado en env:/<ws>/...)
    live = INFRA / "live"
    sh(
        "terraform",
        "init",
        "-input=false",
        "-reconfigure",
        "-backend-config=backend/floci.s3.tfbackend",
        cwd=live,
    )
    existing = sh("terraform", "workspace", "list", cwd=live, capture=True)
    for env in envs:
        if env not in existing.replace("*", " ").split():
            sh("terraform", "workspace", "new", env, cwd=live)
        sh("terraform", "workspace", "select", env, cwd=live)
        sh("terraform", "apply", "-auto-approve", "-input=false", "-var-file=floci.tfvars", cwd=live)

    # 5) Despliegue de la aplicación en cada namespace
    if not args.skip_deploy:
        for env in envs:
            sh(sys.executable, str(ROOT / "scripts/deploy/canary.py"), "deploy", "--env", env)

    print("\nPlataforma lista:")
    ports = {"dev": (30080, 30090), "test": (30081, 30091), "prod": (30082, 30092)}
    for env in envs:
        gw, fe = ports[env]
        print(f"  {env:<5} GraphQL http://localhost:{gw}/graphql   Frontend http://localhost:{fe}")
    print("  Admin token:  terraform -chdir=infra/live output -raw admin_token   (por workspace)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
