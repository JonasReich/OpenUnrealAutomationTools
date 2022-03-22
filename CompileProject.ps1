using namespace System.Management.Automation

param(
    [Boolean]
    $UseBuildGraph = $true,

    [String]
    $RootFolder = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$HasCore7Features = $PSVersionTable.PSEdition -eq "Desktop" -or $PSVersionTable.PSVersion -lt "7.0.0"
if ($HasCore7Features) {
    Write-Warning "This script requires Powershell Core 7 or later for all functionality.
    You are likely still using an old Desktop version that is shipped with Windows (e.g. Windows PowerShell 5.1).
    Please visit https://github.com/PowerShell/PowerShell for more information on PowerShell Core and how to get it."
}

$ScriptDirectory = Split-Path $MyInvocation.MyCommand.Path -Parent
$UProjectPath = ""
Import-Module -Name "$ScriptDirectory/Ue4BuildTools.psm1" -Verbose -Force

if ([string]::IsNullOrEmpty($RootFolder)) {
    $RootFolder = Resolve-Path "$ScriptDirectory/.."
    $UProjectPath = Resolve-Path "$RootFolder/*.uproject"
    while ([string]::IsNullOrEmpty($UProjectPath)) {
        
        $ParentDirectory = (Get-Item $RootFolder).Parent
        if ($ParentDirectory -eq $null) {
            $UProjectPath = ""
            break;
        }
        $RootFolder = $ParentDirectory.FullName
    }
} else {
    $UProjectPath = Resolve-Path "$RootFolder/*.uproject"
}

if ([string]::IsNullOrEmpty($UProjectPath)) {
    Write-Error "No uproject found!"
}

Write-Output "Resolved uproject path as '$UProjectPath'"

if ($UProjectPath -match "(?<ProjectName>[a-zA-Z0-9]+).uproject") {
    $ProjectName = $Matches["ProjectName"]
} else {
    Write-Error "Project name not found in uproject file path '$UProjectPath'"
}

$UProject = Open-Ue4Project $UProjectPath

Write-Output "-------------------------------------------------"
Write-Output "Compiling Game Project"
Write-Output "-------------------------------------------------"

if ($UseBuildGraph) {
    # Compile editor binaries with BuildGraph
    # Buildgraph parameter names that contain colons (e.g. '-set:ProjectName') must be quoted.
    # Otherwise powershell inserts an unwanted space
    Start-Ue4 UAT BuildGraph -script="$ScriptDirectory\Graph.xml" -target="Compile Game Editor" "-Set:ProjectName=`"$ProjectName`"" "-Set:ProjectDir=`"$RootFolder`"" "-Set:BuildConfig=Development"
} else {
    # Regenerate project files
    Start-Ue4 UBT -projectfiles -project="$UProjectPath" -game -rocket -progress

    # Compile editor and standalone binaries via UBT
    $EditorTargetName = $ProjectName+"Editor"
    Start-Ue4 UBT "$EditorTargetName" "Development" "Win64" -project="$UProjectPath" -NoHotReloadFromIDE -editorrecompile -progress -noubtmakefiles -utf8output
    Start-Ue4 UBT "$ProjectName" "Development" "Win64" -project="$UProjectPath" -NoHotReloadFromIDE -editorrecompile -progress -noubtmakefiles -utf8output
}

Write-Output "-------------------------------------------------"
Write-Output "Run Tests"
Write-Output "-------------------------------------------------"

# Launch UE4 with tests
$EditorTests = $true
$TestArgs = If ($EditorTests) { @("-editor", "-editortest") } else { @("-game", "-gametest") }
$HeadlessArgs = @("-unattended", "-buildmachine", "-stdout", "-nullrhi", "-nopause", "-nosplash" )

$ExtraTests = "OpenUnrealUtilities" # Fill from cmdline?
$TestFilter = "$ProjectName+Project.Functional+$ExtraTests"

$RunTestCmdArg = "-ExecCmds=`"Automation RunTests Now $TestFilter;Quit`""
$TestTimestamp = Get-Date -Format "yyyy-MM-dd-HH-mm"
$TestReportPath = "$ScriptDirectory/TestReport-$TestTimestamp"
Write-Output "Executing automation tests..."

$TestMap = "/Engine/Maps/Entry"

Start-Ue4 EditorCmd "$UProjectPath" "$TestMap" $TestArgs $RunTestCmdArg $HeadlessArgs -ReportExportPath="$TestReportPath"

$Version = Get-Ue4ProjectVersion

if ($HasCore7Features) {
    [SemanticVersion]$SemVer = $Version
    $SemVer
}
#Set-Ue4ProjectVersion $SemVer.


