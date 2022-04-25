<#
This script launches a winforms prompt to locally BuildCookRun a game.
Recommended use case is adding a cmd wrapper script that you can then also let artists/etc launch by double-clicking, e.g.

powershell.exe -ExecutionPolicy RemoteSigned -File .../OpenUnrealAutomationTools/BuildCookRunLauncher.ps1 -ProjectPath .../Foo.uproject
#>

param(
    [String]
    [Parameter(Mandatory=$true)]
    $ProjectPath
)

## POWERSHELL SCRIPT CONFIG

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
# Return all verbose output, so we don't have to specify it on individual calls
# -> all internal commands from OpenUnrealAutomationTools.psm1 can output verbose logs that actually show up in console.
$global:VerbosePreference = 'continue'
# set to a different color than Yellow so it stands out less and warnings are better recognizable
$Host.PrivateData.VerboseForegroundColor = 'Cyan'

$ScriptDirectory = Split-Path $MyInvocation.MyCommand.Path -Parent
Import-Module -Name "$ScriptDirectory/OpenUnrealAutomationTools.psm1" -Verbose -Force

## GET CONFIG FROM UE

$UProject = Open-UEProject $ProjectPath
$GameIni = Get-UEConfig Game
$UECmdPath = Get-UEProgramPath EditorCmd

$MapIniSectionNames = $GameIni["MapsToCook"]["ConfigSections"]
$MapIniSection = $MapIniSectionNames[0]

## WINFORMS GUI FOR LAUNCHER

[void] [System.Reflection.Assembly]::LoadWithPartialName("System.Drawing")
[void] [System.Reflection.Assembly]::LoadWithPartialName("System.Windows.Forms")
$WinForm = New-Object System.Windows.Forms.Form
$WinForm.Backcolor="white"
$WinForm.Size = New-Object System.Drawing.Size(350,130)
$WinForm.FormBorderStyle = 'Fixed3D'
$WinForm.MaximizeBox = $false
$WinForm.Text = "Build Cook Run Launcher"
# Use Unreal Engine icon for our launcher
$WinForm.Icon=[System.Drawing.Icon]::ExtractAssociatedIcon($UECmdPath)

$PromptLabel = New-Object System.Windows.Forms.Label
$PromptLabel.Location = New-Object System.Drawing.Size(5, 5)
$PromptLabel.Size = New-Object System.Drawing.Size(200,20)
$PromptLabel.Text = "MapsToCook config section"
$WinForm.Controls.Add($PromptLabel)

$IniSectionCombobox = New-Object System.Windows.Forms.Combobox
$IniSectionCombobox.Location = New-Object System.Drawing.Size(5, 30)
$IniSectionCombobox.Size = New-Object System.Drawing.Size(200,20)
$IniSectionCombobox.Height = 70
$IniSectionCombobox.DropDownStyle = [System.Windows.Forms.ComboBoxStyle]::DropDownList;
$WinForm.Controls.Add($IniSectionCombobox)
$WinForm.Topmost = $True
foreach ($IniSectionName in $MapIniSectionNames) {
    $IniSectionCombobox.Items.Add($IniSectionName) | Out-Null
}
$IniSectionCombobox.SelectedIndex = 0
$IniSectionCombobox.Add_SelectedIndexChanged({
    $script:MapIniSection = $IniSectionCombobox.Text
})

$LaunchClicked = $False
$LaunchButton = New-Object System.Windows.Forms.Button
$LaunchButton.Location = New-Object System.Drawing.Size(5,55)
$LaunchButton.Size = New-Object System.Drawing.Size(75,20)
$LaunchButton.Text = "Launch"
$LaunchButton.Name = "Launch"
$LaunchButton.Add_Click({ 
    $script:LaunchClicked = $True
    $WinForm.Close() 
})
$WinForm.Controls.Add($LaunchButton)

# Shows the winform and pauses
[void] $WinForm.ShowDialog()

## REACT TO GUI INPUTS / LAUNCH BuildCookRun

if ($LaunchClicked) {
    # TODO Add before -run parameter (?)
    # -cmdline=" -Messaging" -device=WindowsNoEditor@DEUMUCCLW032 -addcmdline="-SessionId=E6ACA1E245978B313340D4A46A0995FD -SessionOwner='jreich' -SessionName='BuildCookLaunch_TQ2_Development'  "
        
    Start-UE UAT -ScriptsForProject="$ProjectPath" BuildCookRun -project="$ProjectPath" -noP4 -clientconfig=Development -serverconfig=Development -nocompile -nocompileeditor -installed -ue4exe="$UECmdPath" -utf8output -platform=Win64 -targetplatform=Win64 -build -cook -additionalcookeroptions="-MAPINISECTION=$MapIniSection" -iterativecooking -SkipCookingEditorContent -compressed -iterativedeploy -stage -deploy -run
} else {
    Write-Warning "Operation was canceled by user"
}
