# Deploying to Azure Container Apps

The `redesign/python` branch deploys to **Azure Container Apps** via GitHub
Actions (`.github/workflows/deploy-azure.yml`) using `infra/main.bicep`. Every
push to `redesign/python` that touches `backend/**`, `infra/**`, or the workflow
builds a new image, applies the stack, and runs the migration Job.

**Uses existing resources:** an existing **Azure Container Registry** and an
existing **Postgres Flexible Server**. The template *creates* the Container Apps
environment, a user-assigned identity, an internal **Redis** app (Celery broker),
an **Azure Files** share for media, a **migration Job**, and three app
containers — **web** (gunicorn), **worker**, **beat** (singleton).

`DATABASE_URL`, the broker URL, `DJANGO_ALLOWED_HOSTS` and `CSRF_TRUSTED_ORIGINS`
are computed inside Bicep — you never hand-write them. Migrations run in the
**Job** (not in the web start command), so **web can scale** past one replica.
Uploaded media persists on the Azure Files share (mounted at `/app/media`).

---

## Prerequisites on the existing resources

- **Database exists** on the Postgres server:
  ```bash
  az postgres flexible-server db create -g <PG_RG> -s <PG_SERVER_NAME> -d eia_dcmt
  ```
- **Postgres reachable from Azure** (Container Apps use Azure egress). If the
  server uses public access, allow Azure services:
  ```bash
  az postgres flexible-server firewall-rule create -g <PG_RG> -n <PG_SERVER_NAME> \
    --rule-name AllowAzureServices --start-ip-address 0.0.0.0 --end-ip-address 0.0.0.0
  ```
  (If the server is VNet-integrated, put the Container Apps environment in a
  peered/whitelisted subnet instead.)

---

## One-time bootstrap (run once; needs an Azure admin)

```bash
# ---- names you choose / already have ----
RG=fieldbase-rg                 # NEW resource group for the ACA env + apps
LOCATION=westeurope
REPO=IITA-Fertilizer-Soil-Health-Hub-WAS/dc_dashboard
BRANCH=redesign/python
ACR_RG=<rg-of-existing-acr>
PG_RG=<rg-of-existing-postgres>

az group create -n "$RG" -l "$LOCATION"

# GitHub OIDC identity (no stored cloud secret)
APP_ID=$(az ad app create --display-name fieldbase-gha --query appId -o tsv)
az ad sp create --id "$APP_ID"
az ad app federated-credential create --id "$APP_ID" --parameters "{
  \"name\":\"redesign-python\",
  \"issuer\":\"https://token.actions.githubusercontent.com\",
  \"subject\":\"repo:${REPO}:ref:refs/heads/${BRANCH}\",
  \"audiences\":[\"api://AzureADTokenExchange\"]
}"

SUB_ID=$(az account show --query id -o tsv)
# Owner on the app RG (creates env/apps/storage/job).
az role assignment create --assignee "$APP_ID" --role Owner \
  --scope "/subscriptions/${SUB_ID}/resourceGroups/${RG}"
# Owner on the ACR's RG (Bicep creates an AcrPull role assignment there).
az role assignment create --assignee "$APP_ID" --role Owner \
  --scope "/subscriptions/${SUB_ID}/resourceGroups/${ACR_RG}"
# Reader on the Postgres RG (Bicep only reads the server FQDN).
az role assignment create --assignee "$APP_ID" --role Reader \
  --scope "/subscriptions/${SUB_ID}/resourceGroups/${PG_RG}"

echo "AZURE_CLIENT_ID=$APP_ID"
echo "AZURE_TENANT_ID=$(az account show --query tenantId -o tsv)"
echo "AZURE_SUBSCRIPTION_ID=$SUB_ID"
```
(If the ACR and Postgres are in the same RG as the app, the extra grants collapse
into the single Owner-on-`$RG` line.)

### GitHub configuration (repo → Settings → Secrets and variables → Actions)

**Secrets** (sensitive):

| Secret | Value |
|---|---|
| `AZURE_CLIENT_ID` / `AZURE_TENANT_ID` / `AZURE_SUBSCRIPTION_ID` | from the bootstrap output |
| `POSTGRES_ADMIN_PASSWORD` | **the existing server's** admin (or app user) password — URL-safe chars |
| `DJANGO_SECRET_KEY` | a fresh 50-char random string |
| `AUTH0_CLIENT_SECRET` | Auth0 app client secret |
| `ONA_TOKEN` | ONA API token |
| `ADMIN_PASSWORD` | first Platform Admin password (used once by `bootstrap_admin`) |

**Variables** (non-secret):

| Variable | Example |
|---|---|
| `AZURE_RG` | `fieldbase-rg` |
| `AZURE_LOCATION` | `westeurope` |
| `ACR_NAME` | existing registry name |
| `ACR_RG` | existing registry's resource group |
| `PG_SERVER_NAME` | existing Postgres server name |
| `PG_RG` | existing Postgres resource group |
| `PG_ADMIN_USER` | Postgres admin/app user |
| `DB_NAME` | `eia_dcmt` |
| `AUTH0_DOMAIN` / `AUTH0_CLIENT_ID` | Auth0 app |
| `ONA_BASE_URL` | `https://api.ona.io` |
| `SITE_NAME` | `Fieldbase` |
| `ADMIN_EMAIL` | first Platform Admin email |

---

## Deploy

Push to `redesign/python` (or Actions → deploy-azure → Run workflow). The run:
1. Builds the image with ACR Tasks (context `backend/`).
2. Applies `infra/main.bicep` (env, identity, Redis, Azure Files, the migration
   Job, and web/worker/beat rolled to the new image).
3. Starts the **migration Job** (`migrate` + `bootstrap_admin`) and waits.
4. Curls `/healthz/`.

The web URL is in the run summary and the Bicep `webUrl` output. After the first
deploy, add it to your Auth0 **Allowed Callback / Logout URLs**, then sign in.

> **Migration ordering:** the Job runs right after the app rollout. Additive
> migrations are safe. For a **risky/renaming** migration, run the Job manually
> first (`az containerapp job start -n fieldbase-migrate -g $RG` on the new image)
> before letting web take the new revision.

## Verify
- Workflow green; the smoke test got `200` from `/healthz/`.
- `az containerapp job execution list -n fieldbase-migrate -g $RG` shows `Succeeded`.
- `az containerapp logs show -n fieldbase-web -g $RG --tail 50` shows gunicorn.
- `fieldbase-beat` logs show the scheduler ticking; `fieldbase-worker` runs tasks.

## Notes
- **Media** is on Azure Files (`/app/media`) — persistent and shared across web
  and worker replicas.
- **Web scales** to `webMaxReplicas` (default 3) because migrations moved to the
  Job. Beat stays a singleton; worker scales 1–2.
- The legacy root `.github/workflows/ci-cd.yml` (R app, `release/*`) is untouched.
