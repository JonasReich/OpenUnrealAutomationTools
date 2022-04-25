<#
These functions are mostly based on https://gist.github.com/beruic/1be71ae570646bca40734280ea357e3c, which itself is
mostly based on this stackoverflow thread: https://stackoverflow.com/a/43697842/1031534.

Be careful when using with Unreal Engine ini files!
Array syntax (multiple duplicate keys with + prefix) is not supported for export / write functions - only read functions!
For such operations, you should probably use some kind of Unreal Engine commandlet.
#>

<#
.SYNOPSIS
    Read an ini file.

.DESCRIPTION
    Reads an ini file into a hash table of Sections with keys and values.

.EXAMPLE
Get-IniContent /path/to/my/inifile.ini

.NOTES
The resulting hash table has the form [SectionName->SectionContent], where SectionName is a string and SectionContent is a hash table of the form [key->value] where both are strings.
#>

$ErrorActionPreference = "Stop"
function Get-IniContent {
    param(
        # The path to the INI file.
        [parameter(Mandatory = $true)] [string] $Path,
        
        # The Section name to use for the AnonymousSection Section (keys that come before any Section declaration).
        [string] $AnonymousSection = "NoSection",
        
        # Enables saving of Comments to a comment Section in the resulting hash table.
        # The Comments for each Section will be stored in a Section that has the same name as the Section of its origin, but has the comment suffix appended.
        # Comments will be keyed with the comment key prefix and a sequence number for the comment. The sequence number is reset for every Section.
        [switch] $Comments,
        
        # The suffix for comment Sections. The default value is an underscore ("_").
        [string] $CommentsSectionsSuffix = "_",

        # The prefix for comment keys. The default value is "Comment".
        [string] $CommentsKeyPrefix = "Comment"
    )

    $Ini = @{}
    switch -regex -file ($Path) {
        "^\[(.+)\]$" {
            # Section
            $Section = $Matches[1]
            $Ini[$Section] = @{}
            $CommentCount = 0
            if ($Comments) {
                $CommentsSection = $Section + $CommentsSectionsSuffix
                $Ini[$CommentsSection] = @{}
            }
            continue
        }

        "^(;.*)$" {
            # Comment
            if ($Comments) {
                if (!($Section)) {
                    $Section = $AnonymousSection
                    $Ini[$Section] = @{}
                }
                $Value = $Matches[1]
                $CommentCount = $CommentCount + 1
                $name = $CommentsKeyPrefix + $CommentCount
                $CommentsSection = $Section + $CommentsSectionsSuffix
                $Ini[$CommentsSection][$name] = $Value
            }
            continue
        }

        "^(.+?)\s*=\s*(.*)$" {
            # Key
            if (!($Section)) {
                $Section = $AnonymousSection
                $Ini[$Section] = @{}
            }
            $name, $Value = $Matches[1..2]
            if ($name.StartsWith("+")) {
                $key = $name.Substring(1)
                if (-not $Ini[$Section].ContainsKey($key)) {
                    $Ini[$Section][$key] = New-Object System.Collections.ArrayList
                }
                $Ini[$Section][$key].Add($Value) | Out-Null
            } else {
                $Ini[$Section][$name] = $Value
            }
            continue
        }
    }

    return $Ini
}

function Set-IniContent {
    [cmdletbinding()]
    param(
        [parameter(ValueFromPipeline)] [hashtable] $Data,
        [parameter(Mandatory = $true)] [string] $Path,
        [string] $AnonymousSection = "NoSection"
    )
    $Data | New-IniContent -AnonymousSection $AnonymousSection | Set-Content -Path $Path
}

function New-IniContent {
    [cmdletbinding()]
    param(
        [parameter(ValueFromPipeline)] [hashtable] $Data,
        [string] $AnonymousSection = "NoSection"
    )
    process {
        $IniData = $_

        if ($IniData.Contains($AnonymousSection)) {
            $IniData[$AnonymousSection].GetEnumerator() |  ForEach-Object {
                Write-Output "$($_.Name)=$($_.Value)"
            }
            Write-Output ''
        }

        $IniData.GetEnumerator() | ForEach-Object {
            $SectionData = $_
            if ($SectionData.Name -ne $AnonymousSection) {
                Write-Output "[$($SectionData.Name)]"

                $IniData[$SectionData.Name].GetEnumerator() |  ForEach-Object {
                    Write-Output "$($_.Name)=$($_.Value)"
                }
            }
            Write-Output ''
        }
    }
}

function Add-IniValue {
    param (
        [parameter(Mandatory = $true)] [string] $Value,
        [parameter(Mandatory = $true)] [string] $Path,
        [parameter(Mandatory = $true)] [string] $Key,
        [bool] $NoSection = $false,
        [string] $Section
    )
    [bool] $Added = $false
    switch -regex -file ($Path) {
        "^\[(.+)\]$" {
            # Section
            if ($NoSection -and -not $Added) {
                Write-Output "$Key=$Value"
                $Added = $true
            }
            $NewSection = $Matches[1]
            if (($CurrentSection -eq $Section) -and (-not $CurrentSection -eq $Section) -and (-not $Added)) {
                Write-Output "$Key=$Value"
                $Added = $true
            }
            $CurrentSection = $NewSection
            Write-Output "[$CurrentSection]"
            continue
        }

        "^(;.*)$" {
            # Comment
            $Comment = $Matches[1]
            Write-Output ";$Comment"
            continue
        }

        "^(.+?)\s*=\s*(.*)$" {
            # Key
            $name, $CurrentValue = $Matches[1..2]
            if ((($null -eq $CurrentSection -and $NoSection) -or ($CurrentSection -eq $Section)) -and ($name -eq $Key) -and (-not $Added)) {
                Write-Output "$Key=$Value"
                $Added = $true
                continue
            }
            Write-Output "$name=$CurrentValue"
            continue
        }

        ".*" {
            # Everything else (should be whitespace)
            Write-Output $Matches[0]
        }
    }

    if (-not $Added) {
        Write-Output "$Key=$Value"
    }
}


function Set-IniValue {
    [cmdletbinding()]
    param(
        [parameter(ValueFromPipeline)] [string] $Value,
        [parameter(Mandatory = $true)] [string] $Path,
        [parameter(Mandatory = $true)] [string] $Key,
        [switch] $NoSection,
        [string] $Section
    )

    $NewFileContent = Add-IniValue -Value $Value -Path $Path -Key $Key -NoSection $NoSection -Section $Section
    $NewFileContent | Set-Content -Path $Path
}

Export-ModuleMember -Function *
