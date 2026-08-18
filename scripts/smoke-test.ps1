<#
.SYNOPSIS
    End-to-end smoke test against a running API.

.DESCRIPTION
    Walks the milestone 1 acceptance criteria against a live server, over real
    HTTP, with no test harness involved:

      1. Two companies sign up independently.
      2. Company A invites a technician, who accepts and joins.
      3. Company B attempts to read and modify Company A's records by ID.
      4. Role restrictions are checked against the API, not the UI.
      5. Audit logs are confirmed separate.

    This is the script to run in front of the client. It prints a pass/fail line
    per check and exits non-zero if anything fails.

.EXAMPLE
    .\scripts\smoke-test.ps1
    .\scripts\smoke-test.ps1 -BaseUrl http://localhost:8000
#>
[CmdletBinding()]
param(
    [string]$BaseUrl = "http://127.0.0.1:8000",
    [string]$ApiPrefix = "/api/v1"
)

$ErrorActionPreference = "Stop"
$script:Failures = 0
$stamp = [guid]::NewGuid().ToString("N").Substring(0, 8)

function Invoke-Api {
    <#  Returns @{ Status = <int>; Body = <object|null> } and never throws on
        a non-2xx response, so the caller can assert on status codes.  #>
    param(
        [string]$Method,
        [string]$Path,
        [object]$Body,
        [string]$Token
    )
    $headers = @{}
    if ($Token) { $headers["Authorization"] = "Bearer $Token" }

    $params = @{
        Uri         = "$BaseUrl$ApiPrefix$Path"
        Method      = $Method
        Headers     = $headers
        ContentType = "application/json"
    }
    if ($null -ne $Body) { $params["Body"] = ($Body | ConvertTo-Json -Depth 6) }

    try {
        $response = Invoke-WebRequest @params -UseBasicParsing
        $parsed = if ($response.Content) { $response.Content | ConvertFrom-Json } else { $null }
        return @{ Status = [int]$response.StatusCode; Body = $parsed }
    }
    catch [System.Net.WebException] {
        $resp = $_.Exception.Response
        if ($null -eq $resp) { throw }
        $status = [int]$resp.StatusCode
        $reader = New-Object System.IO.StreamReader($resp.GetResponseStream())
        $text = $reader.ReadToEnd()
        $parsed = if ($text) { try { $text | ConvertFrom-Json } catch { $text } } else { $null }
        return @{ Status = $status; Body = $parsed }
    }
}

function Assert-That {
    param([string]$Name, [bool]$Condition, [string]$Detail = "")
    if ($Condition) {
        Write-Host ("  PASS  " + $Name) -ForegroundColor Green
    }
    else {
        Write-Host ("  FAIL  " + $Name + $(if ($Detail) { "  ($Detail)" })) -ForegroundColor Red
        $script:Failures++
    }
}

function New-Company {
    param([string]$Name, [string]$Email)
    $result = Invoke-Api -Method POST -Path "/auth/signup" -Body @{
        company_name = $Name
        trade_type   = "hvac"
        timezone     = "America/New_York"
        full_name    = "Owner of $Name"
        email        = $Email
        password     = "correct-horse-battery"
    }
    if ($result.Status -ne 201) {
        throw "signup failed for ${Name}: $($result.Status) $($result.Body | ConvertTo-Json -Compress)"
    }
    return $result.Body
}

Write-Host ""
Write-Host "ServiceLine smoke test -> $BaseUrl" -ForegroundColor Cyan
Write-Host ("=" * 60)

# --------------------------------------------------------------------------
Write-Host ""
Write-Host "1. Health" -ForegroundColor Yellow
$health = Invoke-WebRequest -Uri "$BaseUrl/healthz" -UseBasicParsing
Assert-That "API is up" ($health.StatusCode -eq 200)
$ready = Invoke-WebRequest -Uri "$BaseUrl/readyz" -UseBasicParsing
Assert-That "Database is reachable" ($ready.StatusCode -eq 200)

# --------------------------------------------------------------------------
Write-Host ""
Write-Host "2. Two companies sign up independently" -ForegroundColor Yellow
$a = New-Company -Name "Northline Mechanical $stamp" -Email "dale-$stamp@example.com"
$b = New-Company -Name "Riverside Plumbing $stamp" -Email "riverside-$stamp@example.com"
Assert-That "Company A created" ($null -ne $a.tenant_id)
Assert-That "Company B created" ($null -ne $b.tenant_id)
Assert-That "Companies have distinct tenant ids" ($a.tenant_id -ne $b.tenant_id)

$tenantA = (Invoke-Api -Method GET -Path "/tenants/current" -Token $a.access_token).Body
$tenantB = (Invoke-Api -Method GET -Path "/tenants/current" -Token $b.access_token).Body
Assert-That "A sees only its own company" ($tenantA.name -like "Northline*") $tenantA.name
Assert-That "B sees only its own company" ($tenantB.name -like "Riverside*") $tenantB.name
Assert-That "Trial plan applied with 5 seats" ($tenantA.plan -eq "trial" -and $tenantA.seat_limit -eq 5)

# --------------------------------------------------------------------------
Write-Host ""
Write-Host "3. Invite a technician into company A" -ForegroundColor Yellow
$invite = Invoke-Api -Method POST -Path "/invitations" -Token $a.access_token -Body @{
    email = "mike-$stamp@example.com"; role = "technician"
}
Assert-That "Owner can invite" ($invite.Status -eq 201) "status $($invite.Status)"
$token = ([uri]$invite.Body.accept_url).Query -replace '^\?token=', ''

$preview = Invoke-Api -Method GET -Path "/invitations/preview?token=$token"
Assert-That "Invite preview shows the company" ($preview.Body.tenant_name -like "Northline*")
Assert-That "Invite preview requires signup" ($preview.Body.requires_signup -eq $true)

$accepted = Invoke-Api -Method POST -Path "/invitations/accept" -Body @{
    token = $token; full_name = "Mike Technician"; password = "correct-horse-battery"
}
Assert-That "Technician accepted the invite" ($accepted.Status -eq 200) "status $($accepted.Status)"
Assert-That "Technician is scoped to company A" ($accepted.Body.tenant_id -eq $a.tenant_id)
$techToken = $accepted.Body.access_token

$teamA = Invoke-Api -Method GET -Path "/memberships" -Token $a.access_token
Assert-That "Company A now has 2 members" ($teamA.Body.total -eq 2) "total $($teamA.Body.total)"

$teamB = Invoke-Api -Method GET -Path "/memberships" -Token $b.access_token
Assert-That "Company B still has 1 member" ($teamB.Body.total -eq 1) "total $($teamB.Body.total)"

# --------------------------------------------------------------------------
Write-Host ""
Write-Host "4. Cross-tenant attacks by record ID" -ForegroundColor Yellow
$victimMembership = $teamA.Body.items[0].id

$attack1 = Invoke-Api -Method PATCH -Path "/memberships/$victimMembership" -Token $b.access_token -Body @{ role = "technician" }
Assert-That "B cannot modify A's membership (404)" ($attack1.Status -eq 404) "status $($attack1.Status)"

$attack2 = Invoke-Api -Method POST -Path "/auth/switch-tenant" -Token $b.access_token -Body @{ tenant_id = $a.tenant_id }
Assert-That "B cannot switch into A (403)" ($attack2.Status -eq 403) "status $($attack2.Status)"

$inviteId = $invite.Body.id
$attack3 = Invoke-Api -Method DELETE -Path "/invitations/$inviteId" -Token $b.access_token
Assert-That "B cannot revoke A's invitation (404)" ($attack3.Status -eq 404) "status $($attack3.Status)"

$teamAfter = Invoke-Api -Method GET -Path "/memberships" -Token $a.access_token
Assert-That "A's owner is still an owner" ($teamAfter.Body.items[0].role -eq "owner")

# --------------------------------------------------------------------------
Write-Host ""
Write-Host "5. Role restrictions (server-side, not hidden buttons)" -ForegroundColor Yellow
$techTeam = Invoke-Api -Method GET -Path "/memberships" -Token $techToken
Assert-That "Technician cannot list the team (403)" ($techTeam.Status -eq 403) "status $($techTeam.Status)"

$techInvite = Invoke-Api -Method POST -Path "/invitations" -Token $techToken -Body @{ email = "x-$stamp@example.com"; role = "owner" }
Assert-That "Technician cannot invite (403)" ($techInvite.Status -eq 403) "status $($techInvite.Status)"

$techAudit = Invoke-Api -Method GET -Path "/audit-log" -Token $techToken
Assert-That "Technician cannot read the audit log (403)" ($techAudit.Status -eq 403) "status $($techAudit.Status)"

$techSettings = Invoke-Api -Method PATCH -Path "/tenants/current" -Token $techToken -Body @{ name = "Hijacked" }
Assert-That "Technician cannot rename the company (403)" ($techSettings.Status -eq 403) "status $($techSettings.Status)"

$techOwnCompany = Invoke-Api -Method GET -Path "/tenants/current" -Token $techToken
Assert-That "Technician CAN read their own company (200)" ($techOwnCompany.Status -eq 200)

# --------------------------------------------------------------------------
Write-Host ""
Write-Host "6. Audit trail" -ForegroundColor Yellow
$auditA = (Invoke-Api -Method GET -Path "/audit-log" -Token $a.access_token).Body
$auditB = (Invoke-Api -Method GET -Path "/audit-log" -Token $b.access_token).Body
Assert-That "A's audit log has entries" ($auditA.total -ge 3) "total $($auditA.total)"
Assert-That "B's audit log has only its own signup" ($auditB.total -eq 1) "total $($auditB.total)"

$labelsB = @($auditB.items | ForEach-Object { $_.entity_label })
Assert-That "B's audit log never mentions A" (-not ($labelsB -like "*Northline*"))

$actionsA = @($auditA.items | ForEach-Object { $_.action })
Assert-That "Invite creation is audited" ($actionsA -contains "invitation.created")
Assert-That "Invite acceptance is audited" ($actionsA -contains "invitation.accepted")

# --------------------------------------------------------------------------
Write-Host ""
Write-Host "7. Unauthenticated access" -ForegroundColor Yellow
foreach ($path in @("/tenants/current", "/memberships", "/audit-log", "/invitations")) {
    $anon = Invoke-Api -Method GET -Path $path
    Assert-That "GET $path requires auth (401)" ($anon.Status -eq 401) "status $($anon.Status)"
}

# --------------------------------------------------------------------------
Write-Host ""
Write-Host ("=" * 60)
if ($script:Failures -eq 0) {
    Write-Host "ALL CHECKS PASSED" -ForegroundColor Green
    exit 0
}
else {
    Write-Host "$($script:Failures) CHECK(S) FAILED" -ForegroundColor Red
    exit 1
}
