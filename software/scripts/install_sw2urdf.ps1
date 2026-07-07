# scripts/install_sw2urdf.ps1 — one-time setup: install the SW2URDF SolidWorks add-in.
# Run this in an ADMINISTRATOR PowerShell (it needs elevation for COM registration and
# writing to Program Files). See .claude/skills/cad-import/SKILL.md for the full
# SolidWorks -> URDF -> ArmConfig workflow this feeds into.
#
# Source: https://github.com/ros/solidworks_urdf_exporter (ROS-Industrial's official
# SolidWorks-to-URDF exporter). Minimum SolidWorks version is 2018 SP5; the installer
# below is the latest published release (v1.6.1, labelled "for SolidWorks 2021") — it
# has historically stayed COM-compatible with newer SolidWorks versions, but if it fails
# to load as an add-in after install, check that repo's Releases/Issues for a newer build.

$ErrorActionPreference = "Stop"

$isAdmin = ([Security.Principal.WindowsIdentity]::GetCurrent().Groups -contains "S-1-5-32-544")
if (-not $isAdmin) {
    Write-Error "Not running as Administrator. Right-click PowerShell -> Run as administrator, then re-run this script."
    exit 1
}

$url = "https://github.com/ros/solidworks_urdf_exporter/releases/download/1.6.1/sw2urdfSetup.exe"
$dest = Join-Path $env:TEMP "sw2urdfSetup.exe"

Write-Host "Downloading SW2URDF installer from $url ..."
Invoke-WebRequest -Uri $url -OutFile $dest

Write-Host "Launching installer (follow its wizard; it registers a SolidWorks COM add-in) ..."
Start-Process -FilePath $dest -Wait

Write-Host ""
Write-Host "Done. Next steps:" -ForegroundColor Green
Write-Host "  1. Open SolidWorks -> Tools menu should now show 'Export as URDF' (or 'Configuration Publisher')."
Write-Host "  2. If it's not there, enable it: Tools > Add-Ins > check 'SW2URDF Exporter', then re-check the Tools menu."
Write-Host "  3. Open 'Inhabit arm for software.SLDASM' and run the export wizard -- base link first, end effector last."
Write-Host "     Full conventions (axis, limits, joint order): .claude/skills/cad-import/SKILL.md"
