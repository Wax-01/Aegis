"""Inspección y restauración de versiones del terraform.tfstate en el bucket S3 versionado.

  python scripts/tfstate_versions.py list    --workspace dev
  python scripts/tfstate_versions.py show    --workspace dev --version-id <id>      # resumen de esa versión
  python scripts/tfstate_versions.py download --workspace dev --version-id <id> --out prev.tfstate
  python scripts/tfstate_versions.py restore --workspace dev --version-id <id>      # la vuelve "latest"

Cómo funciona la restauración: S3 no "borra" versiones; `restore` hace CopyObject de la versión elegida sobre
la misma llave, lo que crea una NUEVA versión actual con el contenido antiguo (la versión corrupta sigue
disponible como no-actual, auditoría completa). Alternativa equivalente con Terraform:
  terraform state pull > corrupt.tfstate   (respaldo)
  python scripts/tfstate_versions.py download ... --out prev.tfstate
  terraform state push -force prev.tfstate (-force porque el serial es menor al actual)
Antes de restaurar, asegúrate de que nadie esté ejecutando apply (lock .tflock) y luego corre `terraform plan`.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

import boto3

BUCKET = os.getenv("TF_STATE_BUCKET", "aegisvolt-tfstate")
KEY_TEMPLATE = "env:/{workspace}/aegisvolt/terraform.tfstate"


def s3_client():
    endpoint = os.getenv("AWS_ENDPOINT_URL", "http://localhost:4566")
    os.environ.setdefault("AWS_ACCESS_KEY_ID", "test")
    os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "test")
    return boto3.client("s3", endpoint_url=endpoint or None, region_name=os.getenv("AWS_REGION", "us-east-1"))


def summarize(body: bytes) -> str:
    state = json.loads(body)
    resources = state.get("resources", [])
    return (
        f"serial={state.get('serial')} lineage={state.get('lineage', '')[:8]} "
        f"terraform={state.get('terraform_version')} recursos={len(resources)}"
    )


def cmd_list(s3, key: str) -> None:
    print(f"Bucket: {BUCKET}  versioning={s3.get_bucket_versioning(Bucket=BUCKET).get('Status')}")
    print(f"Llave:  {key}\n")
    versions = [
        v for v in s3.list_object_versions(Bucket=BUCKET, Prefix=key).get("Versions", []) if v["Key"] == key
    ]
    if not versions:
        print("(sin versiones: ¿el workspace ya hizo apply?)")
        return
    for v in sorted(versions, key=lambda x: x["LastModified"], reverse=True):
        body = s3.get_object(Bucket=BUCKET, Key=key, VersionId=v["VersionId"])["Body"].read()
        marker = "LATEST " if v["IsLatest"] else "       "
        print(
            f"{marker}{v['LastModified']:%Y-%m-%d %H:%M:%S}  {v['VersionId']}  {v['Size']:>7} B  {summarize(body)}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("action", choices=["list", "show", "download", "restore"])
    parser.add_argument("--workspace", required=True, choices=["dev", "test", "prod"])
    parser.add_argument("--version-id")
    parser.add_argument("--out")
    args = parser.parse_args()

    s3 = s3_client()
    key = KEY_TEMPLATE.format(workspace=args.workspace)

    if args.action == "list":
        cmd_list(s3, key)
        return 0
    if not args.version_id:
        parser.error("--version-id es obligatorio para show/download/restore")

    body = s3.get_object(Bucket=BUCKET, Key=key, VersionId=args.version_id)["Body"].read()
    if args.action == "show":
        print(summarize(body))
        for r in json.loads(body).get("resources", []):
            print(f"  {r.get('module', 'root')}.{r['type']}.{r['name']}")
    elif args.action == "download":
        out = args.out or f"{args.workspace}-{args.version_id[:12]}.tfstate"
        with open(out, "wb") as fh:
            fh.write(body)
        print(f"Versión {args.version_id} guardada en {out} ({summarize(body)})")
    elif args.action == "restore":
        result = s3.copy_object(
            Bucket=BUCKET,
            Key=key,
            CopySource={"Bucket": BUCKET, "Key": key, "VersionId": args.version_id},
        )
        print(f"Restaurada {args.version_id} -> nueva versión actual {result.get('VersionId')}")
        print("Siguiente paso: terraform workspace select", args.workspace, "&& terraform plan")
    return 0


if __name__ == "__main__":
    sys.exit(main())
