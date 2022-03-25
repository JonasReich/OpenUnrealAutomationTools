using namespace System.Management.Automation

param(
    [String]
    $RootFolder = "",

    [Boolean]
    $UseBuildGraph = $true,

    [Switch]
    $RunTests,

    [Switch]
    $UpdateProjectVersion,

    [Switch]
    $CompileBlueprints,

    [Switch]
    $FixupRedirectors
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
# Return all verbose output, so we don't have to specify it on individual calls
# -> all internal commands from OpenUnrealAutomationTools.psm1 can output verbose logs that actually show up in console.
$global:VerbosePreference = 'continue'
# set to a different color than Yellow so it stands out less and warnings are better recognizable
$Host.PrivateData.VerboseForegroundColor = 'Cyan'

$HasCore7Features = -not ($PSVersionTable.PSEdition -eq "Desktop" -or $PSVersionTable.PSVersion -lt "7.0.0")
if ($HasCore7Features) {
    Write-Warning "This script requires Powershell Core 7 or later for all functionality.
    You are likely still using an old Desktop version that is shipped with Windows (e.g. Windows PowerShell 5.1).
    Please visit https://github.com/PowerShell/PowerShell for more information on PowerShell Core and how to get it."
}

$ScriptDirectory = Split-Path $MyInvocation.MyCommand.Path -Parent
$TimeStamp = Get-Date -Format "yyyy-MM-dd_HH-mm"

$UProjectPath = ""
Import-Module -Name "$ScriptDirectory/../OpenUnrealAutomationTools.psm1" -Verbose -Force

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
    $RootFolder = Resolve-Path $RootFolder
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

$UProject = Open-UEProject $UProjectPath

if ($UseBuildGraph) {
    Write-Output "-------------------------------------------------"
    Write-Output "Compiling Game Project (Build Graph)"
    Write-Output "-------------------------------------------------"
    
    # Compile editor binaries with BuildGraph
    # Buildgraph parameter names that contain colons (e.g. '-set:ProjectName') must be quoted.
    # Otherwise powershell inserts an unwanted space
    Start-UE UAT BuildGraph -script="$ScriptDirectory\Graph.xml" -target="Compile Game Editor" "-Set:ProjectName=`"$ProjectName`"" "-Set:ProjectDir=`"$RootFolder`"" "-Set:BuildConfig=Development"
} else {
    Write-Output "-------------------------------------------------"
    Write-Output "Compiling Game (UBT)"
    Write-Output "-------------------------------------------------"
    
    # Regenerate project files
    Write-UEProjectFiles

    # Compile editor binaries
    $EditorTarget = "$ProjectName"+"Editor"
    Build-UE "$EditorTarget" Development

    # Compile standalone binaries
    Build-UE "$ProjectName" Development
}

if ($RunTests) {
    Write-Output "-------------------------------------------------"
    Write-Output "Run Tests"
    Write-Output "-------------------------------------------------"
    
    # Fill from cmdline?
    $ExtraTests = "OpenUnrealUtilities"
    $TestFilter = "$ProjectName+Project.Functional+$ExtraTests"
    $TestReportPath = "$ScriptDirectory/Saved/TestReport-$TimeStamp"
    
    Start-UETests -TestFilter $TestFilter -ReportExportPath $TestReportPath -Target Game
}

if ($UpdateProjectVersion) {
    Write-Output "-------------------------------------------------"
    Write-Output "Update Project Version SemVer"
    Write-Output "-------------------------------------------------"
    
    $Version = Get-UEProjectVersion
    
    if ($HasCore7Features) {
        [SemanticVersion]$SemVer = $Version

        # This just force writes the semver back to config atm
        # Could be extended to actuallz change the semver, replace it, etc.
        # Powershell 7 Core introduces SemanticVersion class (see above) that allows properly incrementing Minor/Patch components
        Set-UEProjectVersion $SemVer
    } else {
        Write-Output "Skipped because of too low PowerShell version"
    }
}

if ($CompileBlueprints) {
    Write-Output "-------------------------------------------------"
    Write-Output "Blueprint Compile"
    Write-Output "-------------------------------------------------"
    
    # See UCompileAllBlueprintsCommandlet::InitCommandLine for list of additional command line parameters
    Start-UECommandlet CompileAllBlueprints
}

if ($FixupRedirectors) {
    Write-Output "-------------------------------------------------"
    Write-Output "Fixup Redirectors"
    Write-Output "-------------------------------------------------"
    
    # Other flags:
    # -SKIPMAPS, -MAPSONLY -SkipDeveloperFolders -NODEV -OnlyDeveloperFolders
    Start-UECommandlet ResavePackages -fixupredirects -autocheckout -PROJECTONLY
}
