param(
    [Parameter(Mandatory = $true)][string]$ChromePath,
    [Parameter(Mandatory = $true)][string]$DestinationDirectory,
    [Parameter(Mandatory = $true)][string]$ReceiptPath
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

# Only stage public browser binaries. Profiles and the source cache keep their ACLs.
$source = Get-Item -LiteralPath $ChromePath -Force
if ($source.Name -ne 'chrome.exe' -or $source.PSIsContainer) { throw 'Expected a Chrome executable' }
$sourceDirectory = $source.Directory.FullName
foreach ($name in @('chrome.dll', 'chrome_elf.dll')) {
    if (-not (Test-Path -LiteralPath (Join-Path $sourceDirectory $name) -PathType Leaf)) { throw "Missing browser asset: $name" }
}
foreach ($name in @('Default', 'Local State', 'Cookies')) {
    if (Test-Path -LiteralPath (Join-Path $sourceDirectory $name)) { throw 'A browser profile cannot be staged as a public binary' }
}
$publicDirectory = [System.IO.Path]::GetFullPath($env:PUBLIC)
$target = [System.IO.Path]::GetFullPath($DestinationDirectory)
if ((Split-Path -Parent $target) -ne $publicDirectory -or
    (Split-Path -Leaf $target) -notmatch '^ai-dev-browser-ci-[a-zA-Z0-9-]+$') {
    throw 'Expected a dedicated browser fixture directly inside the public directory'
}
$publicItem = Get-Item -LiteralPath $publicDirectory -Force
if ($publicItem.Attributes -band [System.IO.FileAttributes]::ReparsePoint) { throw 'Public directory is a reparse point' }
if (Test-Path -LiteralPath $target) { throw 'Preserve the existing browser fixture' }
if (Test-Path -LiteralPath $ReceiptPath) { throw 'Preserve the existing staging receipt' }
$items = @(Get-ChildItem -LiteralPath $sourceDirectory -Recurse -Force)
if (@($source, (Get-Item -LiteralPath $sourceDirectory -Force)) + @($items) | Where-Object { $_.Attributes -band [System.IO.FileAttributes]::ReparsePoint }) {
    throw 'Browser assets contain a reparse point'
}
$sourceAcl = (Get-Acl -LiteralPath $sourceDirectory).Sddl
$parentAcl = (Get-Acl -LiteralPath $publicDirectory).Sddl
$proof = [ordered]@{ passed = $false; source = $ChromePath; target = $target; sandboxDisabled = $false }

try {
    New-Item -ItemType Directory -Path $target | Out-Null
    $acl = Get-Acl -LiteralPath $target
    $acl.SetAccessRuleProtection($true, $false)
    $inherit = [System.Security.AccessControl.InheritanceFlags]::ContainerInherit -bor [System.Security.AccessControl.InheritanceFlags]::ObjectInherit
    $propagation = [System.Security.AccessControl.PropagationFlags]::None
    $allow = [System.Security.AccessControl.AccessControlType]::Allow
    $currentSid = [System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value
    foreach ($identity in @($currentSid, 'S-1-5-18', 'S-1-5-32-544', 'S-1-15-2-1', 'S-1-15-2-2')) {
        $rights = if ($identity -in @('S-1-15-2-1', 'S-1-15-2-2')) {
            [System.Security.AccessControl.FileSystemRights]::ReadAndExecute
        } else { [System.Security.AccessControl.FileSystemRights]::FullControl }
        $sid = New-Object System.Security.Principal.SecurityIdentifier($identity)
        $rule = New-Object System.Security.AccessControl.FileSystemAccessRule($sid, $rights, $inherit, $propagation, $allow)
        $acl.AddAccessRule($rule)
    }
    Set-Acl -LiteralPath $target -AclObject $acl
    $bytes = 0L
    foreach ($item in $items) {
        $relative = $item.FullName.Substring($sourceDirectory.Length + 1)
        $destination = Join-Path $target $relative
        if ($item.PSIsContainer) {
            New-Item -ItemType Directory -Path $destination | Out-Null
        } else {
            Copy-Item -LiteralPath $item.FullName -Destination $destination
            if ((Get-FileHash -LiteralPath $item.FullName -Algorithm SHA256).Hash -ne
                (Get-FileHash -LiteralPath $destination -Algorithm SHA256).Hash) { throw "Browser asset changed: $relative" }
            $bytes += $item.Length
        }
    }
    $binary = Join-Path $target 'chrome.exe'
    foreach ($path in @($target, $binary)) {
        $rules = (Get-Acl -LiteralPath $path).GetAccessRules($true, $true, [System.Security.Principal.SecurityIdentifier])
        foreach ($identity in @('S-1-15-2-1', 'S-1-15-2-2')) {
            $matching = @($rules | Where-Object { $_.IdentityReference.Value -eq $identity -and $_.AccessControlType -eq $allow })
            if (-not $matching) { throw 'Missing sandbox read/execute access' }
            foreach ($rule in $matching) {
                if ($rule.FileSystemRights -band [System.Security.AccessControl.FileSystemRights]::Write) { throw 'Sandbox identity received write access' }
            }
        }
    }
    if ((Get-Acl -LiteralPath $sourceDirectory).Sddl -ne $sourceAcl -or
        (Get-Acl -LiteralPath $publicDirectory).Sddl -ne $parentAcl) { throw 'Source or parent permissions changed' }
    $proof.passed = $true
    $proof.binary = $binary
    $proof.chromeVersion = (Get-Item -LiteralPath $binary).VersionInfo.ProductVersion
    $proof.sha256 = (Get-FileHash -LiteralPath $binary -Algorithm SHA256).Hash.ToLowerInvariant()
    $proof.filesCompared = @($items | Where-Object { -not $_.PSIsContainer }).Count
    $proof.bytesCompared = $bytes
    $proof.sourceAndParentAclsUnchanged = $true
} catch {
    $proof.failure = $_.Exception.Message
    throw
} finally {
    [System.IO.File]::WriteAllText($ReceiptPath, ($proof | ConvertTo-Json -Depth 5), (New-Object System.Text.UTF8Encoding($false)))
}

Write-Output $binary
