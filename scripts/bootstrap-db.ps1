<#
.SYNOPSIS
    One-time database bootstrap: creates the two roles and the two databases.

.DESCRIPTION
    Run this once against a fresh PostgreSQL instance, as a superuser. Migrations
    do NOT create roles, because roles are cluster-level objects while migrations
    are database-level -- mixing them makes migrations non-portable between
    environments.

    Two roles are created on purpose:

      serviceline_owner  Owns the tables. Alembic connects as this role.
      serviceline_app    The API's runtime role. Owns nothing, has no DDL
                         rights, and crucially is NOT the table owner -- a table
                         owner bypasses row-level security by default. This role
                         plus FORCE ROW LEVEL SECURITY on every tenant-scoped
                         table are the two independent reasons the application
                         cannot escape its tenant.

    Idempotent: safe to re-run.

.EXAMPLE
    .\scripts\bootstrap-db.ps1
    .\scripts\bootstrap-db.ps1 -SuperPassword "mypassword" -PgBin "C:\Program Files\PostgreSQL\17\bin"
#>
[CmdletBinding()]
param(
    [string]$PgBin = "C:\Program Files\PostgreSQL\17\bin",
    [string]$PgHost = "localhost",
    [int]$Port = 5432,
    [string]$SuperUser = "postgres",
    [string]$SuperPassword = $env:PGSUPERPASSWORD,
    [string]$OwnerPassword = "owner_dev_2026",
    [string]$AppPassword = "app_dev_2026"
)

$ErrorActionPreference = "Stop"

$psql = Join-Path $PgBin "psql.exe"
if (-not (Test-Path $psql)) {
    throw "psql not found at $psql. Pass -PgBin pointing at your PostgreSQL bin directory."
}
if (-not $SuperPassword) {
    throw "Provide -SuperPassword or set the PGSUPERPASSWORD environment variable."
}

$env:PGPASSWORD = $SuperPassword

function Invoke-Psql {
    param([string]$Database = "postgres", [string]$Sql)
    $out = & $psql -U $SuperUser -h $PgHost -p $Port -d $Database -v ON_ERROR_STOP=1 -t -A -c $Sql
    if ($LASTEXITCODE -ne 0) { throw "psql failed: $Sql`n$out" }
    # A query that matches no rows yields $null, not an empty string. Join so
    # callers can always treat the result as a string.
    return (($out | Where-Object { $_ -ne $null }) -join "`n")
}

Write-Host "== Creating roles ==" -ForegroundColor Cyan
$roleSql = @"
DO `$`$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'serviceline_owner') THEN
        CREATE ROLE serviceline_owner LOGIN PASSWORD '$OwnerPassword'
            NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
        RAISE NOTICE 'created role serviceline_owner';
    ELSE
        ALTER ROLE serviceline_owner PASSWORD '$OwnerPassword';
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'serviceline_app') THEN
        CREATE ROLE serviceline_app LOGIN PASSWORD '$AppPassword'
            NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
        RAISE NOTICE 'created role serviceline_app';
    ELSE
        ALTER ROLE serviceline_app PASSWORD '$AppPassword';
    END IF;
END
`$`$;
"@
Invoke-Psql -Sql $roleSql | Out-Null

# Belt and braces: assert the app role really cannot bypass RLS. If someone
# ever "fixes" a permissions problem by granting BYPASSRLS, this fails loudly.
$bypass = (Invoke-Psql -Sql "SELECT rolbypassrls OR rolsuper FROM pg_roles WHERE rolname='serviceline_app';").Trim()
if ($bypass -ne "f") {
    throw "serviceline_app has BYPASSRLS or SUPERUSER. Tenant isolation would be void. Aborting."
}
Write-Host "   serviceline_app verified: no SUPERUSER, no BYPASSRLS" -ForegroundColor Green

Write-Host "== Creating databases ==" -ForegroundColor Cyan
foreach ($db in @("serviceline", "serviceline_test")) {
    $exists = (Invoke-Psql -Sql "SELECT 1 FROM pg_database WHERE datname = '$db';").Trim()
    if ($exists -eq "1") {
        Write-Host "   $db already exists"
    }
    else {
        Invoke-Psql -Sql "CREATE DATABASE $db OWNER serviceline_owner ENCODING 'UTF8';" | Out-Null
        Write-Host "   created $db" -ForegroundColor Green
    }
    # The app role connects but must never create objects.
    Invoke-Psql -Database $db -Sql "REVOKE CREATE ON SCHEMA public FROM PUBLIC;" | Out-Null
    Invoke-Psql -Database $db -Sql "GRANT CONNECT ON DATABASE $db TO serviceline_app;" | Out-Null
}

Write-Host ""
Write-Host "Bootstrap complete." -ForegroundColor Green
Write-Host "  serviceline_owner -> migrations (DATABASE_ADMIN_URL)"
Write-Host "  serviceline_app   -> runtime    (DATABASE_URL)"
