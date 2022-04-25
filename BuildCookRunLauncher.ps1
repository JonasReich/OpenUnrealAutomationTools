<#
This script launches a winforms prompt to locally BuildCookRun a game.
Recommended use case is adding a cmd wrapper script that you can then also let artists/etc launch by double-clicking, e.g.

powershell.exe -ExecutionPolicy RemoteSigned -File .../OpenUnrealAutomationTools/BuildCookRunLauncher.ps1 -ProjectPath .../Foo.uproject
#>

param(
    [String]
    [Parameter(Mandatory = $true)]
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

if ($GameIni.ContainsKey("MapsToCook")) {
    $MapIniSectionNames = $GameIni["MapsToCook"]["ConfigSections"]
    Write-Verbose "Detected the following map ini section names: $MapIniSectionNames"
}
else {
    Write-Warning "Expected a config section called [MapsToCook] in DefaultGame.ini to configure which map sections to use for map cook lists."
    $MapIniSectionNames = @("")
}

$MapIniSection = $MapIniSectionNames[0]

$Configuration = "Development"
$Configurations = @($Configuration, "DebugGame", "Shipping", "Test")

## WINFORMS GUI FOR LAUNCHER

[void] [System.Reflection.Assembly]::LoadWithPartialName("System.Drawing")
[void] [System.Reflection.Assembly]::LoadWithPartialName("System.Windows.Forms")
$WinForm = New-Object System.Windows.Forms.Form
$WinForm.Backcolor = "lightgray"
$WinForm.Text = "Build Cook Run Launcher"
# Use Unreal Engine icon for our launcher
$WinForm.Icon = [System.Drawing.Icon]::ExtractAssociatedIcon($UECmdPath)
$WinForm.Topmost = $True

$VerticalPadding = 15
$HorizontalPadding = 10
$AccumulatedHeight = $VerticalPadding

function AddCombobox {
    param(
        $LabelText,
        $Items
    )

    $Label = New-Object System.Windows.Forms.Label
    $Label.Location = New-Object System.Drawing.Size($HorizontalPadding, $script:AccumulatedHeight)
    $script:AccumulatedHeight += 20
    $Label.Size = New-Object System.Drawing.Size(200, 20)
    $Label.Text = $LabelText
    $WinForm.Controls.Add($Label)

    $Combobox = New-Object System.Windows.Forms.Combobox
    $Combobox.Location = New-Object System.Drawing.Size($HorizontalPadding, $script:AccumulatedHeight)
    $Combobox.Size = New-Object System.Drawing.Size(200, 20)
    $Combobox.Height = 70
    $script:AccumulatedHeight += 20 + $VerticalPadding
    $Combobox.DropDownStyle = [System.Windows.Forms.ComboBoxStyle]::DropDownList;
    foreach ($Item in $Items) {
        $Combobox.Items.Add($Item) | Out-Null
    }
    $WinForm.Controls.Add($Combobox)
    $Combobox.SelectedIndex = 0

    return $Combobox
}

# Maps to cook combobox
$IniSectionCombobox = AddCombobox -LabelText "MapsToCook config section" -Items ($MapIniSectionNames)
$IniSectionCombobox.Add_SelectedIndexChanged({
    $script:MapIniSection = $IniSectionCombobox.Text
})

# Build configuration combobox
$ConfigurationCombobox = AddCombobox -LabelText "Build Config (Server + Client)" -Items ($Configurations)
$ConfigurationCombobox.Add_SelectedIndexChanged({
    $script:Configuration = $ConfigurationCombobox.Text
})

# Additional padding before launch button
$AccumulatedHeight += $VerticalPadding

# Launch button
$LaunchClicked = $False
$LaunchButton = New-Object System.Windows.Forms.Button
$LaunchButton.Location = New-Object System.Drawing.Size($HorizontalPadding, $AccumulatedHeight)
$AccumulatedHeight += 20 + $VerticalPadding
$LaunchButton.Size = New-Object System.Drawing.Size(75, 20)
$LaunchButton.Text = "Launch"
$LaunchButton.Name = "Launch"
$LaunchButton.Add_Click({ 
        $script:LaunchClicked = $True
        $WinForm.Close() 
    })
$WinForm.Controls.Add($LaunchButton)

# Adjust size based on content (no scrolling / fixed size)
$TitleBarHeight = 40
$WinForm.Size = New-Object System.Drawing.Size(350, ($AccumulatedHeight + $TitleBarHeight))
$WinForm.FormBorderStyle = 'Fixed3D'
$WinForm.MaximizeBox = $false

# Shows the winform and pauses until closed
[void] $WinForm.ShowDialog()

## REACT TO GUI INPUTS / LAUNCH BuildCookRun

if ($LaunchClicked) {
    # TODO Add before -run parameter (?)
    # -cmdline=" -Messaging" -device=WindowsNoEditor@DEUMUCCLW032 -addcmdline="-SessionId=E6ACA1E245978B313340D4A46A0995FD -SessionOwner='jreich' -SessionName='BuildCookLaunch_TQ2_Development'  "
    $ExecutableArg = if ($script:UEMajorVersion -gt 4) { "-unrealexe=$UECmdPath" } else { "-ue4exe=$UECmdPath" }
    $ConfigurationArgs = @("-clientconfig=$Configuration", "-serverconfig=$Configuration")

    # TODO: Is this the right condition / what is the flag used for? Is this dependent on the engine version or the desired build output?
    $InstalledArg = if ($UEIsInstalledBuild) { "-installed" } else { @() }

    $PlatformArgs = @("-platform=Win64", "-targetplatform=Win64")
    
    Start-UE UAT -ScriptsForProject="$ProjectPath" BuildCookRun -project="$ProjectPath" $ExecutableArg -noP4 $ConfigurationArgs -nocompile -nocompileeditor $InstalledArg -utf8output $PlatformArgs -build -cook "-additionalcookeroptions='-MAPINISECTION=$MapIniSection'" -iterativecooking -SkipCookingEditorContent -compressed -iterativedeploy -stage -deploy -run
}
else {
    Write-Warning "Operation was canceled by user"
}
