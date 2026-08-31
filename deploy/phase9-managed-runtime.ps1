[CmdletBinding()]
param(
    [string]$Project = "enterprise-changeops",
    [string]$Region = "us-central1",
    [Parameter(Mandatory = $true)][ValidatePattern('^[a-zA-Z0-9._-]+$')][string]$Tag
)

$ErrorActionPreference = "Stop"
$ProjectNumber = (gcloud projects describe $Project --format="value(projectNumber)").Trim()
$Registry = "$Region-docker.pkg.dev/$Project/changeops"
$ServiceDomain = "$Project.iam.gserviceaccount.com"
$VerificationAccount = "changeops-verification@$ServiceDomain"
$OrchestratorAccount = "changeops-orchestrator@$ServiceDomain"

function Invoke-Gcloud {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments)
    Write-Host ("gcloud " + ($Arguments -join " "))
    & gcloud --quiet @Arguments
    if ($LASTEXITCODE -ne 0) { throw "gcloud command failed with exit code $LASTEXITCODE" }
}

function Test-GcloudResource {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments)
    $previousPreference = $ErrorActionPreference
    $ErrorActionPreference = "SilentlyContinue"
    & gcloud --quiet @Arguments *> $null
    $exists = $LASTEXITCODE -eq 0
    $ErrorActionPreference = $previousPreference
    return $exists
}

function Get-ServiceUrl([string]$Name) {
    $url = (& gcloud run services describe $Name --project $Project --region $Region --format="value(status.url)").Trim()
    if ($LASTEXITCODE -ne 0 -or -not $url) { throw "Cloud Run service $Name has no URL." }
    return $url
}

function Ensure-ServiceAccount([string]$Name, [string]$DisplayName) {
    if (-not (Test-GcloudResource iam service-accounts describe "$Name@$ServiceDomain" --project $Project)) {
        Invoke-Gcloud iam service-accounts create $Name --project $Project --display-name $DisplayName
    }
}

function Ensure-Secret([string]$Name) {
    if (-not (Test-GcloudResource secrets describe $Name --project $Project)) {
        Invoke-Gcloud secrets create $Name --project $Project --replication-policy automatic
    }
    $versionOutput = & gcloud --quiet secrets versions list $Name --project $Project `
        --filter="state:ENABLED" --limit=1 --format="value(name)"
    if ($LASTEXITCODE -ne 0) { throw "Failed to inspect versions for secret $Name." }
    $enabledVersion = if ($null -eq $versionOutput) { "" } else { "$versionOutput".Trim() }
    if ($enabledVersion) { return }
    $bytes = New-Object byte[] 48
    $generator = [Security.Cryptography.RandomNumberGenerator]::Create()
    try { $generator.GetBytes($bytes) } finally { $generator.Dispose() }
    $value = [Convert]::ToBase64String($bytes)
    $secretFile = [IO.Path]::GetTempFileName()
    try {
        [IO.File]::WriteAllText($secretFile, $value, [Text.UTF8Encoding]::new($false))
        $previousPreference = $ErrorActionPreference
        $ErrorActionPreference = "SilentlyContinue"
        & gcloud --quiet secrets versions add $Name --project $Project --data-file=$secretFile *> $null
        $versionExitCode = $LASTEXITCODE
        $ErrorActionPreference = $previousPreference
    }
    finally {
        Remove-Item -LiteralPath $secretFile -Force -ErrorAction SilentlyContinue
    }
    if ($versionExitCode -ne 0) { throw "Failed to add an initial version for secret $Name." }
    Write-Host "Added a generated version to $Name (value redacted)."
}

function Grant-ProjectRole([string]$Member, [string]$Role) {
    Invoke-Gcloud projects add-iam-policy-binding $Project --member $Member --role $Role --condition=None | Out-Null
}

function Grant-SecretAccess([string]$Secret, [string]$Account) {
    Invoke-Gcloud secrets add-iam-policy-binding $Secret --project $Project `
        --member "serviceAccount:$Account" --role roles/secretmanager.secretAccessor --condition=None | Out-Null
}

function Grant-Invoker([string]$Service, [string]$Member) {
    Invoke-Gcloud run services add-iam-policy-binding $Service --project $Project --region $Region `
        --member $Member --role roles/run.invoker --condition=None | Out-Null
}

function Deploy-Service {
    param(
        [string]$Name,
        [string]$Image,
        [string]$Account,
        [int]$Port,
        [string]$Environment,
        [int]$Minimum = 0,
        [int]$Maximum = 2,
        [string]$Secrets = "",
        [switch]$AlwaysAllocated
    )
    $arguments = @(
        "run", "deploy", $Name, "--project", $Project, "--region", $Region,
        "--image", "$Registry/$Image`:$Tag", "--service-account", $Account,
        "--port", "$Port", "--execution-environment", "gen2", "--cpu", "1",
        "--memory", "512Mi", "--concurrency", "20", "--timeout", "120",
        "--min", "$Minimum", "--max", "$Maximum", "--no-allow-unauthenticated",
        "--labels", "application=enterprise-changeops,environment=managed-sandbox",
        "--set-env-vars", $Environment
    )
    if ($Secrets) { $arguments += @("--set-secrets", $Secrets) }
    if ($AlwaysAllocated) { $arguments += "--no-cpu-throttling" }
    Invoke-Gcloud @arguments
}

Invoke-Gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com `
    iamcredentials.googleapis.com secretmanager.googleapis.com firestore.googleapis.com pubsub.googleapis.com `
    --project $Project

foreach ($account in @(
    @{ Name = "changeops-control-tower"; Display = "ChangeOps Control Tower" },
    @{ Name = "changeops-control-api"; Display = "ChangeOps Control API" },
    @{ Name = "changeops-event-gateway"; Display = "ChangeOps Event Gateway" },
    @{ Name = "changeops-tool-gateway"; Display = "ChangeOps Tool Gateway" },
    @{ Name = "changeops-workflow"; Display = "ChangeOps Workflow Coordinator" },
    @{ Name = "changeops-catalog-sandbox"; Display = "ChangeOps Catalog Sandbox" },
    @{ Name = "changeops-crm-sandbox"; Display = "ChangeOps CRM Sandbox" },
    @{ Name = "changeops-analytics-sandbox"; Display = "ChangeOps Analytics Sandbox" },
    @{ Name = "changeops-support-sandbox"; Display = "ChangeOps Support Sandbox" }
)) { Ensure-ServiceAccount $account.Name $account.Display }

$controlTowerAccount = "changeops-control-tower@$ServiceDomain"
$controlApiAccount = "changeops-control-api@$ServiceDomain"
$eventAccount = "changeops-event-gateway@$ServiceDomain"
$toolAccount = "changeops-tool-gateway@$ServiceDomain"
$workflowAccount = "changeops-workflow@$ServiceDomain"

foreach ($secret in @("changeops-tool-auth", "changeops-event-webhook", "changeops-workflow-callback")) {
    Ensure-Secret $secret
}
Grant-SecretAccess changeops-tool-auth $controlTowerAccount
Grant-SecretAccess changeops-tool-auth $toolAccount
Grant-SecretAccess changeops-tool-auth $workflowAccount
Grant-SecretAccess changeops-event-webhook $controlTowerAccount
Grant-SecretAccess changeops-event-webhook $eventAccount
Grant-SecretAccess changeops-workflow-callback $toolAccount
Grant-SecretAccess changeops-workflow-callback $workflowAccount

if (-not (Test-GcloudResource firestore databases describe --database="(default)" --project $Project)) {
    Invoke-Gcloud firestore databases create --database="(default)" --project $Project `
        --location $Region --type firestore-native --delete-protection
}

foreach ($topic in @("changeops-change-events", "changeops-change-events-dlq")) {
    if (-not (Test-GcloudResource pubsub topics describe $topic --project $Project)) {
        Invoke-Gcloud pubsub topics create $topic --project $Project
    }
}
if (-not (Test-GcloudResource pubsub subscriptions describe changeops-workflow-coordinator --project $Project)) {
    Invoke-Gcloud pubsub subscriptions create changeops-workflow-coordinator --project $Project `
        --topic changeops-change-events --ack-deadline 60 --min-retry-delay 1s --max-retry-delay 10s `
        --dead-letter-topic changeops-change-events-dlq --max-delivery-attempts 5
}
if (-not (Test-GcloudResource pubsub subscriptions describe changeops-change-events-dlq-inspection --project $Project)) {
    Invoke-Gcloud pubsub subscriptions create changeops-change-events-dlq-inspection --project $Project `
        --topic changeops-change-events-dlq --ack-deadline 30
}

Grant-ProjectRole "serviceAccount:$controlApiAccount" roles/datastore.user
Grant-ProjectRole "serviceAccount:$eventAccount" roles/datastore.user
Grant-ProjectRole "serviceAccount:$eventAccount" roles/pubsub.publisher
Grant-ProjectRole "serviceAccount:$toolAccount" roles/datastore.user
Grant-ProjectRole "serviceAccount:$workflowAccount" roles/datastore.user
Grant-ProjectRole "serviceAccount:$workflowAccount" roles/pubsub.subscriber
Grant-ProjectRole "serviceAccount:$workflowAccount" roles/pubsub.publisher
$pubsubReaderRole = "projects/$Project/roles/changeopsPubSubRuntimeReader"
if (-not (Test-GcloudResource iam roles describe changeopsPubSubRuntimeReader --project $Project)) {
    Invoke-Gcloud iam roles create changeopsPubSubRuntimeReader --project $Project `
        --title "ChangeOps PubSub Runtime Reader" `
        --description "Readiness metadata for pre-created ChangeOps PubSub resources" `
        --permissions "pubsub.subscriptions.get,pubsub.topics.get" --stage GA
}
Grant-ProjectRole "serviceAccount:$eventAccount" $pubsubReaderRole
Grant-ProjectRole "serviceAccount:$workflowAccount" $pubsubReaderRole
$pubsubAgent = "service-$ProjectNumber@gcp-sa-pubsub.iam.gserviceaccount.com"
Grant-ProjectRole "serviceAccount:$pubsubAgent" roles/pubsub.publisher
Grant-ProjectRole "serviceAccount:$pubsubAgent" roles/pubsub.subscriber

$baseEnvironment = "APP_ENV=sandbox,APP_REGION=$Region,PRODUCTION_WRITES_ENABLED=false"
$firestoreEnvironment = "$baseEnvironment,PERSISTENCE_BACKEND=firestore,GOOGLE_CLOUD_PROJECT=$Project,FIRESTORE_DATABASE=(default)"

Deploy-Service changeops-control-api control-api $controlApiAccount 8000 $firestoreEnvironment
Deploy-Service changeops-catalog-sandbox catalog-sandbox "changeops-catalog-sandbox@$ServiceDomain" 8080 $baseEnvironment 1 1
Deploy-Service changeops-crm-sandbox crm-sandbox "changeops-crm-sandbox@$ServiceDomain" 8080 $baseEnvironment 1 1
Deploy-Service changeops-analytics-sandbox analytics-sandbox "changeops-analytics-sandbox@$ServiceDomain" 8080 $baseEnvironment 1 1
Deploy-Service changeops-support-sandbox support-sandbox "changeops-support-sandbox@$ServiceDomain" 8080 $baseEnvironment 1 1

$controlUrl = Get-ServiceUrl changeops-control-api
$catalogUrl = Get-ServiceUrl changeops-catalog-sandbox
$crmUrl = Get-ServiceUrl changeops-crm-sandbox
$analyticsUrl = Get-ServiceUrl changeops-analytics-sandbox
$supportUrl = Get-ServiceUrl changeops-support-sandbox
$sandboxUrls = "CATALOG_BASE_URL=$catalogUrl,CRM_BASE_URL=$crmUrl,ANALYTICS_BASE_URL=$analyticsUrl,SUPPORT_BASE_URL=$supportUrl"

Invoke-Gcloud run deploy changeops-agent-fleet --project $Project --region $Region `
    --image "$Registry/agent-fleet`:$Tag" --service-account $OrchestratorAccount --port 8200 `
    --execution-environment gen2 --cpu 1 --memory 1Gi --concurrency 20 --timeout 120 --min 0 --max 2 `
    --no-allow-unauthenticated --labels "application=enterprise-changeops,environment=managed-sandbox" `
    --update-env-vars "SERVICE_AUTH_MODE=google_cloud,$sandboxUrls"
$agentUrl = Get-ServiceUrl changeops-agent-fleet

$expectedToolUrl = "https://changeops-tool-gateway-$ProjectNumber.$Region.run.app"
$workflowEnvironment = "$firestoreEnvironment,SERVICE_AUTH_MODE=google_cloud,PUBSUB_MANAGE_RESOURCES=false,AUTH_AUDIENCE=enterprise-changeops-tool-gateway,AGENT_FLEET_BASE_URL=$agentUrl,TOOL_GATEWAY_BASE_URL=$expectedToolUrl,$sandboxUrls"
Deploy-Service changeops-workflow-coordinator workflow-coordinator $workflowAccount 8500 $workflowEnvironment 1 1 `
    "TOOL_GATEWAY_AUTH_SECRET=changeops-tool-auth:latest,WORKFLOW_CALLBACK_SECRET=changeops-workflow-callback:latest" -AlwaysAllocated
$workflowUrl = Get-ServiceUrl changeops-workflow-coordinator

$toolEnvironment = "$firestoreEnvironment,SERVICE_AUTH_MODE=google_cloud,WORKFLOW_CALLBACK_URL=$workflowUrl/internal/v1/approval-callbacks,$sandboxUrls,AUTH_AUDIENCE=enterprise-changeops-tool-gateway"
Deploy-Service changeops-tool-gateway tool-gateway $toolAccount 8300 $toolEnvironment 0 2 `
    "TOOL_GATEWAY_AUTH_SECRET=changeops-tool-auth:latest,WORKFLOW_CALLBACK_SECRET=changeops-workflow-callback:latest"
$toolUrl = Get-ServiceUrl changeops-tool-gateway

Invoke-Gcloud run services update changeops-workflow-coordinator --project $Project --region $Region `
    --update-env-vars "TOOL_GATEWAY_BASE_URL=$toolUrl"

$eventEnvironment = "$firestoreEnvironment,PUBSUB_MANAGE_RESOURCES=false,CONTROL_API_BASE_URL=$controlUrl"
Deploy-Service changeops-event-gateway event-gateway $eventAccount 8400 $eventEnvironment 1 2 `
    "EVENT_GATEWAY_WEBHOOK_SECRET=changeops-event-webhook:latest"
$eventUrl = Get-ServiceUrl changeops-event-gateway

$towerEnvironment = "$baseEnvironment,SERVICE_AUTH_MODE=google_cloud,CONTROL_TOWER_ENVIRONMENT=sandbox,CONTROL_TOWER_SANDBOX_ACTIONS_ENABLED=true,DEMO_TENANT_ID=tenant-managed-verification,AUTH_AUDIENCE=enterprise-changeops-tool-gateway,CONTROL_API_BASE_URL=$controlUrl,AGENT_FLEET_BASE_URL=$agentUrl,TOOL_GATEWAY_BASE_URL=$toolUrl,EVENT_GATEWAY_BASE_URL=$eventUrl,WORKFLOW_COORDINATOR_BASE_URL=$workflowUrl"
Deploy-Service changeops-control-tower control-tower $controlTowerAccount 3000 $towerEnvironment 0 2 `
    "TOOL_GATEWAY_AUTH_SECRET=changeops-tool-auth:latest,EVENT_GATEWAY_WEBHOOK_SECRET=changeops-event-webhook:latest"

foreach ($service in @("changeops-catalog-sandbox", "changeops-crm-sandbox", "changeops-analytics-sandbox", "changeops-support-sandbox")) {
    Grant-Invoker $service "serviceAccount:$OrchestratorAccount"
    Grant-Invoker $service "serviceAccount:$workflowAccount"
}
foreach ($service in @("changeops-crm-sandbox", "changeops-analytics-sandbox", "changeops-support-sandbox")) {
    Grant-Invoker $service "serviceAccount:$toolAccount"
}
foreach ($service in @("changeops-control-api", "changeops-agent-fleet", "changeops-event-gateway", "changeops-tool-gateway", "changeops-workflow-coordinator")) {
    Grant-Invoker $service "serviceAccount:$controlTowerAccount"
}
Grant-Invoker changeops-agent-fleet "serviceAccount:$workflowAccount"
Grant-Invoker changeops-tool-gateway "serviceAccount:$workflowAccount"
Grant-Invoker changeops-workflow-coordinator "serviceAccount:$toolAccount"
foreach ($service in @(
    "changeops-control-tower", "changeops-control-api", "changeops-agent-fleet", "changeops-event-gateway",
    "changeops-tool-gateway", "changeops-workflow-coordinator", "changeops-catalog-sandbox",
    "changeops-crm-sandbox", "changeops-analytics-sandbox", "changeops-support-sandbox"
)) { Grant-Invoker $service "serviceAccount:$VerificationAccount" }

$operator = (& gcloud config get-value account).Trim()
Invoke-Gcloud iam service-accounts add-iam-policy-binding $VerificationAccount --project $Project `
    --member "user:$operator" --role roles/iam.serviceAccountTokenCreator --condition=None | Out-Null
Grant-Invoker changeops-control-tower "user:$operator"

Write-Host "Phase 9 private managed runtime deployed."
Write-Host "Open it with: gcloud run services proxy changeops-control-tower --project $Project --region $Region --port 3000"
