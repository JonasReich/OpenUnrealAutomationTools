$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$ScriptDirectory = Split-Path $MyInvocation.MyCommand.Path -Parent
Import-Module -Name "$ScriptDirectory/IniContent.psm1" -Force -Verbose:$false

$UEEnvironmentVariables = @(
    "CurrentProjectName",
    "CurrentProjectPath",
    "CurrentProjectDirectory",
    "CurrentUProject",
    "CurrentEngineAssociation",
    "EngineInstallRoot",
    "UEIsInstalledBuild",
    "UEMajorVersion",
    "UEMinorVersion",
    "UEPatchVersion",
    "UEVersion"
)

foreach ($VariableName in $UEEnvironmentVariables) {
    Set-Variable -Name $VariableName -Value $null
}

function Get-UEVersionFilePath {
    return "$EngineInstallRoot\Engine\Build\Build.version"
}

function Assert-UEEnvironment {
    foreach ($VariableName in $UEEnvironmentVariables) {
        if ($null -eq (Get-Variable $VariableName).Value) {
            Write-Error "UE environment variable '$VariableName' not set!`nPlease load a project via Open-UEProject!"
        }
    }
}

$DefaultEmptyMap = "`"/OpenUnrealUtilities/Runtime/EmptyWorld`""
$HeadlessArgs = @("-unattended", "-buildmachine", "-stdout", "-nopause", "-nosplash")

<#
.SYNOPSIS
Opens a UE project and sets the current project and engine path.
.DESCRIPTION
Opens a UE project file, loads the json structure and saves it in a hidden global variable.
This also resolves and caches the engine install root of the project, which is the foundation for many other
functions in the UEBuildTools module that expect the EngineInstallRoot cache to be set.

The function returns a copy of the UProject as object tree so you can retreive metadata from it.
#>
function Open-UEProject {
    param(
        [String]
        $ProjectPath
    )
    Write-Verbose "Opening UE project `"$ProjectPath`""
    $script:CurrentProjectPath = Resolve-Path $ProjectPath
    $script:CurrentProjectName = (Get-Item $CurrentProjectPath).Name -replace ".uproject", ""
    $script:CurrentProjectDirectory = (Get-Item $CurrentProjectPath).Directory

    $script:CurrentUProject = ConvertFrom-Json -InputObject (Get-Content -raw $ProjectPath)
    
    $script:CurrentEngineAssociation = $CurrentUProject.EngineAssociation
    if ($script:CurrentEngineAssociation -eq "") {
        $EngineInstallCheckDir = $script:CurrentProjectDirectory
        while (-not (Test-Path "$EngineInstallCheckDir/Engine") -and -not ($null -eq $EngineInstallCheckDir.Parent)) {
            $EngineInstallCheckDir = $EngineInstallCheckDir.Parent.FullName
        }
        $script:EngineInstallRoot = Resolve-Path -Path "$EngineInstallCheckDir"
    }
    else {
        try {
            $CustomBuildEnginePath = (Get-ItemProperty "Registry::HKEY_CURRENT_USER\SOFTWARE\Epic Games\Unreal Engine\Builds")."$CurrentEngineAssociation"
            Test-Path $CustomBuildEnginePath
            $script:EngineInstallRoot = Resolve-Path $CustomBuildEnginePath
        }
        catch {
            $InstalledEnginePath = (Get-ItemProperty "Registry::HKEY_LOCAL_MACHINE\SOFTWARE\EpicGames\Unreal Engine\$CurrentEngineAssociation" -Name "InstalledDirectory").InstalledDirectory
            $script:EngineInstallRoot = Resolve-Path ($InstalledEnginePath)
        }
    }

    $script:UEIsInstalledBuild = if (Test-Path "$EngineInstallRoot\Engine\Build\InstalledBuild.txt") { $true } else { $false }

    Write-Verbose "Set current UE project to $CurrentProjectName ($CurrentProjectPath)"
    Write-Verbose "Engine association: $CurrentEngineAssociation ($EngineInstallRoot)"

    $EngineVersionFilePath = Get-UEVersionFilePath
    if (Test-Path $EngineVersionFilePath) {
        $EngineVersionFile = ConvertFrom-Json -InputObject (Get-Content -raw $EngineVersionFilePath)
        $script:UEMajorVersion = $EngineVersionFile.MajorVersion
        $script:UEMinorVersion = $EngineVersionFile.MinorVersion
        $script:UEPatchVersion = $EngineVersionFile.PatchVersion
        Write-Verbose "Detected UE Version from Build.version file"
    }
    else {
        Write-Warning "Failed to detect engine version (Build.version file not found). Assuming UE 5.0.0"
        $script:UEMajorVersion = 5
        $script:UEMinorVersion = 0
        $script:UEPatchVersion = 0
    }
    $script:UEVersion = "$UEMajorVersion.$UEMinorVersion.$UEPatchVersion"
    Write-Verbose "Engine Version: $script:UEVersion"

    Assert-UEEnvironment 

    return $CurrentUProject
}

# Programs available in UE Engine that can be started with Start-UE function.
enum UEProgram {
    # UE Automation Tool
    UAT
    # UE Build Tool
    UBT
    # UE Editor
    Editor
    # UE Editor (command line)
    EditorCmd
}

$ProgramPaths_UE4_Legacy = @{
    [UEProgram]::UAT       = "\Engine\Build\BatchFiles\RunUAT.bat"
    [UEProgram]::UBT       = "\Engine\Build\BatchFiles\Build.bat"
    [UEProgram]::Editor    = "\Engine\Binaries\Win64\UE4Editor.exe"
    [UEProgram]::EditorCmd = "\Engine\Binaries\Win64\UE4Editor-Cmd.exe"
}

$ProgramPaths = @{
    [UEProgram]::UAT       = "\Engine\Build\BatchFiles\RunUAT.bat"
    [UEProgram]::UBT       = "\Engine\Build\BatchFiles\Build.bat"
    [UEProgram]::Editor    = "\Engine\Binaries\Win64\UnrealEditor.exe"
    [UEProgram]::EditorCmd = "\Engine\Binaries\Win64\UnrealEditor-Cmd.exe"
}

<#
.SYNOPSIS
    Returns the absolute path to a UE program.
.DESCRIPTION
    Takes an input program code and returns the absolute file path to the program executable inside the current active UE engine directory.
    This function throws an error if you did not previously open a UE project with Open-UEProject.
#>
function Get-UEProgramPath {
    param(
        [Parameter(Mandatory = $true)]
        [UEProgram]
        $Program
    )
    Assert-UEEnvironment
    
    $RelativePath = if ($script:UEMajorVersion -gt 4) { $ProgramPaths[$Program] } else { $ProgramPaths_UE4_Legacy[$Program] }
    Resolve-Path  "$EngineInstallRoot\$RelativePath"
}

<#
.SYNOPSIS
    Recursively expands arrays and generic object lists by flattening them to a simple object array
#>
function Expand-Array {
    param($Arguments)
    $Arguments | ForEach-Object {
        if ($_ -is [array] -or $_ -is [System.Collections.Generic.List[System.Object]]) {
            Expand-Array $_
        }
        else {
            $_
        }
    }
}


<#
.SYNOPSIS
    Regenerate the C++ solution and project files.
.DESCRIPTION
    This command should be executted ahead of any build commands.
    It's not automatically invoked within the build command itself, because regenerating the project files
    is a waste of time if you build multiple targets in a row.
#>
function Write-UEProjectFiles {
    Start-UE UBT -projectfiles -project="$CurrentProjectPath" -game -rocket -progress
}


enum UeBuildTarget {
    Game
    Server
    Client
    Editor
    Program
}

enum UeBuildConfiguration {
    Debug
    DebugGame
    Development
    Shipping
    Test
}

<#
.SYNOPSIS
    Build a UE target using Unreal Build Tool (UBT)
#>
function Start-UEBuild {
    param(
        [Parameter(Mandatory = $true)]
        [String]
        $Target,

        [Parameter(Mandatory = $true)]
        [UeBuildConfiguration]
        $BuildConfigruation,

        [String]
        $Platform = "Win64",

        # Any remaining arguments that should be passed to the UE program
        [parameter(ValueFromRemainingArguments = $true)]
        $RemainingArguments
    )
    Assert-UEEnvironment

    $UBT_BuildConfiguration_Args = @{
        [UeBuildConfiguration]::Debug       = "Debug"
        [UeBuildConfiguration]::DebugGame   = "DebugGame"
        [UeBuildConfiguration]::Development = "Development"
        [UeBuildConfiguration]::Shipping    = "Shipping"
        [UeBuildConfiguration]::Test        = "Test"
    }

    $BuildConfigurationArg = $UBT_BuildConfiguration_Args[$BuildConfigruation]
    $EditorArgs = if ($Target -eq [UeBuildTarget]::Editor) { "-editorrecompile" } else { "" }

    Start-UE UBT $Target $BuildConfigurationArg $Platform "-project=`"$CurrentProjectPath`"" -NoHotReloadFromIDE -progress -noubtmakefiles -utf8output $EditorArgs $RemainingArguments
}


<#
.SYNOPSIS
    Starts an UE program with arbitrary command-line arguments.
.DESCRIPTION
    Takes an input program code and runs the program executable inside the current active UE engine directory.
    This function throws an error if you did not previously open a UE project with Open-UEProject.
#>
function Start-UE {
    param(
        [Parameter(Mandatory = $true)]
        [UEProgram]
        $Program,

        # Any remaining arguments that should be passed to the UE program
        [parameter(ValueFromRemainingArguments = $true)]
        $RemainingArguments
    )
    Assert-UEEnvironment
    $ProgramPath = Get-UEProgramPath -Program $Program
    $ExpandedArgs = Expand-Array $RemainingArguments
    Write-Verbose "Starting UE $Program with the following command-line:`n$ProgramPath $ExpandedArgs"
    &"$ProgramPath" $ExpandedArgs
    if (-not $LASTEXITCODE -eq 0) {
        Write-Error "`"$ProgramPath`" exited with code $LASTEXITCODE"
    }
}

# Target configurations for running unit tests. Either in game or editor mode.
enum UeTestTarget {
    # Run Game tests
    Game
    # Run Editor tests
    Editor
}

function Start-UETests {
    param(
        [Parameter(Mandatory = $true)]
        [String]
        $TestFilter,

        [Parameter(Mandatory = $true)]
        [String]
        $ReportExportPath,

        [Parameter(Mandatory = $true)]
        [UeTestTarget]
        $Target,

        # Any remaining arguments that should be passed to the UE program
        [parameter(ValueFromRemainingArguments = $true)]
        $RemainingArguments
    )
    Assert-UEEnvironment
    $TargetArg = if ($Target -eq [UeTestTarget]::Game) { @("-game", "-gametest") } else { @("-editor", "-editortest") }
    $RunTestCmdArg = "-ExecCmds=`"Automation RunTests Now $TestFilter;Quit`""
    $ReportArg = "-ReportExportPath=`"$ReportExportPath`""

    Start-UE EditorCmd $CurrentProjectPath $DefaultEmptyMap $TargetArg $HeadlessArgs "-nullrhi" $RunTestCmdArg $ReportArg $RemainingArguments

    # Delete everything but the json from the test results.
    $ReportFiles = Get-ChildItem $ReportExportPath
    foreach ($File in $ReportFiles) {
        if ($File.Name.EndsWith(".json")) { continue; }
        Remove-Item $File.FullName
    }
    
    # Copy over our customized test report viewer template
    Copy-Item -Path "$ScriptDirectory\TestReportViewer_Template\*" -Destination "$ReportExportPath\" -Recurse
}


<#
.SYNOPSIS
    Starts a UE commandlet with arbitrary command-line arguments.
.DESCRIPTION
    This function throws an error if you did not previously open a UE project with Open-UEProject.
#>

function Start-UECommandlet {
    param(
        [Parameter(Mandatory = $true)]
        [String]
        $CommandletName,

        [String]
        $TargetMap = $DefaultEmptyMap,

        [switch]
        $AllowCommandletRendering,

        # Any remaining arguments that should be passed to the UE program
        [parameter(ValueFromRemainingArguments = $true)]
        $RemainingArguments
    )
    Assert-UEEnvironment
    $RHIArg = if ($AllowCommandletRendering) { "-AllowCommandletRendering" } else { "-nullrhi" }
    Start-UE EditorCmd $CurrentProjectPath $TargetMap $HeadlessArgs $RHIArg "-run=$CommandletName" $RemainingArguments
}

function Get-UEConfigPath {
    param(
        [parameter(Mandatory = $true)] [string] $ConfigName,
        [bool] $Saved,
        [string] $SavedPlatform = "Windows"
    )
    Assert-UEEnvironment
    if ($Saved) {
        return Resolve-Path "$CurrentProjectDirectory/Saved/Config/$SavedPlatform/$ConfigName.ini"
    }
    else {
        return Resolve-Path "$CurrentProjectDirectory/Config/Default$ConfigName.ini"
    }
}

function Get-UEConfig {
    param(
        [parameter(Mandatory = $true)] [string] $ConfigName,
        [switch] $Saved,
        [string] $SavedPlatform = "Windows"
    )
    $IniPath = Get-UEConfigPath -ConfigName $ConfigName -Saved $Saved -SavedPlatform $SavedPlatform
    Get-IniContent -Path $IniPath
}

function Set-UEConfig {
    [cmdletbinding()]
    param (
        [parameter(ValueFromPipeline)] [hashtable] $Data,
        [parameter(Mandatory = $true)] [string] $ConfigName,
        [switch] $Saved,
        [string] $SavedPlatform = "Windows"
    )
    $IniPath = Get-UEConfigPath -ConfigName $ConfigName -Saved $Saved -SavedPlatform $SavedPlatform
    $Data | Set-IniContent -Path $IniPath
}

function Set-UEConfigValue {
    [cmdletbinding()]
    param (
        [parameter(ValueFromPipeline)] [string] $Value,
        [parameter(Mandatory = $true)] [string] $ConfigName,
        [parameter(Mandatory = $true)] [string] $Key,
        [parameter(Mandatory = $true)] [string] $Section,
        [switch] $Saved,
        [string] $SavedPlatform = "Windows"
    )

    $IniPath = Get-UEConfigPath -ConfigName $ConfigName -Saved $Saved -SavedPlatform $SavedPlatform
    $Value | Set-IniValue -Path $IniPath -Key $Key -Section $Section
}

function Get-UEEngineVersion {

}

function Get-UEProjectVersion {
    param([parameter()] [string] $FallbackVersion = "0.1.0")

    $GeneralProjectSettings = (Get-UEConfig "Game")."/Script/EngineSettings.GeneralProjectSettings"
    if ($GeneralProjectSettings.ContainsKey("ProjectVersion")) {
        return $GeneralProjectSettings.ProjectVersion
    }
    else {
        return "$FallbackVersion"
    }
}

function Set-UEProjectVersion {
    param([parameter(Mandatory = $true)] [string] $Version)
    $Version | Set-UEConfigValue -ConfigName "Game" -Key "ProjectVersion" -Section "/Script/EngineSettings.GeneralProjectSettings"
}

Export-ModuleMember -Verbose:$false -Function Open-UEProject, Get-UEProgramPath, Write-UEProjectFiles, Start-UEBuild, Start-UE, Start-UETests, Start-UECommandlet, Get-UEConfig, Set-UEConfig, Set-UEConfigValue, Get-UEProjectVersion, Set-UEProjectVersion
foreach ($VariableName in $UEEnvironmentVariables) {
    Export-ModuleMember  -Verbose:$false -Variable $VariableName
}
