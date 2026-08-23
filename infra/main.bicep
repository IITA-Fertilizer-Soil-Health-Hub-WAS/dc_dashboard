// Azure Container Apps stack for the Fieldbase Django backend (eia_dcmt).
// One idempotent template: registry, Container Apps environment, Postgres,
// an internal Redis app, and the three long-running processes (web / worker /
// beat). Apply with:
//   az deployment group create -g <rg> -f infra/main.bicep -p imageTag=<sha> ...
// Wiring (DATABASE_URL, broker URL, allowed hosts, CSRF origins) is computed
// here so the operator never hand-crafts a connection string.

// ---------- Parameters ----------
@description('Azure region for all resources.')
param location string = resourceGroup().location

@description('Short prefix for resource names (letters/numbers).')
param namePrefix string = 'fieldbase'

@description('Globally-unique ACR name (alphanumeric, 5-50 chars).')
param acrName string

@description('Container image tag to deploy (usually the git SHA).')
param imageTag string

@description('Image repository name inside the ACR.')
param imageName string = 'dc-dashboard'

// Postgres
param postgresAdminUser string = 'fieldbase'
@description('Postgres admin password. Use URL-safe characters (alphanumeric) — it is embedded in DATABASE_URL.')
@secure()
param postgresAdminPassword string
param dbName string = 'eia_dcmt'

// App config (non-secret)
param auth0Domain string = ''
param auth0ClientId string = ''
param onaBaseUrl string = ''
param siteName string = 'Fieldbase'
param adminEmail string = ''

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
var pgServerName = '${namePrefix}-pg-${uniqueString(resourceGroup().id)}'
var uamiName = '${namePrefix}-pull-id'
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

// ---------- Registry + pull identity ----------
resource acr 'Microsoft.ContainerRegistry/registries@2023-07-01' = {
  name: acrName
  location: location
  sku: { name: 'Basic' }
  properties: { adminUserEnabled: false }
}

resource uami 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: uamiName
  location: location
}

// AcrPull for the user-assigned identity (created before the apps, so the very
// first image pull already has permission — avoids the MI/pull chicken-and-egg).
resource acrPull 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(acr.id, uami.id, 'AcrPull')
  scope: acr
  properties: {
    principalId: uami.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '7f951dda-4ed3-4680-a7ca-43fe172d538d')
  }
}

// ---------- Postgres ----------
resource pg 'Microsoft.DBforPostgreSQL/flexibleServers@2023-06-01-preview' = {
  name: pgServerName
  location: location
  sku: { name: 'Standard_B1ms', tier: 'Burstable' }
  properties: {
    version: '16'
    administratorLogin: postgresAdminUser
    administratorLoginPassword: postgresAdminPassword
    storage: { storageSizeGB: 32 }
    backup: { backupRetentionDays: 7, geoRedundantBackup: 'Disabled' }
    highAvailability: { mode: 'Disabled' }
  }
}

resource pgDb 'Microsoft.DBforPostgreSQL/flexibleServers/databases@2023-06-01-preview' = {
  parent: pg
  name: dbName
  properties: { charset: 'UTF8', collation: 'en_US.utf8' }
}

// Allow other Azure services (the Container Apps) to reach the server.
resource pgAllowAzure 'Microsoft.DBforPostgreSQL/flexibleServers/firewallRules@2023-06-01-preview' = {
  parent: pg
  name: 'AllowAzureServices'
  properties: { startIpAddress: '0.0.0.0', endIpAddress: '0.0.0.0' }
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

// ---------- Computed wiring ----------
var envDomain = env.properties.defaultDomain
var webFqdn = '${webAppName}.${envDomain}'
var redisFqdn = '${redisAppName}.internal.${envDomain}'
var databaseUrl = 'postgres://${postgresAdminUser}:${postgresAdminPassword}@${pg.properties.fullyQualifiedDomainName}:5432/${dbName}?sslmode=require'

var sharedSecrets = [
  { name: 'database-url', value: databaseUrl }
  { name: 'django-secret-key', value: djangoSecretKey }
  { name: 'auth0-client-secret', value: auth0ClientSecret }
  { name: 'ona-token', value: onaToken }
  { name: 'admin-password', value: adminPassword }
]

var sharedEnv = [
  { name: 'DJANGO_SETTINGS_MODULE', value: 'eia_dcmt.settings.prod' }
  { name: 'DJANGO_DEBUG', value: 'false' }
  { name: 'DJANGO_ALLOWED_HOSTS', value: '${webFqdn},localhost,127.0.0.1' }
  { name: 'DJANGO_CSRF_TRUSTED_ORIGINS', value: 'https://${webFqdn}' }
  { name: 'CELERY_BROKER_URL', value: 'redis://${redisFqdn}:6379/0' }
  { name: 'CELERY_RESULT_BACKEND', value: 'redis://${redisFqdn}:6379/1' }
  { name: 'AUTH0_DOMAIN', value: auth0Domain }
  { name: 'AUTH0_CLIENT_ID', value: auth0ClientId }
  { name: 'ONA_BASE_URL', value: onaBaseUrl }
  { name: 'SITE_NAME', value: siteName }
  { name: 'ADMIN_EMAIL', value: adminEmail }
  { name: 'DATABASE_URL', secretRef: 'database-url' }
  { name: 'DJANGO_SECRET_KEY', secretRef: 'django-secret-key' }
  { name: 'AUTH0_CLIENT_SECRET', secretRef: 'auth0-client-secret' }
  { name: 'ONA_TOKEN', secretRef: 'ona-token' }
  { name: 'ADMIN_PASSWORD', secretRef: 'admin-password' }
]

var appIdentity = {
  type: 'UserAssigned'
  userAssignedIdentities: { '${uami.id}': {} }
}
var appRegistries = [
  { server: acr.properties.loginServer, identity: uami.id }
]

// ---------- Redis (internal broker) ----------
resource redisApp 'Microsoft.App/containerApps@2024-03-01' = {
  name: redisAppName
  location: location
  properties: {
    managedEnvironmentId: env.id
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: {
        external: false
        transport: 'tcp'
        targetPort: 6379
        exposedPort: 6379
      }
    }
    template: {
      containers: [
        {
          name: 'redis'
          image: 'redis:7'
          resources: { cpu: json('0.25'), memory: '0.5Gi' }
        }
      ]
      scale: { minReplicas: 1, maxReplicas: 1 }
    }
  }
}

// ---------- Web (gunicorn) ----------
resource webApp 'Microsoft.App/containerApps@2024-03-01' = {
  name: webAppName
  location: location
  identity: appIdentity
  dependsOn: [ acrPull, pgDb, pgAllowAzure, redisApp ]
  properties: {
    managedEnvironmentId: env.id
    configuration: {
      activeRevisionsMode: 'Single'
      secrets: sharedSecrets
      registries: appRegistries
      ingress: {
        external: true
        transport: 'auto'
        targetPort: 8000
        allowInsecure: false
      }
    }
    template: {
      containers: [
        {
          name: 'web'
          image: acrImage
          resources: { cpu: json('0.5'), memory: '1Gi' }
          command: [
            '/bin/sh'
            '-c'
            'python manage.py migrate --noinput && python manage.py bootstrap_admin && gunicorn eia_dcmt.wsgi:application --bind 0.0.0.0:8000 --worker-class gthread --workers 2 --threads 4 --timeout 120 --worker-tmp-dir /dev/shm'
          ]
          env: sharedEnv
          probes: [
            // Generous startup budget so migrations on a fresh revision finish
            // before gunicorn binds (5 min: 30 x 10s).
            { type: 'Startup', httpGet: { path: '/healthz/', port: 8000 }, periodSeconds: 10, failureThreshold: 30, timeoutSeconds: 5 }
            { type: 'Readiness', httpGet: { path: '/healthz/', port: 8000 }, periodSeconds: 15, failureThreshold: 3, timeoutSeconds: 5 }
            { type: 'Liveness', httpGet: { path: '/healthz/', port: 8000 }, periodSeconds: 30, failureThreshold: 5, timeoutSeconds: 5 }
          ]
        }
      ]
      // Single replica: migrate runs in the container command, so keep one
      // writer. Move migrate to a Container Apps Job to scale web past 1.
      scale: { minReplicas: 1, maxReplicas: 1 }
    }
  }
}

// ---------- Celery worker ----------
resource workerApp 'Microsoft.App/containerApps@2024-03-01' = {
  name: workerAppName
  location: location
  identity: appIdentity
  dependsOn: [ acrPull, pgDb, redisApp ]
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
          name: 'worker'
          image: acrImage
          resources: { cpu: json('0.5'), memory: '1Gi' }
          command: [ 'celery', '-A', 'eia_dcmt', 'worker', '-l', 'info' ]
          env: sharedEnv
        }
      ]
      scale: { minReplicas: 1, maxReplicas: 2 }
    }
  }
}

// ---------- Celery beat (singleton scheduler) ----------
resource beatApp 'Microsoft.App/containerApps@2024-03-01' = {
  name: beatAppName
  location: location
  identity: appIdentity
  dependsOn: [ acrPull, pgDb, redisApp ]
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
output acrLoginServer string = acr.properties.loginServer
output postgresFqdn string = pg.properties.fullyQualifiedDomainName
