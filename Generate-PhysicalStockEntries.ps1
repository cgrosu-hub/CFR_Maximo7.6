# Genereaza SAF-T D406: conturi, unitati, produse, stoc fizic si miscari.
# Fisiere in acelasi folder: EXPORT*.csv, UOM*.csv si, optional, INVENTORY*.csv, GLAccounts*.xml, MOG*.csv.
# Windows PowerShell 5.1. Verificare fara CSV:
#   powershell -File .\Generate-PhysicalStockEntries.ps1 -SelfTest
param(
    [switch]$SelfTest
)

$script:invariant = [Globalization.CultureInfo]::InvariantCulture

function Escape-Xml {
    param([string]$text)
    if ($null -eq $text) { return "" }
    return [System.Security.SecurityElement]::Escape($text)
}

# "1,25" si "1.25" sunt 1.25. "1.234,56" nu se parseaza si intra in log.
function ConvertTo-InvariantDouble {
    param([string]$Value)
    $number = [double]0
    if ([string]::IsNullOrWhiteSpace($Value)) {
        return [pscustomobject]@{ Ok = $true; Number = $number }
    }
    $normalized = $Value.Trim().Replace(",", ".")
    $ok = [double]::TryParse(
        $normalized,
        [Globalization.NumberStyles]::Float,
        $script:invariant,
        [ref]$number
    )
    if (-not $ok) {
        return [pscustomobject]@{ Ok = $false; Number = ([double]0) }
    }
    return [pscustomobject]@{ Ok = $true; Number = $number }
}

function Format-StockNumber {
    param(
        [string]$Value,
        [int]$Line,
        [string]$Column,
        [string]$Picture
    )
    $parsed = ConvertTo-InvariantDouble $Value
    if (-not $parsed.Ok) {
        $script:unparseableCount++
        [void]$script:unparseableList.Add("linia $Line, coloana $Column, valoare '$Value'")
    }
    elseif ($parsed.Number -lt 0) {
        $script:rowHasNegative = $true
    }
    return $parsed.Number.ToString($Picture, $script:invariant)
}

function Format-Amount {
    param(
        [string]$Value,
        [int]$Line,
        [string]$Column
    )
    return Format-StockNumber -Value $Value -Line $Line -Column $Column -Picture "F2"
}

function Format-Quantity {
    param(
        [string]$Value,
        [int]$Line,
        [string]$Column
    )
    return Format-StockNumber -Value $Value -Line $Line -Column $Column -Picture "F3"
}

function Resolve-StockUom {
    param([string]$RawUom)
    $raw = ("$RawUom").Trim()
    if (-not [string]::IsNullOrWhiteSpace($raw) -and $script:uomMapping.ContainsKey($raw)) {
        $code = ([string]$script:uomMapping[$raw]).Trim()
        if (-not [string]::IsNullOrWhiteSpace($code)) {
            return [pscustomobject]@{ Code = $code; Fallback = $false; Raw = $raw; Source = "id" }
        }
    }
    # Exportul are deja abrevierea DUK (H87, KGM), nu doar MEASUREUNITID (BUC, KG).
    if (-not [string]::IsNullOrWhiteSpace($raw) -and $script:uomCodes.ContainsKey($raw)) {
        return [pscustomobject]@{ Code = $raw; Fallback = $false; Raw = $raw; Source = "abbr" }
    }
    return [pscustomobject]@{ Code = "H87"; Fallback = $true; Raw = $raw; Source = "fallback" }
}

function Add-UsedUom {
    param([string]$Code)
    if ([string]::IsNullOrWhiteSpace($Code)) { return }
    if (-not $script:usedUomSet.ContainsKey($Code)) {
        $script:usedUomSet[$Code] = $true
        [void]$script:usedUoms.Add($Code)
    }
}

function Add-UomFallback {
    param(
        [string]$Raw,
        [string]$Detail
    )
    $label = $Raw
    if ([string]::IsNullOrWhiteSpace($label)) { $label = "(gol)" }
    $script:fallbackCount++
    if (-not $script:fallbackRawSet.ContainsKey($label)) {
        $script:fallbackRawSet[$label] = $true
        [void]$script:fallbackRawList.Add($label)
    }
    [void]$script:fallbackDetails.Add($Detail)
}

function Convert-MovementDate {
    param([string]$Value)
    $raw = ("$Value").Trim()
    if ([string]::IsNullOrWhiteSpace($raw)) { return "" }
    # MOG din Excel: 3/5/2026 12:00:00 AM si 8/10/2026 1:50:00 PM (luna/zi).
    $formats = @(
        "M/d/yyyy h:mm:ss tt",
        "M/d/yyyy hh:mm:ss tt",
        "MM/dd/yyyy h:mm:ss tt",
        "yyyy-MM-dd",
        "yyyy-MM-dd HH:mm:ss",
        "yyyy-MM-ddTHH:mm:ss",
        "dd.MM.yyyy",
        "dd.MM.yyyy HH:mm:ss",
        "dd/MM/yyyy",
        "dd/MM/yyyy HH:mm:ss",
        "dd-MM-yyyy",
        "dd-MM-yyyy HH:mm:ss"
    )
    # TryParseExact cu [ref] nu se leaga in Windows PowerShell 5.1.
    foreach ($fmt in $formats) {
        try {
            $dt = [datetime]::ParseExact($raw, $fmt, $script:invariant)
            return $dt.ToString("yyyy-MM-dd", $script:invariant)
        } catch {
            continue
        }
    }
    if ($null -ne $script:badDateList) {
        $script:badDateCount++
        [void]$script:badDateList.Add($raw)
    }
    return $raw
}

function Read-CsvDataLines {
    param(
        [string]$Path,
        [scriptblock]$Process
    )
    $reader = [System.IO.StreamReader]::new($Path)
    $lineNo = 0
    $headerRead = $false
    try {
        while ($null -ne ($line = $reader.ReadLine())) {
            $lineNo++
            if (-not $headerRead) {
                $headerRead = $true
                continue
            }
            if ([string]::IsNullOrWhiteSpace(($line + "").Replace(",", "").Trim())) { continue }
            & $Process $line $lineNo
        }
    } finally {
        $reader.Close()
    }
}

$script:uomMapping = @{}
$script:uomCodes = @{}
$script:unparseableCount = 0
$script:unparseableList = New-Object System.Collections.Generic.List[string]
$script:rowHasNegative = $false
$script:usedUoms = New-Object System.Collections.Generic.List[string]
$script:usedUomSet = @{}

if ($SelfTest) {
    $previousCulture = [Threading.Thread]::CurrentThread.CurrentCulture
    try {
        [Threading.Thread]::CurrentThread.CurrentCulture = New-Object System.Globalization.CultureInfo("ro-RO")
    } catch {
        Write-Warning "Cultura ro-RO nu este disponibila pe acest calculator: $_"
    }

    $amount = Format-Amount -Value "12,5" -Line 2 -Column "PRET_UNITAR"
    $amountDot = Format-Amount -Value "0.016000" -Line 2 -Column "VALOARE_INITIALA"
    $quantity = Format-Quantity -Value "16.000" -Line 3 -Column "STOC_FINAL"
    $negativeQty = Format-Quantity -Value "-3,5" -Line 3 -Column "STOC_INITIAL"
    $bad = Format-Amount -Value "abc" -Line 4 -Column "PRET_UNITAR"
    if ($amount -ne "12.50") { throw "Format-Amount a produs '$amount'." }
    if ($amountDot -ne "0.02") { throw "0.016000 a devenit '$amountDot'." }
    if ($quantity -ne "16.000") { throw "16.000 a devenit '$quantity'." }
    if ($negativeQty -ne "-3.500" -or -not $script:rowHasNegative) { throw "Cantitatea negativa nu a fost formatata invariant." }
    if ($bad -ne "0.00" -or $script:unparseableCount -ne 1) { throw "Valoarea neparsabila nu a fost jurnalizata." }
    if (($amount + $amountDot + $quantity + $negativeQty) -match ",") { throw "Un numar formatat contine virgula." }
    $when = Convert-MovementDate "06.10.2026"
    $us = Convert-MovementDate "3/5/2026 12:00:00 AM"
    $pm = Convert-MovementDate "8/10/2026 1:50:00 PM"
    if ($when -ne "2026-10-06") { throw "Data 06.10.2026 a devenit '$when'." }
    if ($us -ne "2026-03-05") { throw "Data Excel AM a devenit '$us'." }
    if ($pm -ne "2026-08-10") { throw "Data Excel PM a devenit '$pm'." }

    $script:uomMapping = @{ BUC = "H87"; KG = "KGM"; BARA = "XBZ" }
    $script:uomCodes = @{ H87 = $true; KGM = $true; XBZ = $true }
    $known = Resolve-StockUom "KG"
    $already = Resolve-StockUom "KGM"
    $translated = Resolve-StockUom "BARA"
    $unknown = Resolve-StockUom "NECUNOSCUT"
    $blank = Resolve-StockUom "  "
    if ($known.Code -ne "KGM" -or $known.Source -ne "id") { throw "KG nu s-a mapat la KGM." }
    if ($already.Code -ne "KGM" -or $already.Fallback) { throw "KGM deja cod DUK a fost rescris." }
    if ($translated.Code -ne "XBZ" -or $translated.Fallback) { throw "BARA nu s-a mapat la XBZ." }
    if ($unknown.Code -ne "H87" -or -not $unknown.Fallback) { throw "Cod necunoscut nu a cazut pe H87." }
    if ($blank.Code -ne "H87" -or -not $blank.Fallback) { throw "UOM gol nu a cazut pe H87." }

    foreach ($code in @("H87", "H87", "KGM")) { Add-UsedUom $code }
    if ($script:usedUoms.Count -ne 2) { throw "UOMTable ar contine coduri duplicate." }

    [Threading.Thread]::CurrentThread.CurrentCulture = $previousCulture
    Write-Host "SelfTest OK"
    exit 0
}

$script:uomMapping = @{}
$script:uomCodes = @{}
$script:uomDescriptionByCode = @{}
$script:usedUoms = New-Object System.Collections.Generic.List[string]
$script:usedUomSet = @{}
$script:unparseableCount = 0
$script:unparseableList = New-Object System.Collections.Generic.List[string]
$script:fallbackCount = 0
$script:fallbackDetails = New-Object System.Collections.Generic.List[string]
$script:fallbackRawList = New-Object System.Collections.Generic.List[string]
$script:fallbackRawSet = @{}
$script:skippedRecords = 0
$script:skippedList = New-Object System.Collections.Generic.List[string]
$script:negativeRecords = 0
$script:negativeList = New-Object System.Collections.Generic.List[string]
$script:mappedFromIdCount = 0
$script:alreadyAbbrCount = 0
$script:totalRecords = 0
$script:successRecords = 0
$script:totalProducts = 0
$script:productConflicts = 0
$script:badProductLines = 0
$script:processedProducts = @{}
$script:productUomSeen = @{}
$script:productXml = New-Object System.Collections.Generic.List[string]
$script:stockXml = New-Object System.Collections.Generic.List[string]
$script:mogRows = New-Object System.Collections.Generic.List[object]
$script:mogTotalLines = 0
$script:mogTotalQtyReceived = [double]0
$script:mogTotalQtyIssued = [double]0
$script:badDateCount = 0
$script:badDateList = New-Object System.Collections.Generic.List[string]
$script:longDocCount = 0
$script:longDocList = New-Object System.Collections.Generic.List[string]
$script:stockHeader = @("SITEID","GESTIUNE_BALANTA","MAGAZIE","TIP_GESTIUNE","COD_PRODUS","DESCRIERE_PRODUS","UNITATE_MASURA","PRET_UNITAR","STOC_INITIAL","VALOARE_INITIALA","CANTITATE_INTRATA","CANTITATE_IESITA","STOC_FINAL","VALOARE_FINALA")
$script:inventoryHeader = @("ITEMNUM","DESCRIPTION","ISSUEUNIT","ABBREVIATION")
$script:mogHeader = @("CXCREDITOBINV","CXDEBITOBINV","MAXIMONR","DENUMIRE","DIRECTIE","COMMODITYGROUP","ITEMNUM","UNITCOST","LINECOST","RECEIVEDUNIT","ABBREVIATION","QUANTITY","TOSTORELOC","FROMSTORELOC","ISSUETYPE","DATAINTRAREIESIRE","NUMARDOC","DATADOC","NRFACT","DATAFACT","GLDEBITACCT","GLCREDITACCT")

$scriptDirectory = Split-Path -Parent $MyInvocation.MyCommand.Path

$uomFile = Get-ChildItem -Path $scriptDirectory -Filter "UOM*.csv" -File |
           Sort-Object LastWriteTime -Descending |
           Select-Object -First 1

if ($uomFile) {
    Write-Host "Fisier UOM detectat: $($uomFile.Name)"
    try {
        $uomData = Import-Csv -Path $uomFile.FullName -Encoding UTF8
        foreach ($row in $uomData) {
            $key = ($row.MEASUREUNITID + "").Trim()
            $abbr = ($row.ABBREVIATION + "").Trim()
            $desc = ($row.DESCRIPTION + "").Trim()

            if (-not [string]::IsNullOrWhiteSpace($key) -and -not [string]::IsNullOrWhiteSpace($abbr)) {
                $script:uomMapping[$key] = $abbr
            }
            if (-not [string]::IsNullOrWhiteSpace($abbr)) {
                $script:uomCodes[$abbr] = $true
                $knownDesc = ""
                if ($script:uomDescriptionByCode.ContainsKey($abbr)) {
                    $knownDesc = [string]$script:uomDescriptionByCode[$abbr]
                }
                if (-not $script:uomDescriptionByCode.ContainsKey($abbr) -or ([string]::IsNullOrWhiteSpace($knownDesc) -and -not [string]::IsNullOrWhiteSpace($desc))) {
                    $script:uomDescriptionByCode[$abbr] = $desc
                }
            }
        }
        Write-Host "Au fost incarcate $($script:uomMapping.Count) mapari de unitati de masura."
    } catch {
        Write-Warning "Eroare la citirea fisierului UOM: $_"
    }
} else {
    Write-Warning "Nu a fost gasit niciun fisier UOM*.csv. Unitatiile necunoscute vor folosi H87."
}

$inventoryFile = Get-ChildItem -Path $scriptDirectory -Filter "INVENTORY*.csv" -File |
                 Sort-Object LastWriteTime -Descending |
                 Select-Object -First 1
if ($inventoryFile) {
    Write-Host "Fisier INVENTORY detectat: $($inventoryFile.Name)"
} else {
    Write-Warning "Nu a fost gasit niciun fisier INVENTORY*.csv."
}

$glAccountsFile = Get-ChildItem -Path $scriptDirectory -Filter "GLAccounts*.xml" -File |
                  Sort-Object LastWriteTime -Descending |
                  Select-Object -First 1
if ($glAccountsFile) {
    Write-Host "Fisier GLAccounts detectat: $($glAccountsFile.Name)"
} else {
    Write-Warning "Nu a fost gasit niciun fisier GLAccounts*.xml."
}

$mogFile = Get-ChildItem -Path $scriptDirectory -Filter "MOG*.csv" -File |
           Sort-Object LastWriteTime -Descending |
           Select-Object -First 1
if ($mogFile) {
    Write-Host "Fisier MOG detectat: $($mogFile.Name)"
} else {
    Write-Warning "Nu a fost gasit niciun fisier MOG*.csv."
}

$csvFile = Get-ChildItem -Path $scriptDirectory -Filter "EXPORT*" -File |
           Sort-Object LastWriteTime -Descending |
           Select-Object -First 1
if (-not $csvFile) {
    Write-Error "Nu a fost gasit niciun fisier CSV care sa inceapa cu 'EXPORT' in folderul curent: $scriptDirectory"
    exit 1
}

$CsvPath = $csvFile.FullName
Write-Host "Fisier CSV stocuri detectat: $($csvFile.Name)"

$fileName = $csvFile.Name
$startMatch = [regex]::Match($fileName, 'start_(\d{2})(\d{4})')
$endMatch   = [regex]::Match($fileName, 'end_(\d{2})(\d{4})')
if (-not $startMatch.Success -or -not $endMatch.Success) {
    Write-Error "Numele fisierului '$fileName' nu contine start_MMYYYY si end_MMYYYY. Exemplu: EXPORT_start_062026_end_102026.csv. Scriptul se opreste."
    exit 1
}

$periodStart = $startMatch.Groups[1].Value
$periodStartYear = $startMatch.Groups[2].Value
$periodEnd = $endMatch.Groups[1].Value
$periodEndYear = $endMatch.Groups[2].Value
Write-Host "Perioada detectata: Start $periodStart/$periodStartYear - End $periodEnd/$periodEndYear"

$runDate = Get-Date
$currentDate = $runDate.ToString("yyyyMMdd", $script:invariant)
$auditFileDateCreated = $runDate.ToString("yyyy-MM-dd", $script:invariant)
$logDateTime = $runDate.ToString("yyyy-MM-dd HH:mm:ss", $script:invariant)
$OutputPath = Join-Path $scriptDirectory "SAFT_$currentDate.xml"
Write-Host "Fisierul SAF-T va fi salvat ca: $OutputPath"

function Import-ProductRows {
    if (-not $inventoryFile) { return }
    Read-CsvDataLines -Path $inventoryFile.FullName -Process {
        param($line, $lineNo)
        try {
            $invRow = $line | ConvertFrom-Csv -Header $script:inventoryHeader
        } catch {
            $script:badProductLines++
            return
        }

        $pCode = ("$($invRow.ITEMNUM)").Trim()
        $pDesc = ("$($invRow.DESCRIPTION)").Trim()
        $rawUom = ("$($invRow.ABBREVIATION)").Trim()
        if ([string]::IsNullOrWhiteSpace($pCode)) { return }

        if ($script:productUomSeen.ContainsKey($pCode)) {
            if ($script:productUomSeen[$pCode] -ne $rawUom -and -not $script:processedProducts.ContainsKey($pCode)) {
                $script:productConflicts++
                $script:processedProducts[$pCode] = $true
            }
            return
        }

        $script:productUomSeen[$pCode] = $rawUom
        $resolved = Resolve-StockUom $rawUom
        Add-UsedUom $resolved.Code
        if ($resolved.Fallback) {
            $rawLabel = $rawUom
            if ([string]::IsNullOrWhiteSpace($rawLabel)) { $rawLabel = "(gol)" }
            Add-UomFallback -Raw $resolved.Raw -Detail "produs $pCode, $rawLabel"
        }

        $script:totalProducts++
        $pCodeEsc = Escape-Xml $pCode
        $pDescEsc = Escape-Xml $pDesc
        $pUomEsc = Escape-Xml $resolved.Code
        $prodEntry = @"
      <Product>
        <ProductCode>$pCodeEsc</ProductCode>
        <GoodsServicesID>01</GoodsServicesID>
        <Description>$pDescEsc</Description>
        <ProductCommodityCode>99500000</ProductCommodityCode>
        <UOMBase>$pUomEsc</UOMBase>
        <UOMStandard>$pUomEsc</UOMStandard>
        <UOMToUOMBaseConversionFactor>1</UOMToUOMBaseConversionFactor>
      </Product>
"@
        [void]$script:productXml.Add($prodEntry)
    }
}

function Import-StockRows {
    Read-CsvDataLines -Path $CsvPath -Process {
        param($line, $lineNo)
        $script:totalRecords++
        try {
            $row = $line | ConvertFrom-Csv -Header $script:stockHeader
        } catch {
            $script:skippedRecords++
            [void]$script:skippedList.Add("linia $lineNo, rand CSV necitibil")
            return
        }

        $warehouseRaw = ("$($row.MAGAZIE)").Trim()
        $productRaw = ("$($row.COD_PRODUS)").Trim()
        if ([string]::IsNullOrWhiteSpace($warehouseRaw) -or [string]::IsNullOrWhiteSpace($productRaw)) {
            $script:skippedRecords++
            [void]$script:skippedList.Add("linia $lineNo, MAGAZIE='$warehouseRaw', COD_PRODUS='$productRaw'")
            return
        }

        $resolved = Resolve-StockUom $row.UNITATE_MASURA
        Add-UsedUom $resolved.Code
        if ($resolved.Fallback) {
            Add-UomFallback -Raw $resolved.Raw -Detail "$warehouseRaw, $productRaw, $(if ([string]::IsNullOrWhiteSpace($resolved.Raw)) { '(gol)' } else { $resolved.Raw })"
        }
        elseif ($resolved.Source -eq "id") {
            $script:mappedFromIdCount++
        }
        else {
            $script:alreadyAbbrCount++
        }

        $script:rowHasNegative = $false
        $unitPrice  = Format-Amount   -Value ("$($row.PRET_UNITAR)")      -Line $lineNo -Column "PRET_UNITAR"
        $openingQty = Format-Quantity -Value ("$($row.STOC_INITIAL)")     -Line $lineNo -Column "STOC_INITIAL"
        $openingVal = Format-Amount   -Value ("$($row.VALOARE_INITIALA)") -Line $lineNo -Column "VALOARE_INITIALA"
        $closingQty = Format-Quantity -Value ("$($row.STOC_FINAL)")       -Line $lineNo -Column "STOC_FINAL"
        $closingVal = Format-Amount   -Value ("$($row.VALOARE_FINALA)")   -Line $lineNo -Column "VALOARE_FINALA"
        if ($script:rowHasNegative) {
            $script:negativeRecords++
            [void]$script:negativeList.Add("$warehouseRaw, $productRaw, $unitPrice, $openingQty, $openingVal, $closingQty, $closingVal")
        }

        $warehouse = Escape-Xml $warehouseRaw
        $productCode = Escape-Xml $productRaw
        $finalUomEsc = Escape-Xml $resolved.Code
        $entry = @"
      <PhysicalStockEntry>
        <WarehouseID>$warehouse</WarehouseID>
        <ProductCode>$productCode</ProductCode>
        <ProductType>4</ProductType>
        <StockAccountCommodityCode>86079900</StockAccountCommodityCode>
        <OwnerID>0011054545</OwnerID>
        <UOMPhysicalStock>$finalUomEsc</UOMPhysicalStock>
        <UOMToUOMBaseConversionFactor>1.0</UOMToUOMBaseConversionFactor>
        <UnitPrice>$unitPrice</UnitPrice>
        <OpeningStockQuantity>$openingQty</OpeningStockQuantity>
        <OpeningStockValue>$openingVal</OpeningStockValue>
        <ClosingStockQuantity>$closingQty</ClosingStockQuantity>
        <ClosingStockValue>$closingVal</ClosingStockValue>
        <StockCharacteristics>
          <StockCharacteristic>NULL</StockCharacteristic>
          <StockCharacteristicValue>NULL</StockCharacteristicValue>
        </StockCharacteristics>
      </PhysicalStockEntry>
"@
        [void]$script:stockXml.Add($entry)
        $script:successRecords++
    }
}

function Import-MogRows {
    if (-not $mogFile) { return }
    Read-CsvDataLines -Path $mogFile.FullName -Process {
        param($line, $lineNo)
        try {
            $row = $line | ConvertFrom-Csv -Header $script:mogHeader
        } catch {
            $script:unparseableCount++
            [void]$script:unparseableList.Add("MOG linia $lineNo, rand CSV necitibil")
            return
        }

        $qtyRaw = ("$($row.QUANTITY)").Trim()
        $parsed = ConvertTo-InvariantDouble $qtyRaw
        if (-not $parsed.Ok) {
            $script:unparseableCount++
            [void]$script:unparseableList.Add("MOG linia $lineNo, coloana QUANTITY, valoare '$qtyRaw'")
        }
        $qtyAbs = [Math]::Abs($parsed.Number)
        $dir = ("$($row.DIRECTIE)").Trim()
        if ($dir -eq "Intrare") { $script:mogTotalQtyReceived += $qtyAbs }
        elseif ($dir -eq "Iesire") { $script:mogTotalQtyIssued += $qtyAbs }

        $resolved = Resolve-StockUom $row.ABBREVIATION
        Add-UsedUom $resolved.Code
        if ($resolved.Fallback) {
            $ref = ("$($row.MAXIMONR)").Trim()
            $item = ("$($row.ITEMNUM)").Trim()
            Add-UomFallback -Raw $resolved.Raw -Detail "MOG linia $lineNo, $ref, $item, $(if ([string]::IsNullOrWhiteSpace($resolved.Raw)) { '(gol)' } else { $resolved.Raw })"
        }

        $script:mogTotalLines++
        [void]$script:mogRows.Add([pscustomobject]@{
            Row = $row
            QtyText = $qtyAbs.ToString("F3", $script:invariant)
            MovDate = (Convert-MovementDate $row.DATADOC)
            Uom = $resolved.Code
        })
    }
}

Import-ProductRows
Import-StockRows
Import-MogRows

$movementTypes = @{
    "10" = "Achizitie"
    "20" = "Productie"
    "30" = "Vanzare"
    "40" = "Retur produse vandute"
    "50" = "Retur produse achizitionate"
    "60" = "Reduceri comerciale primite"
    "70" = "Consum"
    "80" = "Transfer intern"
    "90" = "Cheltuieli ulterioare incluse in valoarea de intrare"
    "100" = "Diferente de pret pozitive"
    "101" = "Diferente de pret negative"
    "110" = "Plus de inventar"
    "120" = "Minus de inventar"
    "130" = "Ajustari pentru deprecierea stocurilor"
    "140" = "Reluari de ajustari pentru deprecierea stocurilor"
    "150" = "Bunuri acordate cu titlu gratuit"
    "160" = "Bunuri degradate"
    "170" = "Bunuri expirate"
    "180" = "Alte tranzactii"
}
$sortedMovementKeys = $movementTypes.Keys | Sort-Object { [int]$_ }

$glAccountsCopied = $false
$script:outputStream = $null
try {
    $script:outputStream = [System.IO.StreamWriter]::new($OutputPath, $false, [System.Text.Encoding]::UTF8)
    $script:outputStream.WriteLine('<?xml version="1.0" encoding="UTF-8"?>')
    $script:outputStream.WriteLine('<AuditFile xmlns:xsi=''http://www.w3.org/2001/XMLSchema-instance'' xmlns=''mfp:anaf:dgti:d406:declaratie:v1''>')
    $script:outputStream.WriteLine('  <Header>')
    $script:outputStream.WriteLine('    <AuditFileVersion>1.0</AuditFileVersion>')
    $script:outputStream.WriteLine('    <AuditFileCountry>RO</AuditFileCountry>')
    $script:outputStream.WriteLine('    <AuditFileRegion>RO-B</AuditFileRegion>')
    $script:outputStream.WriteLine("    <AuditFileDateCreated>$auditFileDateCreated</AuditFileDateCreated>")
    $script:outputStream.WriteLine('    <SoftwareCompanyName>FIA INTEGRA</SoftwareCompanyName>')
    $script:outputStream.WriteLine('    <SoftwareID>IBM MAXIMO</SoftwareID>')
    $script:outputStream.WriteLine('    <SoftwareVersion>9.1</SoftwareVersion>')
    $script:outputStream.WriteLine('    <Company>')
    $script:outputStream.WriteLine('      <RegistrationNumber>11054545</RegistrationNumber>')
    $script:outputStream.WriteLine('      <Name>SNTFC CFR CALATORI S.A.</Name>')
    $script:outputStream.WriteLine('      <Address>')
    $script:outputStream.WriteLine('        <StreetName>B-dul Dinicu Golescu</StreetName>')
    $script:outputStream.WriteLine('        <Number>38</Number>')
    $script:outputStream.WriteLine('        <AdditionalAddressDetail>B-dul Dinicu Golescu</AdditionalAddressDetail>')
    $script:outputStream.WriteLine('        <Building>Palat CFR</Building>')
    $script:outputStream.WriteLine('        <City>Bucuresti</City>')
    $script:outputStream.WriteLine('        <PostalCode>010873</PostalCode>')
    $script:outputStream.WriteLine('        <Region>RO-B</Region>')
    $script:outputStream.WriteLine('        <Country>RO</Country>')
    $script:outputStream.WriteLine('      </Address>')
    $script:outputStream.WriteLine('      <Contact>')
    $script:outputStream.WriteLine('        <ContactPerson>')
    $script:outputStream.WriteLine('          <FirstName>PREOTEASA</FirstName>')
    $script:outputStream.WriteLine('          <LastName>TRAIAN</LastName>')
    $script:outputStream.WriteLine('        </ContactPerson>')
    $script:outputStream.WriteLine('        <Telephone>+40213199529</Telephone>')
    $script:outputStream.WriteLine('      </Contact>')
    $script:outputStream.WriteLine('      <TaxRegistration>')
    $script:outputStream.WriteLine('        <TaxRegistrationNumber>11054545</TaxRegistrationNumber>')
    $script:outputStream.WriteLine('        <TaxType>100010</TaxType>')
    $script:outputStream.WriteLine('        <TaxNumber>11054545</TaxNumber>')
    $script:outputStream.WriteLine('        <TaxAuthority>ANAF</TaxAuthority>')
    $script:outputStream.WriteLine('        <TaxVerificationDate>1998-10-08</TaxVerificationDate>')
    $script:outputStream.WriteLine('      </TaxRegistration>')
    $script:outputStream.WriteLine('      <BankAccount>')
    $script:outputStream.WriteLine('        <IBANNumber>RO24BACX0000000070230310</IBANNumber>')
    $script:outputStream.WriteLine('      </BankAccount>')
    $script:outputStream.WriteLine('    </Company>')
    $script:outputStream.WriteLine('    <DefaultCurrencyCode>RON</DefaultCurrencyCode>')
    $script:outputStream.WriteLine('    <SelectionCriteria>')
    $script:outputStream.WriteLine('      <TaxReportingJurisdiction>Romania</TaxReportingJurisdiction>')
    $script:outputStream.WriteLine('      <CompanyEntity>SNTFC CFR CALATORI S.A.</CompanyEntity>')
    $script:outputStream.WriteLine("      <PeriodStart>$periodStart</PeriodStart>")
    $script:outputStream.WriteLine("      <PeriodStartYear>$periodStartYear</PeriodStartYear>")
    $script:outputStream.WriteLine("      <PeriodEnd>$periodEnd</PeriodEnd>")
    $script:outputStream.WriteLine("      <PeriodEndYear>$periodEndYear</PeriodEndYear>")
    $script:outputStream.WriteLine('    </SelectionCriteria>')
    $script:outputStream.WriteLine('    <HeaderComment>C</HeaderComment>')
    $script:outputStream.WriteLine('    <SegmentIndex>1</SegmentIndex>')
    $script:outputStream.WriteLine('    <TotalSegmentsInsequence>1</TotalSegmentsInsequence>')
    $script:outputStream.WriteLine('    <TaxAccountingBasis>IFRS</TaxAccountingBasis>')
    $script:outputStream.WriteLine('    <TaxEntity>Company</TaxEntity>')
    $script:outputStream.WriteLine('  </Header>')
    $script:outputStream.WriteLine('  <MasterFiles>')

    if ($glAccountsFile) {
        try {
            [xml]$glXml = Get-Content -Path $glAccountsFile.FullName -Encoding UTF8
            $glNode = $glXml.SelectSingleNode("//*[local-name()='GeneralLedgerAccounts']")
            if ($glNode) {
                $script:outputStream.WriteLine($glNode.OuterXml)
                $glAccountsCopied = $true
            } else {
                Write-Warning "Nodul <GeneralLedgerAccounts> nu a fost gasit in fisierul $($glAccountsFile.Name)"
                $script:outputStream.WriteLine('    <GeneralLedgerAccounts>')
                $script:outputStream.WriteLine('    </GeneralLedgerAccounts>')
            }
        } catch {
            Write-Warning "Eroare la procesarea fisierului GLAccounts: $_"
            $script:outputStream.WriteLine('    <GeneralLedgerAccounts>')
            $script:outputStream.WriteLine('    </GeneralLedgerAccounts>')
        }
    } else {
        $script:outputStream.WriteLine('    <GeneralLedgerAccounts>')
        $script:outputStream.WriteLine('    </GeneralLedgerAccounts>')
    }

    $script:outputStream.WriteLine('    <Customers>')
    $script:outputStream.WriteLine('    </Customers>')
    $script:outputStream.WriteLine('    <Suppliers>')
    $script:outputStream.WriteLine('    </Suppliers>')
    $script:outputStream.WriteLine('    <TaxTable>')
    $script:outputStream.WriteLine('    </TaxTable>')
    $script:outputStream.WriteLine('    <UOMTable>')
    foreach ($code in $script:usedUoms) {
        $desc = ""
        if ($script:uomDescriptionByCode.ContainsKey($code)) {
            $desc = [string]$script:uomDescriptionByCode[$code]
        }
        if ([string]::IsNullOrWhiteSpace($desc)) {
            if ($code -eq "H87") { $desc = "Bucata" } else { $desc = $code }
        }
        $codeEsc = Escape-Xml $code
        $descEsc = Escape-Xml $desc
        $script:outputStream.WriteLine('      <UOMTableEntry>')
        $script:outputStream.WriteLine("        <UnitOfMeasure>$codeEsc</UnitOfMeasure>")
        $script:outputStream.WriteLine("        <Description>$descEsc</Description>")
        $script:outputStream.WriteLine('      </UOMTableEntry>')
    }
    $script:outputStream.WriteLine('    </UOMTable>')
    $script:outputStream.WriteLine('    <AnalysisTypeTable>')
    $script:outputStream.WriteLine('    </AnalysisTypeTable>')
    $script:outputStream.WriteLine('    <MovementTypeTable>')
    foreach ($key in $sortedMovementKeys) {
        $desc = $movementTypes["$key"]
        $keyEsc = Escape-Xml $key
        $descEsc = Escape-Xml $desc
        $script:outputStream.WriteLine('      <MovementTypeTableEntry>')
        $script:outputStream.WriteLine("        <MovementType>$keyEsc</MovementType>")
        $script:outputStream.WriteLine("        <Description>$descEsc</Description>")
        $script:outputStream.WriteLine('      </MovementTypeTableEntry>')
    }
    $script:outputStream.WriteLine('    </MovementTypeTable>')
    $script:outputStream.WriteLine('    <Products>')
    foreach ($chunk in $script:productXml) { $script:outputStream.WriteLine($chunk) }
    $script:outputStream.WriteLine('    </Products>')
    $script:outputStream.WriteLine('    <PhysicalStock>')
    foreach ($chunk in $script:stockXml) { $script:outputStream.WriteLine($chunk) }
    $script:outputStream.WriteLine('    </PhysicalStock>')
    $script:outputStream.WriteLine('    <Owners>')
    $script:outputStream.WriteLine('      <Owner>')
    $script:outputStream.WriteLine('        <CompanyStructure>')
    $script:outputStream.WriteLine('          <RegistrationNumber>0011054545</RegistrationNumber>')
    $script:outputStream.WriteLine('          <Name>SNTFC CFR CALATORI S.A.</Name>')
    $script:outputStream.WriteLine('          <Address>')
    $script:outputStream.WriteLine('            <StreetName>B-dul Dinicu Golescu</StreetName>')
    $script:outputStream.WriteLine('            <Number>38</Number>')
    $script:outputStream.WriteLine('            <AdditionalAddressDetail>B-dul Dinicu Golescu</AdditionalAddressDetail>')
    $script:outputStream.WriteLine('            <Building>Palat CFR</Building>')
    $script:outputStream.WriteLine('            <City>Bucuresti</City>')
    $script:outputStream.WriteLine('            <PostalCode>010873</PostalCode>')
    $script:outputStream.WriteLine('            <Region>RO-B</Region>')
    $script:outputStream.WriteLine('            <Country>RO</Country>')
    $script:outputStream.WriteLine('          </Address>')
    $script:outputStream.WriteLine('        </CompanyStructure>')
    $script:outputStream.WriteLine('        <OwnerID>0011054545</OwnerID>')
    $script:outputStream.WriteLine('        <AccountID>1012</AccountID>')
    $script:outputStream.WriteLine('      </Owner>')
    $script:outputStream.WriteLine('    </Owners>')
    $script:outputStream.WriteLine('    <Assets>')
    $script:outputStream.WriteLine('    </Assets>')
    $script:outputStream.WriteLine('  </MasterFiles>')
    $script:outputStream.WriteLine('  <GeneralLedgerEntries></GeneralLedgerEntries>')
    $script:outputStream.WriteLine('  <SourceDocuments>')
    $script:outputStream.WriteLine('    <SalesInvoices></SalesInvoices>')
    $script:outputStream.WriteLine('    <PurchaseInvoices></PurchaseInvoices>')
    $script:outputStream.WriteLine('    <Payments></Payments>')
    $script:outputStream.WriteLine('    <MovementOfGoods>')
    if ($script:mogRows.Count -gt 0 -or $mogFile) {
        $receivedText = $script:mogTotalQtyReceived.ToString("F3", $script:invariant)
        $issuedText = $script:mogTotalQtyIssued.ToString("F3", $script:invariant)
        $script:outputStream.WriteLine("      <NumberOfMovementLines>$($script:mogTotalLines)</NumberOfMovementLines>")
        $script:outputStream.WriteLine("      <TotalQuantityReceived>$receivedText</TotalQuantityReceived>")
        $script:outputStream.WriteLine("      <TotalQuantityIssued>$issuedText</TotalQuantityIssued>")
        foreach ($entry in $script:mogRows) {
            $r = $entry.Row
            $ref = ("$($r.MAXIMONR)").Trim()
            if ([string]::IsNullOrWhiteSpace($ref)) { $ref = "12345678" }
            $docNr = ("$($r.NUMARDOC)").Trim()
            if ([string]::IsNullOrWhiteSpace($docNr)) { $docNr = "12345678" }
            if ($docNr.Length -gt 35) {
                $script:longDocCount++
                [void]$script:longDocList.Add("$docNr")
                $docNr = $docNr.Substring(0, 35)
            }
            $docType = ("$($r.ISSUETYPE)").Trim()
            $itemNum = ("$($r.ITEMNUM)").Trim()
            $dir = ("$($r.DIRECTIE)").Trim()
            $movType = "180"
            if ($dir -eq "Intrare") { $movType = "10" }
            elseif ($dir -eq "Iesire") { $movType = "70" }
            $refEsc = Escape-Xml $ref
            $docNrEsc = Escape-Xml $docNr
            $docTypeEsc = Escape-Xml $docType
            $itemNumEsc = Escape-Xml $itemNum
            $uomEsc = Escape-Xml $entry.Uom
            $qty = $entry.QtyText
            $movDateXml = $entry.MovDate
            $stockMovement = @"
      <StockMovement>
        <MovementReference>$refEsc</MovementReference>
        <MovementDate>$movDateXml</MovementDate>
        <MovementType>$movType</MovementType>
        <DocumentReference>
          <DocumentType>$docTypeEsc</DocumentType>
          <DocumentNumber>$docNrEsc</DocumentNumber>
        </DocumentReference>
        <StockMovementLine>
          <LineNumber>1</LineNumber>
          <AccountID>1011</AccountID>
          <CustomerID>0011054545</CustomerID>
          <SupplierID>0011054545</SupplierID>
          <ProductCode>$itemNumEsc</ProductCode>
          <Quantity>$qty</Quantity>
          <UnitOfMeasure>$uomEsc</UnitOfMeasure>
          <UOMToUOMPhysicalStockConversionFactor>1.0</UOMToUOMPhysicalStockConversionFactor>
          <MovementSubType>$movType</MovementSubType>
        </StockMovementLine>
      </StockMovement>
"@
            $script:outputStream.WriteLine($stockMovement)
        }
    } else {
        $script:outputStream.WriteLine("      <NumberOfMovementLines>0</NumberOfMovementLines>")
        $script:outputStream.WriteLine("      <TotalQuantityReceived>0.000</TotalQuantityReceived>")
        $script:outputStream.WriteLine("      <TotalQuantityIssued>0.000</TotalQuantityIssued>")
    }
    $script:outputStream.WriteLine('    </MovementOfGoods>')
    $script:outputStream.WriteLine('  </SourceDocuments>')
    $script:outputStream.WriteLine('</AuditFile>')
} finally {
    if ($null -ne $script:outputStream) { $script:outputStream.Close() }
}

$logDirectory = Join-Path $scriptDirectory "log"
if (!(Test-Path -Path $logDirectory)) {
    New-Item -ItemType Directory -Path $logDirectory | Out-Null
}
$logPath = Join-Path $logDirectory "SAFT_Log_$currentDate.txt"
$distinctFallback = ($script:fallbackRawList -join ", ")
if ([string]::IsNullOrWhiteSpace($distinctFallback)) { $distinctFallback = "-" }

$logLines = New-Object System.Collections.Generic.List[string]
[void]$logLines.Add("Data si ora rularii: $logDateTime")
[void]$logLines.Add("Fisier CSV stocuri procesat: $($csvFile.Name)")
if ($uomFile) { [void]$logLines.Add("Fisier UOM utilizat: $($uomFile.Name)") }
if ($inventoryFile) { [void]$logLines.Add("Fisier INVENTORY utilizat: $($inventoryFile.Name)") }
if ($glAccountsFile) { [void]$logLines.Add("Fisier GLAccounts utilizat: $($glAccountsFile.Name)") }
if ($mogFile) { [void]$logLines.Add("Fisier MOG utilizat: $($mogFile.Name)") }
[void]$logLines.Add("Perioada raportata: $periodStart/$periodStartYear - $periodEnd/$periodEndYear")
[void]$logLines.Add("Fisier XML generat: $(Split-Path $OutputPath -Leaf)")
[void]$logLines.Add("Data crearii din antet: $auditFileDateCreated")
[void]$logLines.Add("")
[void]$logLines.Add("Statistici procesare:")
[void]$logLines.Add("---------------------")
[void]$logLines.Add("Numar total inregistrari procesate (stocuri): $($script:totalRecords)")
[void]$logLines.Add("Inregistrari stoc scrise in XML: $($script:successRecords)")
[void]$logLines.Add("Inregistrari sarite (MAGAZIE sau COD_PRODUS gol): $($script:skippedRecords)")
[void]$logLines.Add("Conturi contabile copiate din XML extern: $(if ($glAccountsCopied) {'DA'} else {'NU'})")
[void]$logLines.Add("Numar produse unice adaugate in MasterFiles: $($script:totalProducts)")
[void]$logLines.Add("Articole cu aceeasi cod si unitati diferite (pastrata prima): $($script:productConflicts)")
[void]$logLines.Add("Linii produs necitibile: $($script:badProductLines)")
[void]$logLines.Add("Unitati stoc traduse din MEASUREUNITID: $($script:mappedFromIdCount)")
[void]$logLines.Add("Unitati stoc deja cod DUK (ABBREVIATION): $($script:alreadyAbbrCount)")
[void]$logLines.Add("Inregistrari cu UOM in fallback H87: $($script:fallbackCount)")
[void]$logLines.Add("UOM distincte trimise in fallback H87: $distinctFallback")
[void]$logLines.Add("Valori numerice neparsabile: $($script:unparseableCount)")
[void]$logLines.Add("Inregistrari cu valori negative: $($script:negativeRecords)")
[void]$logLines.Add("Numar tranzactii MovementOfGoods (linii MOG): $($script:mogTotalLines)")
[void]$logLines.Add("Total cantitate Intrari (MOG): $($script:mogTotalQtyReceived.ToString('F3', $script:invariant))")
[void]$logLines.Add("Total cantitate Iesiri (MOG): $($script:mogTotalQtyIssued.ToString('F3', $script:invariant))")
[void]$logLines.Add("Date de miscare neconvertite la yyyy-MM-dd: $($script:badDateCount)")
[void]$logLines.Add("Numere de document taiate la 35 de caractere: $($script:longDocCount)")
[void]$logLines.Add("")

if ($script:skippedRecords -gt 0) {
    [void]$logLines.Add("Detalii inregistrari sarite (linia, MAGAZIE, COD_PRODUS):")
    $logLines.AddRange($script:skippedList)
    [void]$logLines.Add("")
}
if ($script:fallbackCount -gt 0) {
    [void]$logLines.Add("Detalii UOM in fallback H87 (MAGAZIE, COD_PRODUS, UOM original sau produs/MOG):")
    $logLines.AddRange($script:fallbackDetails)
    [void]$logLines.Add("")
}
if ($script:unparseableCount -gt 0) {
    [void]$logLines.Add("Valorile neparsabile sunt scrise in XML ca 0.00 (pret/valoare) sau 0.000 (cantitate).")
    [void]$logLines.Add("Detalii valori neparsabile (linia, coloana, valoarea):")
    $logLines.AddRange($script:unparseableList)
    [void]$logLines.Add("")
}
if ($script:longDocCount -gt 0) {
    [void]$logLines.Add("Detalii numere de document taiate la 35 de caractere (valoarea originala):")
    $logLines.AddRange($script:longDocList)
    [void]$logLines.Add("")
}
if ($script:badDateCount -gt 0) {
    [void]$logLines.Add("Detalii date de miscare neconvertite (valoarea din DATADOC):")
    $logLines.AddRange($script:badDateList)
    [void]$logLines.Add("")
}
if ($script:negativeRecords -gt 0) {
    [void]$logLines.Add("Detalii inregistrari negative (MAGAZIE, COD_PRODUS, PRET, STOC_INI, VAL_INI, STOC_FIN, VAL_FIN):")
    $logLines.AddRange($script:negativeList)
    [void]$logLines.Add("")
}

[void]$logLines.Add("Reguli de mapare pentru fisierele CSV:")
[void]$logLines.Add("--------------------------------------")
[void]$logLines.Add("1) Fisier EXPORT* (stocuri):")
[void]$logLines.Add("   - UNITATE_MASURA se traduce din MEASUREUNITID in ABBREVIATION daca exista in UOM*.csv.")
[void]$logLines.Add("   - Daca valoarea este deja o ABBREVIATION din UOM*.csv, ramane neschimbata.")
[void]$logLines.Add("   - Daca este goala sau necunoscuta, in XML se foloseste H87 si randul intra in log.")
[void]$logLines.Add("   - Pretul si valorile au 2 zecimale. Cantitatile au 3 zecimale. Separatorul zecimal din XML este punctul.")
[void]$logLines.Add("   - Randurile fara MAGAZIE sau COD_PRODUS sunt sarite si scrise in log.")
[void]$logLines.Add("2) Fisier INVENTORY* (Products):")
[void]$logLines.Add("   - ITEMNUM -> ProductCode. DESCRIPTION -> Description.")
[void]$logLines.Add("   - ABBREVIATION -> UOMBase si UOMStandard, cu aceleasi reguli de fallback H87.")
[void]$logLines.Add("   - ProductCommodityCode este fix 99500000.")
[void]$logLines.Add("   - Codurile duplicate de produs se scriu o singura data; daca unitatea difera, se pastreaza prima.")
[void]$logLines.Add("3) Fisier UOM* (UOMTable):")
[void]$logLines.Add("   - Intra doar codurile folosite in Products, PhysicalStock si MovementOfGoods, fiecare o singura data.")
[void]$logLines.Add("4) Fisier GLAccounts* (plan de conturi):")
[void]$logLines.Add("   - Scriptul copiaza sectiunea GeneralLedgerAccounts din acest XML in MasterFiles.")
[void]$logLines.Add("5) Fisier MOG* (MovementOfGoods):")
[void]$logLines.Add("   - DIRECTIE Intrare -> tip 10; Iesire -> tip 70; altfel 180.")
[void]$logLines.Add("   - QUANTITY este pozitiva, cu 3 zecimale si punct zecimal.")
[void]$logLines.Add("   - ABBREVIATION urmeaza aceleasi reguli UOM; gol sau necunoscut devine H87.")
[void]$logLines.Add("   - NUMARDOC mai lung de 35 de caractere este taiat la 35, limita DUK pentru DocumentNumber.")
[void]$logLines.Add("")

$logLines | Out-File -FilePath $logPath -Encoding UTF8

Write-Host "Proces complet!"
Write-Host "Fisier XML: $OutputPath"
Write-Host "Log procesare: $logPath"
