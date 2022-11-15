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
#--------------
# POWERSHELL SCRIPT CONFIG
#--------------

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
# Return all verbose output, so we don't have to specify it on individual calls
# -> all internal commands from OpenUnrealAutomationTools.psm1 can output verbose logs that actually show up in console.
$global:VerbosePreference = 'continue'
# set to a different color than Yellow so it stands out less and warnings are better recognizable
$Host.PrivateData.VerboseForegroundColor = 'Cyan'

$ScriptDirectory = Split-Path $MyInvocation.MyCommand.Path -Parent
Import-Module -Name "$ScriptDirectory/OpenUnrealAutomationTools.psm1" -Verbose -Force

#--------------
# GET CONFIG FROM UE
#--------------

$UProject = Open-UEProject $ProjectPath
$EditorIni = Get-UEConfig Editor
$UECmdPath = Get-UEProgramPath EditorCmd

$MainSectionName = "/Script/OUUDeveloper.OUUMapsToCookSettings"

$MapIniSectionNames = New-Object System.Collections.ArrayList
$MapIniSectionNames.Add("") | Out-Null
$AllMapsToCook = @{}
if (-not $EditorIni.ContainsKey($MainSectionName)) {
    Write-Error "Expected a config section called [$MainSectionName] in DefaultEditor.ini to configure which map sections to use for map cook lists."
}
foreach ($MapIniSection in $EditorIni[$MainSectionName]["ConfigSections"]) {
    $MapIniSectionNames.Add($MapIniSection) | Out-Null
    $AllMapsToCook[$MapIniSection] = $EditorIni[$MapIniSection]["Map"]
}
$InitialMapIniSectionIdx = 0
$MapIniSection = $MapIniSectionNames[$InitialMapIniSectionIdx]
Write-Verbose "Detected ConfigSections: $MapIniSectionNames."
Write-Verbose "Detected DefaultConfigSection: $MapIniSection"

$Configuration = "Development"
$Configurations = @("DebugGame", $Configuration, "Shipping", "Test")

#--------------
# WINFORMS GUI FOR LAUNCHER
#--------------

[void] [System.Reflection.Assembly]::LoadWithPartialName("System.Drawing")
[void] [System.Reflection.Assembly]::LoadWithPartialName("System.Windows.Forms")
$WinForm = New-Object System.Windows.Forms.Form
$WinForm.Backcolor = "lightgray"
$WinForm.Text = "Build Cook Run Launcher"
# Use Unreal Engine icon for our launcher
$WinForm.Icon = [System.Drawing.Icon]::ExtractAssociatedIcon($UECmdPath)
$WinForm.Topmost = $True

$ToolTip = New-Object System.Windows.Forms.Tooltip
$ToolTip.AutoPopDelay = 10000;
$ToolTip.InitialDelay = 1;
$ToolTip.ReshowDelay = 1;
$ToolTip.ShowAlways = $true;

$Width = 400
$VerticalPadding = 15
$HorizontalPadding = 10
$AccumulatedHeight = $VerticalPadding

$Font_Regular = New-Object System.Drawing.Font("Arial",8,[System.Drawing.FontStyle]::Regular)
$Font_Bold = New-Object System.Drawing.Font("Arial",8,[System.Drawing.FontStyle]::Bold)
$Font_Header = New-Object System.Drawing.Font("Arial",10,[System.Drawing.FontStyle]::Bold)

#--------------
# Layout helpers
#--------------

function SetTooltip {
    param(
        $Element,
        $TooltipText
    )
    if (-not ($TooltipText -eq "")) {
        $ToolTip.SetToolTip($Element, $TooltipText)
    }
}

function AddLabel {
    param(
        $LabelText,
        $IsHeader = $False,
        $TooltipText = ""
    )
    $Label = New-Object System.Windows.Forms.Label
    $Label.Location = New-Object System.Drawing.Size($HorizontalPadding, $script:AccumulatedHeight)
    $script:AccumulatedHeight += 20
    $Label.Size = New-Object System.Drawing.Size($Width, 20)
    #$Label.AutoSize = $true
    $Label.AutoEllipsis = $true
    $Label.Text = $LabelText
    $Label.Font = if ($IsHeader) { $Font_Header } else { $Font_Regular }
    $WinForm.Controls.Add($Label) | Out-Null
    SetTooltip $Label $TooltipText

    return $Label
}

function AddCombobox {
    param(
        $LabelText,
        $Items,
        $Index = 0,
        $TooltipText = ""
    )

    AddLabel -LabelText $LabelText -TooltipText $TooltipText | Out-Null

    $Combobox = New-Object System.Windows.Forms.Combobox
    $Combobox.Location = New-Object System.Drawing.Size($HorizontalPadding, $script:AccumulatedHeight)
    $Combobox.Size = New-Object System.Drawing.Size($Width, 20)
    $Combobox.Height = 70
    $script:AccumulatedHeight += 20 + $VerticalPadding
    $Combobox.DropDownStyle = [System.Windows.Forms.ComboBoxStyle]::DropDownList;
    foreach ($Item in $Items) {
        $Combobox.Items.Add($Item) | Out-Null
    }
    $WinForm.Controls.Add($Combobox)
    $Combobox.SelectedIndex = $Index
    SetTooltip $Combobox $TooltipText

    return $Combobox
}

function AddCheckBox {
    param(
        $LabelText,
        $DefaultCheckedState,
        $TooltipText = ""
    )
    $Checkbox = New-Object System.Windows.Forms.Checkbox 
    $Checkbox.Location = New-Object System.Drawing.Size($HorizontalPadding, $script:AccumulatedHeight) 
    $Checkbox.Size = New-Object System.Drawing.Size($Width, 20)
    $script:AccumulatedHeight += 20 + $VerticalPadding
    $Checkbox.Text = $LabelText
    $Checkbox.TabIndex = 4
    $Checkbox.Checked = $DefaultCheckedState
    $WinForm.Controls.Add($Checkbox) | Out-Null
    SetTooltip $Checkbox $TooltipText

    return $Checkbox
}

#--------------
# Primary Layout
#--------------

AddLabel -LabelText "Build" -IsHeader $true | Out-Null

# Build configuration combobox
$ConfigurationCombobox = AddCombobox -LabelText "Build Config (Server + Client)" -Items ($Configurations) -Index 1 -TooltipText "DebugGame is best for detailed debugging. `
Shipping does not have any logs / debug info.`
Development is a good default in-between.`
Test is closest to Shipping for performance testing."

$ConfigurationCombobox.Add_SelectedIndexChanged({
    $script:Configuration = $ConfigurationCombobox.Text
})

AddLabel -LabelText "Cook" -IsHeader $true | Out-Null

function UpdateMapsToCookLabel() {
    $MapsToCook = $AllMapsToCook[$script:MapIniSection] -join "`n"
    $script:MapsToCookLabel.Text = "Maps: $MapsToCook"
    SetTooltip $script:MapsToCookLabel $MapsToCook
}

# Maps to cook combobox
$IniSectionCombobox = AddCombobox -LabelText "MapsToCook config section" -Items ($MapIniSectionNames) -Index $InitialMapIniSectionIdx -TooltipText "Name of the map list to use for the build. Changes cooked maps and startup map."
$IniSectionCombobox.Add_SelectedIndexChanged({
    $script:MapIniSection = $IniSectionCombobox.Text
    UpdateMapsToCookLabel
})

$MapsToCookLabel = AddLabel -LabelText "TEMP" -IsHeader $false -TooltipText "TEMP"
UpdateMapsToCookLabel

$PakCheckbox = AddCheckBox -LabelText "pak" -DefaultCheckedState $False -TooltipText "Combine assets into a few .pak files"

AddLabel -LabelText "Run" -IsHeader $true | Out-Null

$WaitForAttachCheckbox = AddCheckBox -LabelText "waitforattach" -DefaultCheckedState $False -TooltipText "Pause game until a debugger is attached. Useful to debug startup code."

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

#--------------
# Show form + wait
#--------------

# Adjust size based on content (no scrolling / fixed size)
$TitleBarHeight = 40
$WinForm.Size = New-Object System.Drawing.Size(($Width + $HorizontalPadding*2 + 20), ($AccumulatedHeight + $TitleBarHeight))
$WinForm.FormBorderStyle = 'Fixed3D'
$WinForm.MaximizeBox = $false

# Shows the winform and pauses until closed
[void] $WinForm.ShowDialog()

if (-not $LaunchClicked) {
    Write-Warning "Operation was canceled by user"
    exit
}

#--------------
# GENERAL SETTINGS
#--------------
$ExecutableArg = if ($UEMajorVersion -gt 4) { "-unrealexe=$UECmdPath" } else { "-ue4exe=$UECmdPath" }
$GENERAL_ARGS = @(
    "-project=\`"$ProjectPath\`"",
    $ExecutableArg,
    "-noP4",
    "-utf8output"
)

#--------------
# COMPILE / BUILD
#--------------
$ConfigurationArgs = @("-clientconfig=$Configuration", "-serverconfig=$Configuration")

# TODO: Is this the right condition / what is the flag used for? Is this dependent on the engine version or the desired build output?
$InstalledArg = if ($UEIsInstalledBuild) { "-installed" } else { @() }

$COMPILE_ARGS = @(
    $ConfigurationArgs,      # see above
    #"-nocompile",           # This is a convenience tool. We need to compile UAT+editor to make cooking possible without requiring explicit steps in advance.
    #"-nocompileeditor",     # ^
    $InstalledArg,           # see above
    "-platform=Win64",       # current platform
    "-targetplatform=Win64"  # platform for game
    "-build"                 # build the game
)

#--------------
# COOK
#--------------
$MapIniSectionArgs = if ($MapIniSection.Length -gt 0) { "-additionalcookeroptions=\`"-MAPINISECTION=$MapIniSection\`"" } else { $null }
$PakArg = if ($PakCheckbox.Checked) { "-pak" } else { $null }
$COOK_ARGS = @("-cook", $MapIniSectionArgs, "-SkipCookingEditorContent", "-compressed", $PakArg)

#--------------
# STAGE
#--------------
$STAGE_ARGS = @("-stage")

#--------------
# DEPLOY
#--------------
# As long as we do not support platforms other than Win64, deploy is not required
$DEPLOY_ARGS = @() # @("-deploy", "-iterativedeploy")

#--------------
# RUN
#--------------
# These parameters were also present in default cmdline from ProjectLauncher
# -cmdline=" -Messaging"  # -> command line to put into the stage in UE4CommandLine.txt
# -device=WindowsNoEditor@PCNAME  # -> on which device to run
# -addcmdline="-SessionId=E6ACA1E245978B313340D4A46A0995FD -SessionOwner='username' -SessionName='BuildCookLaunch_GameName_Development'  "  # -> pass session info to run cmdline

# additional commandline args for game build during "run" step
$WaitForAttachArg = if ($WaitForAttachCheckbox.Checked) { "-waitforattach" } else { "" }
$RunCmdline = "$WaitForAttachArg"
$RunCmdlineArg = if ($RunCmdline.Length -gt 0) { "-addcmdline=\`"$RunCmdline\`"" } else { $null }
$RUN_ARGS = @("-run", $RunCmdlineArg)

Start-UE UAT -ScriptsForProject="$ProjectPath" BuildCookRun $GENERAL_ARGS $COMPILE_ARGS $COOK_ARGS $DEPLOY_ARGS $STAGE_ARGS $RUN_ARGS
