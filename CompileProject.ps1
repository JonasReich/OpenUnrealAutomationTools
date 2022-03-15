using namespace System.Management.Automation

param(
    [Boolean]
    $UseBuildGraph = $true,

    [String]
    $Rootfolder = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if ($PSVersionTable.PSEdition -eq "Desktop" -or $PSVersionTable.PSVersion -lt "7.0.0") {
    Write-Error "This script requires Powershell Core 7 or later.
    You are likely still using an old Desktop version that is shipped with Windows (e.g. Windows PowerShell 5.1).
    Please visit https://github.com/PowerShell/PowerShell for more information on PowerShell Core and how to get it."
}

$ScriptDirectory = Split-Path $MyInvocation.MyCommand.Path -Parent
if ($Rootfolder -eq "") {
    $Rootfolder = Resolve-Path "$ScriptDirectory/.."
}

Import-Module -Name "$ScriptDirectory/Ue4BuildTools.psm1" -Verbose -Force

$UProjectSearchPath = "$Rootfolder/*.uproject"
Write-Output "Searching for UE4 project files in $UProjectSearchPath"
$UProjectPath = Resolve-Path $UProjectSearchPath
Write-Output "Resolved path as $UProjectPath"
if ($UProjectPath -match "(?<ProjectName>[a-zA-Z0-9]+).uproject") {
    $ProjectName = $Matches["ProjectName"]
} else {
    Write-Error "Project name not found in uproject file path '$UProjectPath'"
}

$UProject = Open-Ue4Project $UProjectPath

if ($UseBuildGraph) {
    # Compile editor binaries with BuildGraph
    Start-Ue4 UAT BuildGraph -script="$ScriptDirectory\Graph.xml" -target="Compile Game Editor" -set:ProjectName=$ProjectName -Set:ProjectDir="$ScriptDirectory" -Set:BuildConfig=Development
} else {
    # Regenerate project files
    Start-Ue4 UBT -projectfiles -project="$UProjectPath" -game -rocket -progress

    # Compile editor and standalone binaries via UBT
    $EditorTargetName = $ProjectName+"Editor"
    Start-Ue4 UBT "$EditorTargetName" "Development" "Win64" -project="$UProjectPath" -NoHotReloadFromIDE -editorrecompile -progress -noubtmakefiles -utf8output
    Start-Ue4 UBT "$ProjectName" "Development" "Win64" -project="$UProjectPath" -NoHotReloadFromIDE -editorrecompile -progress -noubtmakefiles -utf8output
}

# Launch editor with tests
$EditorTestArgs = @("-editor", "-editortest")
$HeadlessArgs = @("-unattended", "-buildmachine", "-stdout", "-nullrhi", "-nopause", "-nosplash" )

$ExtraTests = "OpenUnrealUtilities" # Fill from cmdline?
$TestFilter = "$ProjectName+Project.Functional+$ExtraTests"

$RunTestCmdArg = "-ExecCmds=`"Automation RunTests Now $TestFilter;Quit`""
$TestTimestamp = Get-Date -Format "yyyy-MM-dd-HH-mm"
$TestReportPath = "$ScriptDirectory/TestReport-$TestTimestamp"
Write-Output "Executing automation tests..."

Start-Ue4 EditorCmd "$UProjectPath" $EditorTestArgs $RunTestCmdArg $HeadlessArgs -ReportExportPath="$TestReportPath"

$Version = Get-Ue4ProjectVersion
if ($Version -eq "") {
    $Version = "0.1.0"
}
[SemanticVersion]$SemVer = $Version
$SemVer
#Set-Ue4ProjectVersion $SemVer.


