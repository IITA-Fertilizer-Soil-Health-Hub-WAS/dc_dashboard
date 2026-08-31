// Azure Container Apps stack for the Fieldbase Django backend (eia_dcmt).
// Uses an EXISTING Azure Container Registry and an EXISTING Postgres Flexible
// Server; creates the Container Apps environment, an internal Redis app, Azure
// Files-backed media, a migration Job, and the three processes (web/worker/beat).
// Apply:
//   az deployment group create -g <appRG> -f infra/main.bicep -p imageTag=<sha> ...
// Wiring (DATABASE_URL, broker URL, allowed hosts, CSRF origins) is computed here.

// ---------- Parameters ----------
@description('Azure region for the resources this template creates.')
param location string = resourceGroup().location

@description('Short prefix for resource names (letters/numbers).')
param namePrefix string = 'fieldbase'

@description('Container image tag to deploy (usually the git SHA).')
param imageTag string

@description('Image repository name inside the ACR.')
param imageName string = 'dc-dashboard'

// Existing Azure Container Registry
@description('Name of the EXISTING Azure Container Registry.')
param acrName string
@description('Resource group of the existing ACR (defaults to this deployment RG).')
param acrResourceGroup string = resourceGroup().name

// Existing Postgres Flexible Server
@description('Name of the EXISTING Postgres Flexible Server.')
param pgServerName string
@description('Resource group of the existing Postgres server (defaults to this RG).')
param pgResourceGroup string = resourceGroup().name
@description('Postgres admin (or app) user for the connection string.')
param pgAdminUser string
@description('Postgres password. URL-safe chars — it is embedded in DATABASE_URL.')
@secure()
param pgAdminPassword string
@description('Database name on the existing server (must already exist).')
param dbName string = 'eia_dcmt'

// App config (non-secret)
@description('Custom domain bound to the web app (added to ALLOWED_HOSTS + CSRF).')
param customDomain string = ''
@description('Name of the env managed certificate for the custom domain (SNI bind).')
param managedCertName string = ''
param auth0Domain string = ''
param auth0ClientId string = ''
param onaBaseUrl string = ''
param siteName string = 'Fieldbase'
param adminEmail string = ''
@description('Max web replicas. Web can scale now that migrations run in a Job.')
param webMaxReplicas int = 2

// App config (secret)
@secure()
param djangoSecretKey string
@secure()
param auth0ClientSecret string = ''
@secure()
param onaToken string = ''
@secure()
param adminPassword string = ''

// ---------- Names ----------
var envName = '${namePrefix}-env'
var webAppName = '${namePrefix}-web'
var workerAppName = '${namePrefix}-worker'
var beatAppName = '${namePrefix}-beat'
var redisAppName = '${namePrefix}-redis'
var migrateJobName = '${namePrefix}-migrate'
var uamiName = '${namePrefix}-pull-id'
var storageAccountName = toLower(take('${namePrefix}st${uniqueString(resourceGroup().id)}', 24))

// ---------- Existing resources ----------
resource acr 'Microsoft.ContainerRegistry/registries@2023-07-01' existing = {
  name: acrName
  scope: resourceGroup(acrResourceGroup)
}

resource pg 'Microsoft.DBforPostgreSQL/flexibleServers@2023-06-01-preview' existing = {
  name: pgServerName
  scope: resourceGroup(pgResourceGroup)
}

var acrImage = '${acr.properties.loginServer}/${imageName}:${imageTag}'

// ---------- Observability ----------
resource logs 'Microsoft.OperationalInsights/workspaces@2022-10-01' = {
  name: '${namePrefix}-logs'
  location: location
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: 30
  }
}

// ---------- Pull identity ----------
// Created out-of-band (with AcrPull on the existing registry already granted) so
// this template needs no write access to the shared ACR resource group.
resource uami 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' existing = {
  name: uamiName
}

// ---------- Media storage (Azure Files) ----------
resource storage 'Microsoft.Storage/storageAccounts@2023-01-01' = {
  name: storageAccountName
  location: location
  sku: { name: 'Standard_LRS' }
  kind: 'StorageV2'
  properties: {
    minimumTlsVersion: 'TLS1_2'
    allowBlobPublicAccess: false
  }
}

resource fileService 'Microsoft.Storage/storageAccounts/fileServices@2023-01-01' = {
  parent: storage
  name: 'default'
}

resource mediaShare 'Microsoft.Storage/storageAccounts/fileServices/shares@2023-01-01' = {
  parent: fileService
  name: 'media'
  properties: {
    shareQuota: 100
    enabledProtocols: 'SMB'
  }
}

// ---------- Container Apps environment ----------
resource env 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: envName
  location: location
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logs.properties.customerId
        sharedKey: logs.listKeys().primarySharedKey
      }
    }
  }
}

// Register the file share with the environment so apps can mount it.
resource envStorage 'Microsoft.App/managedEnvironments/storages@2024-03-01' = {
  parent: env
  name: 'media'
  properties: {
    azureFile: {
      accountName: storage.name
      accountKey: storage.listKeys().keys[0].value
      shareName: mediaShare.name
      accessMode: 'ReadWrite'
    }
  }
}

// ---------- Computed wiring ----------
var envDomain = env.properties.defaultDomain
var webFqdn = '${webAppName}.${envDomain}'
var redisFqdn = '${redisAppName}.internal.${envDomain}'
// The custom domain, when set, is added to allowed hosts + CSRF trusted origins.
var allowedHosts = empty(customDomain) ? '${webFqdn},localhost,127.0.0.1' : '${customDomain},${webFqdn},localhost,127.0.0.1'
var csrfOrigins = empty(customDomain) ? 'https://${webFqdn}' : 'https://${customDomain},https://${webFqdn}'
// Bind the custom domain in the app's ingress (referencing the env managed cert)
// so redeploys keep the SNI binding instead of wiping a manually-added one.
var bindCustomDomain = !empty(customDomain) && !empty(managedCertName)
var webIngress = union(
  { external: true, transport: 'auto', targetPort: 8000, allowInsecure: false },
  bindCustomDomain ? {
    customDomains: [
      {
        name: customDomain
        bindingType: 'SniEnabled'
        certificateId: resourceId('Microsoft.App/managedEnvironments/managedCertificates', envName, managedCertName)
      }
    ]
  } : {}
)
var databaseUrl = 'postgres://${pgAdminUser}:${pgAdminPassword}@${pg.properties.fullyQualifiedDomainName}:5432/${dbName}?sslmode=require'

// ACA rejects a secret whose value is empty, so optional secrets are only
// created when a value is supplied; otherwise the env var is passed empty.
var sharedSecrets = concat(
  [
    { name: 'database-url', value: databaseUrl }
    { name: 'django-secret-key', value: djangoSecretKey }
  ],
  empty(auth0ClientSecret) ? [] : [ { name: 'auth0-client-secret', value: auth0ClientSecret } ],
  empty(onaToken) ? [] : [ { name: 'ona-token', value: onaToken } ],
  empty(adminPassword) ? [] : [ { name: 'admin-password', value: adminPassword } ]
)

var sharedEnv = concat(
  [
    { name: 'DJANGO_SETTINGS_MODULE', value: 'eia_dcmt.settings.prod' }
    { name: 'DJANGO_DEBUG', value: 'false' }
    { name: 'DJANGO_ALLOWED_HOSTS', value: allowedHosts }
    { name: 'DJANGO_CSRF_TRUSTED_ORIGINS', value: csrfOrigins }
    { name: 'CELERY_BROKER_URL', value: 'redis://${redisFqdn}:6379/0' }
    { name: 'CELERY_RESULT_BACKEND', value: 'redis://${redisFqdn}:6379/1' }
    { name: 'AUTH0_DOMAIN', value: auth0Domain }
    { name: 'AUTH0_CLIENT_ID', value: auth0ClientId }
    { name: 'ONA_BASE_URL', value: onaBaseUrl }
    { name: 'SITE_NAME', value: siteName }
    { name: 'ADMIN_EMAIL', value: adminEmail }
    { name: 'DATABASE_URL', secretRef: 'database-url' }
    { name: 'DJANGO_SECRET_KEY', secretRef: 'django-secret-key' }
  ],
  [ empty(auth0ClientSecret) ? { name: 'AUTH0_CLIENT_SECRET', value: '' } : { name: 'AUTH0_CLIENT_SECRET', secretRef: 'auth0-client-secret' } ],
  [ empty(onaToken) ? { name: 'ONA_TOKEN', value: '' } : { name: 'ONA_TOKEN', secretRef: 'ona-token' } ],
  [ empty(adminPassword) ? { name: 'ADMIN_PASSWORD', value: '' } : { name: 'ADMIN_PASSWORD', secretRef: 'admin-password' } ]
)

var appIdentity = {
  type: 'UserAssigned'
  userAssignedIdentities: { '${uami.id}': {} }
}
var appRegistries = [
  { server: acr.properties.loginServer, identity: uami.id }
]
// Mount the Azure Files share at Django's MEDIA_ROOT (/app/media).
var mediaVolumes = [
  { name: 'media', storageType: 'AzureFile', storageName: envStorage.name }
]
var mediaMounts = [
  { volumeName: 'media', mountPath: '/app/media' }
]
// Probes hit the pod IP over HTTP, so spoof the ingress Host (for ALLOWED_HOSTS)
// and mark the request secure (prod forces SECURE_SSL_REDIRECT) — else /healthz
// returns 400/301 and the replica is killed as unhealthy.
var probeHeaders = [
  { name: 'Host', value: webFqdn }
  { name: 'X-Forwarded-Proto', value: 'https' }
]

// ---------- Migration Job (runs migrate + bootstrap_admin, decoupled from web) ----------
resource migrateJob 'Microsoft.App/jobs@2024-03-01' = {
  name: migrateJobName
  location: location
  identity: appIdentity
  properties: {
    environmentId: env.id
    configuration: {
      triggerType: 'Manual'
      replicaTimeout: 1800
      replicaRetryLimit: 1
      manualTriggerConfig: { parallelism: 1, replicaCompletionCount: 1 }
      secrets: sharedSecrets
      registries: appRegistries
    }
    template: {
      containers: [
        {
          name: 'migrate'
          image: acrImage
          resources: { cpu: json('0.5'), memory: '1Gi' }
          command: [ '/bin/sh', '-c', 'python manage.py migrate --noinput && python manage.py bootstrap_admin' ]
          env: sharedEnv
        }
      ]
    }
  }
}

// ---------- On-demand ONA sync Job (start with: az containerapp job start) ----------
resource syncJob 'Microsoft.App/jobs@2024-03-01' = {
  name: '${namePrefix}-sync'
  location: location
  identity: appIdentity
  properties: {
    environmentId: env.id
    configuration: {
      triggerType: 'Manual'
      replicaTimeout: 3600
      replicaRetryLimit: 0
      manualTriggerConfig: { parallelism: 1, replicaCompletionCount: 1 }
      secrets: sharedSecrets
      registries: appRegistries
    }
    template: {
      containers: [
        {
          name: 'sync'
          image: acrImage
          resources: { cpu: json('0.5'), memory: '1Gi' }
          command: [ '/bin/sh', '-c', 'python manage.py sync_project --all' ]
          env: sharedEnv
        }
      ]
    }
  }
}

// ---------- Redis (internal broker) ----------
resource redisApp 'Microsoft.App/containerApps@2024-03-01' = {
  name: redisAppName
  location: location
  properties: {
    managedEnvironmentId: env.id
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: { external: false, transport: 'tcp', targetPort: 6379, exposedPort: 6379 }
    }
    template: {
      containers: [
        { name: 'redis', image: 'redis:7', resources: { cpu: json('0.25'), memory: '0.5Gi' } }
      ]
      scale: { minReplicas: 1, maxReplicas: 1 }
    }
  }
}

// ---------- Web (gunicorn; migrations now run in the Job, so it can scale) ----------
resource webApp 'Microsoft.App/containerApps@2024-03-01' = {
  name: webAppName
  location: location
  identity: appIdentity
  dependsOn: [ redisApp ]
  properties: {
    managedEnvironmentId: env.id
    configuration: {
      activeRevisionsMode: 'Single'
      secrets: sharedSecrets
      registries: appRegistries
      ingress: webIngress
    }
    template: {
      volumes: mediaVolumes
      containers: [
        {
          name: 'web'
          image: acrImage
          resources: { cpu: json('0.25'), memory: '0.5Gi' }
          // No command override — the image CMD is gunicorn. Migrations run in the Job.
          env: sharedEnv
          volumeMounts: mediaMounts
          probes: [
            { type: 'Startup', httpGet: { path: '/healthz/', port: 8000, httpHeaders: probeHeaders }, periodSeconds: 5, failureThreshold: 20, timeoutSeconds: 5 }
            { type: 'Readiness', httpGet: { path: '/healthz/', port: 8000, httpHeaders: probeHeaders }, periodSeconds: 15, failureThreshold: 3, timeoutSeconds: 5 }
            { type: 'Liveness', httpGet: { path: '/healthz/', port: 8000, httpHeaders: probeHeaders }, periodSeconds: 30, failureThreshold: 5, timeoutSeconds: 5 }
          ]
        }
      ]
      scale: { minReplicas: 1, maxReplicas: webMaxReplicas }
    }
  }
}

// ---------- Celery worker ----------
resource workerApp 'Microsoft.App/containerApps@2024-03-01' = {
  name: workerAppName
  location: location
  identity: appIdentity
  dependsOn: [ redisApp ]
  properties: {
    managedEnvironmentId: env.id
    configuration: {
      activeRevisionsMode: 'Single'
      secrets: sharedSecrets
      registries: appRegistries
    }
    template: {
      volumes: mediaVolumes
      containers: [
        {
          name: 'worker'
          image: acrImage
          resources: { cpu: json('0.25'), memory: '0.5Gi' }
          command: [ 'celery', '-A', 'eia_dcmt', 'worker', '-l', 'info', '--concurrency', '2' ]
          env: sharedEnv
          volumeMounts: mediaMounts
        }
      ]
      scale: { minReplicas: 1, maxReplicas: 1 }
    }
  }
}

// ---------- Celery beat (singleton scheduler) ----------
resource beatApp 'Microsoft.App/containerApps@2024-03-01' = {
  name: beatAppName
  location: location
  identity: appIdentity
  dependsOn: [ redisApp ]
  properties: {
    managedEnvironmentId: env.id
    configuration: {
      activeRevisionsMode: 'Single'
      secrets: sharedSecrets
      registries: appRegistries
    }
    template: {
      containers: [
        {
          name: 'beat'
          image: acrImage
          resources: { cpu: json('0.25'), memory: '0.5Gi' }
          command: [ 'celery', '-A', 'eia_dcmt', 'beat', '-l', 'info', '--scheduler', 'django_celery_beat.schedulers:DatabaseScheduler' ]
          env: sharedEnv
        }
      ]
      // Beat must be a singleton — exactly one scheduler.
      scale: { minReplicas: 1, maxReplicas: 1 }
    }
  }
}

// ---------- Outputs ----------
output webUrl string = 'https://${webApp.properties.configuration.ingress.fqdn}'
output migrateJobName string = migrateJob.name
output syncJobName string = syncJob.name
output acrLoginServer string = acr.properties.loginServer
