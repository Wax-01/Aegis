#!/usr/bin/env bash
# -----------------------------------------------------------------------------
# Configura el repositorio GitHub: ramas de ambiente + ruleset de protección + GitHub Environments.
#   Requisitos: gh auth login  y  el repo ya creado con `origin` apuntando a él.
#   Uso: bash scripts/github/setup_repo.sh
#
# Qué bloquea el ruleset (sin bypass, ni siquiera para administradores):
#   non_fast_forward        -> git push --force a dev/test/prod es rechazado
#   pull_request            -> git push directo a dev/test/prod es rechazado (solo merge vía PR)
#   required_status_checks  -> el botón Merge exige los 6 checks en verde
#   deletion                -> no se pueden borrar las ramas de ambiente
# -----------------------------------------------------------------------------
set -euo pipefail

REPO="$(gh repo view --json nameWithOwner -q .nameWithOwner)"
echo "Repositorio: $REPO"

# 1) Ramas de ambiente (se crean ANTES de activar el ruleset, desde la rama actual)
base="$(git rev-parse --abbrev-ref HEAD)"
for branch in dev test prod; do
  if git ls-remote --exit-code --heads origin "$branch" >/dev/null 2>&1; then
    echo "rama $branch ya existe en origin"
  else
    git push origin "$base:refs/heads/$branch"
  fi
done
gh repo edit "$REPO" --default-branch dev --delete-branch-on-merge --enable-merge-commit \
  --enable-squash-merge=false --enable-rebase-merge=false

# 2) Ruleset (idempotente: actualiza si ya existe)
existing_id="$(gh api "repos/$REPO/rulesets" -q '.[] | select(.name=="protect-environment-branches") | .id' || true)"
if [ -n "$existing_id" ]; then
  gh api -X PUT "repos/$REPO/rulesets/$existing_id" --input .github/rulesets/environment-branches.json >/dev/null
  echo "ruleset actualizado ($existing_id)"
else
  gh api -X POST "repos/$REPO/rulesets" --input .github/rulesets/environment-branches.json >/dev/null
  echo "ruleset creado"
fi

# 3) GitHub Environments (el job terraform-apply declara environment: <env>)
for env in dev test prod; do
  gh api -X PUT "repos/$REPO/environments/$env" >/dev/null
  echo "environment $env listo"
done

echo
echo "Listo. Verifica con:  gh api repos/$REPO/rulesets"
echo "Prueba del bloqueo:   git push --force origin test   (debe ser rechazado por el ruleset)"
