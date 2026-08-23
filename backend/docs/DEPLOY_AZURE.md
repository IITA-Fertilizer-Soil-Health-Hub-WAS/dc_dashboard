# Deploying to Azure Container Apps

The `redesign/python` branch deploys to **Azure Container Apps** via GitHub
Actions (`.github/workflows/deploy-azure.yml`) using the Bicep stack in
`infra/main.bicep`. Every push to `redesign/python` that touches `backend/**`,
`infra/**`, or the workflow builds a new image and rolls out web / worker / beat.

The stack: an Azure Container Registry, a Container Apps environment, an
**Azure Database for PostgreSQL Flexible Server**, an internal **Redis**
container app (the Celery broker), and three app containers —
**web** (gunicorn), **worker** (`celery worker`), **beat** (`celery beat`,
singleton). `DATABASE_URL`, the broker URL, `DJANGO_ALLOWED_HOSTS`, and
`CSRF_TRUSTED_ORIGINS` are computed inside Bicep — you never hand-write them.

---

## One-time bootstrap (run once, needs an Azure admin)

You need the Azure CLI (`az`) logged in to the target subscription, and admin
rights to create an app registration and a role assignment.

```bash
# ---- names you choose ----
RG=fieldbase-rg
LOCATION=westeurope
ACR=fieldbaseacr$RANDOM        # must be globally unique, lowercase alphanumeric
REPO=IITA-Fertilizer-Soil-Health-Hub-WAS/dc_dashboard
BRANCH=redesign/python

# 1. Resource group
az group create -n "$RG" -l "$LOCATION"

# 2. App registration + service principal for GitHub OIDC
APP_ID=$(az ad app create --display-name fieldbase-gha --query appId -o tsv)
az ad sp create --id "$APP_ID"

# 3. Federated credential: trust this repo + branch (no stored secret)
az ad app federated-credential create --id "$APP_ID" --parameters "{
  \"name\": \"redesign-python\",
  \"issuer\": \"https://token.actions.githubusercontent.com\",
  \"subject\": \"repo:${REPO}:ref:refs/heads/${BRANCH}\",
  \"audiences\": [\"api://AzureADTokenExchange\"]
}"

# 4. Owner on the resource group (Bicep creates an AcrPull role assignment,
#    which needs role-assignment write — Owner is the simplest grant on a
#    dedicated staging RG).
SUB_ID=$(az account show --query id -o tsv)
TENANT_ID=$(az account show --query tenantId -o tsv)
az role assignment create --assignee "$APP_ID" --role Owner \
  --scope "/subscriptions/${SUB_ID}/resourceGroups/${RG}"

echo "AZURE_CLIENT_ID=$APP_ID"
echo "AZURE_TENANT_ID=$TENANT_ID"
echo "AZURE_SUBSCRIPTION_ID=$SUB_ID"
echo "ACR_NAME=$ACR"
```

### GitHub configuration (repo → Settings → Secrets and variables → Actions)

**Secrets** (sensitive):

| Secret | Value |
|---|---|
| `AZURE_CLIENT_ID` | the `APP_ID` above |
| `AZURE_TENANT_ID` | tenant id above |
| `AZURE_SUBSCRIPTION_ID` | subscription id above |
| `POSTGRES_ADMIN_PASSWORD` | a strong **URL-safe** (alphanumeric) password — it is embedded in `DATABASE_URL` |
| `DJANGO_SECRET_KEY` | a fresh 50-char random string |
| `AUTH0_CLIENT_SECRET` | Auth0 app client secret |
| `ONA_TOKEN` | ONA API token |
| `ADMIN_PASSWORD` | first Platform Admin password (used once by `bootstrap_admin`) |

**Variables** (non-secret):

| Variable | Example |
|---|---|
| `AZURE_RG` | `fieldbase-rg` |
| `AZURE_LOCATION` | `westeurope` |
| `ACR_NAME` | the `$ACR` value above |
| `AUTH0_DOMAIN` | `your-tenant.eu.auth0.com` |
| `AUTH0_CLIENT_ID` | Auth0 app client id |
| `ONA_BASE_URL` | `https://api.ona.io` |
| `SITE_NAME` | `Fieldbase` |
| `ADMIN_EMAIL` | first Platform Admin email |

> With the GitHub CLI: `gh secret set DJANGO_SECRET_KEY -b"..." -R $REPO` and
> `gh variable set AZURE_RG -b"fieldbase-rg" -R $REPO`.

---

## First deploy

Push to `redesign/python` (or run the workflow manually — Actions → deploy-azure
→ Run workflow). The run will:

1. Build the image with ACR Tasks (context `backend/`, `backend/Dockerfile`).
2. Apply `infra/main.bicep` — creates everything and rolls web/worker/beat to
   the new image. The web revision runs `migrate` + `bootstrap_admin` before it
   serves (gated by the startup health probe).
3. Print the web URL and curl `/healthz/`.

The web URL is in the run summary and as the Bicep `webUrl` output
(`https://fieldbase-web.<region>.azurecontainerapps.io`).

### After the first deploy — Auth0 callback URLs

Add the web URL to your Auth0 application's **Allowed Callback URLs** /
**Allowed Logout URLs** (e.g. `https://<web-fqdn>/accounts/auth0/login/callback/`
— match the app's actual allauth callback path), then sign in.

---

## Verify

- Workflow is green; the smoke-test step got `200` from `/healthz/`.
- `az containerapp logs show -n fieldbase-web -g $RG --tail 50` shows migrations
  applied then gunicorn serving.
- `az containerapp logs show -n fieldbase-beat -g $RG --tail 50` shows the
  scheduler ticking; `fieldbase-worker` shows tasks executing.
- Browse `https://<web-fqdn>/` and sign in via Auth0.

## Notes & follow-ups

- **Media is ephemeral** — uploads under `/app/media` are lost on restart and
  not shared across replicas. Fine for staging (media is re-fetched from
  ONA/ODK). To persist: mount **Azure Files** to `/app/media` on the web app,
  or switch to Azure Blob via `django-storages`.
- **Web is pinned to 1 replica** because `migrate` runs in its start command.
  To scale web out, move `migrate`/`bootstrap_admin` into a Container Apps
  **Job** run before the rollout, then raise `maxReplicas`.
- **Custom domain**: `az containerapp hostname add` + a managed certificate,
  then add the new host to `DJANGO_ALLOWED_HOSTS` / `CSRF_TRUSTED_ORIGINS`.
- The legacy root `.github/workflows/ci-cd.yml` (R app, `release/*` branches) is
  untouched and does not collide with this workflow.
