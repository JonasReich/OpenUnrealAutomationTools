$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$ScriptDirectory = Split-Path $MyInvocation.MyCommand.Path -Parent
Import-Module -Name "$ScriptDirectory/IniContent.psm1" -Force -Verbose

$Ue4EnvironmentVariables = @(
    "CurrentProjectName",
    "CurrentProjectPath",
    "CurrentProjectDirectory",
    "CurrentUProject",
    "CurrentEngineAssociation",
    "EngineInstallRoot"
)

foreach ($VariableName in $Ue4EnvironmentVariables) {
    Set-Variable -Name $VariableName -Value $null
}

function Assert-Ue4Environment {
    foreach ($VariableName in $Ue4EnvironmentVariables) {
        if ($null -eq (Get-Variable $VariableName).Value) {
            Write-Error "UE4 environment variable '$VariableName' not set!`nPlease load a project via Open-Ue4Project!"
        }
    }
}

<#
.SYNOPSIS
Opens a UE4 project and sets the current project and engine path.
.DESCRIPTION
Opens a UE4 project file, loads the json structure and saves it in a hidden global variable.
This also resolves and caches the engine install root of the project, which is the foundation for many other
functions in the UE4BuildTools module that expect the EngineInstallRoot cache to be set.

The function returns a copy of the UProject as object tree so you can retreive metadata from it.
#>
function Open-Ue4Project {
    param(
        [String]
        $ProjectPath
    )
    $script:CurrentProjectPath = Resolve-Path $ProjectPath
    $script:CurrentProjectName = (Get-Item $CurrentProjectPath).Name -replace ".uproject", ""
    $script:CurrentProjectDirectory = (Get-Item $CurrentProjectPath).Directory

    $script:CurrentUProject = ConvertFrom-Json -InputObject (Get-Content -raw $ProjectPath)
    
    $script:CurrentEngineAssociation = $CurrentUProject.EngineAssociation
    $CustomBuildEnginePath = (Get-ItemProperty "Registry::HKEY_CURRENT_USER\SOFTWARE\Epic Games\Unreal Engine\Builds")."$CurrentEngineAssociation"
    if (Test-Path $CustomBuildEnginePath) {
        $script:EngineInstallRoot = Resolve-Path $CustomBuildEnginePath
    } else {
        $InstalledEnginePath = (Get-ItemProperty "Registry::HKEY_LOCAL_MACHINE\SOFTWARE\EpicGames\Unreal Engine\$CurrentEngineAssociation" -Name "InstalledDirectory").InstalledDirectory
        $script:EngineInstallRoot = Resolve-Path ($InstalledEnginePath)
    }

    Write-Host "Set current UE4 project to $CurrentProjectName ($CurrentProjectPath)"
    Write-Host "Engine association: $CurrentEngineAssociation ($EngineInstallRoot)"

    Assert-Ue4Environment
    
    return $CurrentUProject
}

# Programs available in Unreal Engine that can be started with Start-Ue4 function.
enum Ue4Program {
    # Unreal Automation Tool
    UAT
    # Unreal Build Tool
    UBT
    # Unreal Editor
    Editor
    # Unreal Editor (command line)
    EditorCmd
}

$ProgramPaths = @{
    [Ue4Program]::UAT = "\Engine\Build\BatchFiles\RunUAT.bat"
    [Ue4Program]::UBT = "\Engine\Build\BatchFiles\Build.bat"
    [Ue4Program]::Editor = "\Engine\Binaries\Win64\UE4Editor.exe"
    [Ue4Program]::EditorCmd = "\Engine\Binaries\Win64\UE4Editor-Cmd.exe"
}

<#
.SYNOPSIS
    Returns the absolute path to a UE4 program.
.DESCRIPTION
    Takes an input program code and returns the absolute file path to the program executable inside the current active UE4 engine directory.
    This function throws an error if you did not previously open a UE4 project with Open-Ue4Project.
#>
function Get-Ue4ProgramPath {
    param(
        [Parameter(Mandatory=$true)]
        [Ue4Program]
        $Program
    )
    Assert-Ue4Environment
    $RelativePath = $ProgramPaths[$Program]
    Resolve-Path  "$EngineInstallRoot\$RelativePath"
}

<#
.SYNOPSIS
    Recursively expands arrays and generic object lists by flattening them to a simple object array
#>
function Expand-Array{
    param($Arguments)
    $Arguments | ForEach-Object{
        if ($_ -is [array] -or $_ -is [System.Collections.Generic.List[System.Object]]) {
            Expand-Array $_
        } else {
            $_
        }
    }
}

<#
.SYNOPSIS
    Starts an UE4 program with arbitrary command-line arguments.
.DESCRIPTION
    Takes an input program code and runs the program executable inside the current active UE4 engine directory.
    This function throws an error if you did not previously open a UE4 project with Open-Ue4Project.
#>
function Start-Ue4 {
    param(
        [Parameter(Mandatory=$true)]
        [Ue4Program]
        $Program,

        # Any remaining arguments that should be passed to the UE4 program
        [parameter(ValueFromRemainingArguments = $true)]
        $Arguments,

        [switch]
        $SkipDefaultArguments
    )
    Assert-Ue4Environment
    $ProgramPath = Get-Ue4ProgramPath -Program $Program
    $ExpandedArgs = Expand-Array $Arguments
    Write-Host "Starting UE4 $Program with the following command-line:`n$ProgramPath $ExpandedArgs"
    &"$ProgramPath" $ExpandedArgs
    if (-not $LASTEXITCODE -eq 0) {
        Write-Error "`"$ProgramPath`" exited with code $LASTEXITCODE"
    }
}

function Get-Ue4ConfigPath {
    param(
        [parameter(Mandatory = $true)] [string] $ConfigName,
        [bool] $Saved,
        [string] $SavedPlatform = "Windows"
    )
    Assert-Ue4Environment
    if ($Saved) {
        return Resolve-Path "$CurrentProjectDirectory/Saved/Config/$SavedPlatform/$ConfigName.ini"
    } else {
        return Resolve-Path "$CurrentProjectDirectory/Config/Default$ConfigName.ini"
    }
}

function Get-Ue4Config {
    param(
        [parameter(Mandatory = $true)] [string] $ConfigName,
        [switch] $Saved,
        [string] $SavedPlatform = "Windows"
    )
    $IniPath = Get-Ue4ConfigPath -ConfigName $ConfigName -Saved $Saved -SavedPlatform $SavedPlatform
    Get-IniContent -Path $IniPath
}

function Set-Ue4Config {
    [cmdletbinding()]
    param (
        [parameter(ValueFromPipeline)] [hashtable] $Data,
        [parameter(Mandatory = $true)] [string] $ConfigName,
        [switch] $Saved,
        [string] $SavedPlatform = "Windows"
    )
    $IniPath = Get-Ue4ConfigPath -ConfigName $ConfigName -Saved $Saved -SavedPlatform $SavedPlatform
    $Data | Set-IniContent -Path $IniPath
}

function Set-Ue4ConfigValue {
    [cmdletbinding()]
    param (
        [parameter(ValueFromPipeline)] [string] $Value,
        [parameter(Mandatory = $true)] [string] $ConfigName,
        [parameter(Mandatory = $true)] [string] $Key,
        [parameter(Mandatory = $true)] [string] $Section,
        [switch] $Saved,
        [string] $SavedPlatform = "Windows"
    )

    $IniPath = Get-Ue4ConfigPath -ConfigName $ConfigName -Saved $Saved -SavedPlatform $SavedPlatform
    $Value | Set-IniValue -Path $IniPath -Key $Key -Section $Section
}

function Get-Ue4ProjectVersion {
    $GeneralProjectSettings = (Get-Ue4Config "Game")."/Script/EngineSettings.GeneralProjectSettings"
    if ($GeneralProjectSettings.ContainsKey("ProjectVersion")) {
        return $GeneralProjectSettings.ProjectVersion
    } else {
        return ""
    }
}

function Set-Ue4ProjectVersion {
    param([parameter(Mandatory = $true)] [string] $Version)
    $Version | Set-Ue4ConfigValue -ConfigName "Game" -Key "ProjectVersion" -Section "/Script/EngineSettings.GeneralProjectSettings"
}

Export-ModuleMember -Function Open-Ue4Project, Get-Ue4ProgramPath, Start-UE4, Get-Ue4Config, Set-Ue4Config, Set-Ue4ConfigValue, Get-Ue4ProjectVersion, Set-Ue4ProjectVersion
