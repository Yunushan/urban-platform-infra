Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if (-not (Get-Command choco -ErrorAction SilentlyContinue)) {
  Write-Host "Install Chocolatey first: https://chocolatey.org/install"
  exit 1
}
choco install -y git python kubernetes-cli kubernetes-helm make jq shellcheck openssh
Write-Host "Run 'make setup-local' and 'make doctor-local' from the repository after prerequisites install."
Write-Host "Use WSL2 or a Linux operator host for Ansible cluster mutation, RKE2 bootstrap, and Helm deploy workflows."
