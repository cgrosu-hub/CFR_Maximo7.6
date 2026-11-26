# Genereaza SAF-T D406 (sectiunea PhysicalStock) din EXPORT*.csv + UOM*.csv.
# Se ruleaza din folderul in care sunt cele doua fisiere. Windows PowerShell 5.1.
# Verificare rapida, fara CSV: powershell -File .\Generate-PhysicalStockEntries.ps1 -SelfTest
param(
    [switch]$SelfTest
)

$script:invariant = [Globalization.CultureInfo]::InvariantCulture

function Escape-Xml {
    param([string]$text)
    if ($null -eq $text) { return "" }
    return [System.Security.SecurityElement]::Escape($text)
}

# "1,25" -> 1.25. Nu scoatem separatorul de mii: "1.234,56" nu se parseaza si intra in log.
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
    # Exportul CFR are deja abrevierea DUK (H87, KGM), nu MEASUREUNITID (BUC, KG).
    if (-not [string]::IsNullOrWhiteSpace($raw) -and $script:uomCodes.ContainsKey($raw)) {
        return [pscustomobject]@{ Code = $raw; Fallback = $false; Raw = $raw; Source = "abbr" }
    }
    return [pscustomobject]@{ Code = "H87"; Fallback = $true; Raw = $raw; Source = "fallback" }
}

$script:uomMapping = @{}
$script:uomCodes = @{}
$script:uomDescriptionByCode = @{}
$script:usedUoms = New-Object System.Collections.Generic.List[string]
$script:usedUomSet = @{}
$script:unparseableCount = 0
$script:unparseableList = New-Object System.Collections.Generic.List[string]
$script:rowHasNegative = $false

if ($SelfTest) {
    $previousCulture = [Threading.Thread]::CurrentThread.CurrentCulture
    try {
        [Threading.Thread]::CurrentThread.CurrentCulture = New-Object System.Globalization.CultureInfo("ro-RO")
    } catch {
        Write-Warning "Cultura ro-RO nu este disponibila pe acest calculator: $_"
    }

    $amount = Format-Amount -Value "12,5" -Line 2 -Column "PRET_UNITAR"
    $amountDot = Format-Amount -Value "12.5" -Line 2 -Column "PRET_UNITAR"
    $quantity = Format-Quantity -Value "2,5" -Line 3 -Column "STOC_FINAL"
    $negativeQty = Format-Quantity -Value "-3,5" -Line 3 -Column "STOC_INITIAL"
    $bad = Format-Amount -Value "abc" -Line 4 -Column "PRET_UNITAR"
    if ($amount -ne "12.50" -or $amountDot -ne "12.50") { throw "Format-Amount a produs '$amount' / '$amountDot'." }
    if ($quantity -ne "2.500") { throw "Format-Quantity a produs '$quantity'." }
    if ($negativeQty -ne "-3.500" -or -not $script:rowHasNegative) { throw "Cantitatea negativa nu a fost formatata invariant." }
    if ($bad -ne "0.00" -or $script:unparseableCount -ne 1) { throw "Valoarea neparsabila nu a fost jurnalizata." }
    if ($script:unparseableList[0] -notmatch "linia 4, coloana PRET_UNITAR") { throw "Logul valorii neparsabile este incomplet." }
    if (($amount + $quantity + $negativeQty) -match ",") { throw "Un numar formatat contine virgula." }

    $script:uomMapping = @{ BUC = "H87"; KG = "KGM"; BARA = "XBZ" }
    $script:uomCodes = @{ H87 = $true; KGM = $true; XBZ = $true }
    $known = Resolve-StockUom "KG"
    $already = Resolve-StockUom "KGM"
    $translated = Resolve-StockUom "BARA"
    $unknown = Resolve-StockUom "NECUNOSCUT"
    $blank = Resolve-StockUom "  "
    if ($known.Code -ne "KGM" -or $known.Fallback -or $known.Source -ne "id") { throw "KG nu s-a mapat la KGM." }
    if ($already.Code -ne "KGM" -or $already.Fallback -or $already.Source -ne "abbr") { throw "KGM deja cod DUK a fost rescris." }
    if ($translated.Code -ne "XBZ" -or $translated.Fallback) { throw "BARA nu s-a mapat la XBZ." }
    if ($unknown.Code -ne "H87" -or -not $unknown.Fallback) { throw "Cod necunoscut nu a cazut pe H87." }
    if ($blank.Code -ne "H87" -or -not $blank.Fallback) { throw "UOM gol nu a cazut pe H87." }

    foreach ($code in @("H87", "H87", "KGM")) {
        if (-not $script:usedUomSet.ContainsKey($code)) {
            $script:usedUomSet[$code] = $true
            [void]$script:usedUoms.Add($code)
        }
    }
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

function Import-StockRows {
    param(
        [string]$Path,
        [ValidateSet("CollectUom", "WriteEntries")]
        [string]$Mode
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

            $row = $line | ConvertFrom-Csv -Header "SITEID","GESTIUNE_BALANTA","MAGAZIE","TIP_GESTIUNE","COD_PRODUS","DESCRIERE_PRODUS","UNITATE_MASURA","PRET_UNITAR","STOC_INITIAL","VALOARE_INITIALA","CANTITATE_INTRATA","CANTITATE_IESITA","STOC_FINAL","VALOARE_FINALA"
            $warehouseRaw = ("$($row.MAGAZIE)").Trim()
            $productRaw = ("$($row.COD_PRODUS)").Trim()

            if ($Mode -eq "WriteEntries") {
                $script:totalRecords++
            }

            if ([string]::IsNullOrWhiteSpace($warehouseRaw) -or [string]::IsNullOrWhiteSpace($productRaw)) {
                if ($Mode -eq "WriteEntries") {
                    $script:skippedRecords++
                    [void]$script:skippedList.Add("linia $lineNo, MAGAZIE='$warehouseRaw', COD_PRODUS='$productRaw'")
                }
                continue
            }

            $resolved = Resolve-StockUom $row.UNITATE_MASURA
            if ($Mode -eq "CollectUom") {
                if (-not $script:usedUomSet.ContainsKey($resolved.Code)) {
                    $script:usedUomSet[$resolved.Code] = $true
                    [void]$script:usedUoms.Add($resolved.Code)
                }
                continue
            }

            if ($resolved.Fallback) {
                $rawLabel = $resolved.Raw
                if ([string]::IsNullOrWhiteSpace($rawLabel)) { $rawLabel = "(gol)" }
                $script:fallbackCount++
                if (-not $script:fallbackRawSet.ContainsKey($rawLabel)) {
                    $script:fallbackRawSet[$rawLabel] = $true
                    [void]$script:fallbackRawList.Add($rawLabel)
                }
                [void]$script:fallbackDetails.Add("$warehouseRaw, $productRaw, $rawLabel")
            }
            elseif ($resolved.Source -eq "id") {
                $script:mappedFromIdCount++
            }
            else {
                $script:alreadyAbbrCount++
            }

            $script:rowHasNegative = $false
            $unitPrice  = Format-Amount   -Value $row.PRET_UNITAR      -Line $lineNo -Column "PRET_UNITAR"
            $openingQty = Format-Quantity -Value $row.STOC_INITIAL     -Line $lineNo -Column "STOC_INITIAL"
            $openingVal = Format-Amount   -Value $row.VALOARE_INITIALA -Line $lineNo -Column "VALOARE_INITIALA"
            $closingQty = Format-Quantity -Value $row.STOC_FINAL       -Line $lineNo -Column "STOC_FINAL"
            $closingVal = Format-Amount   -Value $row.VALOARE_FINALA   -Line $lineNo -Column "VALOARE_FINALA"

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
            $script:outputStream.WriteLine($entry)
            $script:successRecords++
        }
    } finally {
        $reader.Close()
    }
}

$scriptDirectory = Split-Path -Parent $MyInvocation.MyCommand.Path

$uomFile = Get-ChildItem -Path $scriptDirectory -Filter "UOM*.csv" -File |
           Sort-Object LastWriteTime -Descending |
           Select-Object -First 1

if ($uomFile) {
    Write-Host "Fisier UOM detectat: $($uomFile.Name)"
    try {
        # UTF8: fisierul real are BOM, iar Windows PowerShell 5.1 altfel citeste ANSI.
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
    Write-Warning "Nu a fost gasit niciun fisier UOM*.csv. Unitatiile nemapate vor folosi H87."
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
    Write-Error "Numele fisierului '$fileName' nu contine start_MMYYYY si end_MMYYYY. Exemplu: EXPORT_start_012026_end_122026.csv. Scriptul se opreste."
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

$logPath = Join-Path $scriptDirectory\log "SAFT_Log_$currentDate.txt"
if (!(Test-Path -Path "$scriptDirectory\log")) {
    New-Item -ItemType Directory -Path "$scriptDirectory\log" | Out-Null
}

$script:totalRecords = 0
$script:successRecords = 0
$script:skippedRecords = 0
$script:negativeRecords = 0
$script:mappedFromIdCount = 0
$script:alreadyAbbrCount = 0
$script:fallbackCount = 0
$script:skippedList = New-Object System.Collections.Generic.List[string]
$script:negativeList = New-Object System.Collections.Generic.List[string]
$script:fallbackDetails = New-Object System.Collections.Generic.List[string]
$script:fallbackRawList = New-Object System.Collections.Generic.List[string]
$script:fallbackRawSet = @{}

# UOMTable se scrie inainte de PhysicalStock, deci codurile folosite se aduna intr-o prima trecere.
Import-StockRows -Path $CsvPath -Mode CollectUom

$script:outputStream = [System.IO.StreamWriter]::new($OutputPath, $false, [System.Text.Encoding]::UTF8)
try {
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
    $script:outputStream.WriteLine('    <GeneralLedgerAccounts>')
    $script:outputStream.WriteLine('    </GeneralLedgerAccounts>')
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
            # H87 fara descriere in UOM*.csv: denumirea din nomenclatorul folosit de D406.
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
    $script:outputStream.WriteLine('    </MovementTypeTable>')
    $script:outputStream.WriteLine('    <Products>')
    $script:outputStream.WriteLine('    </Products>')
    $script:outputStream.WriteLine('    <PhysicalStock>')

    Import-StockRows -Path $CsvPath -Mode WriteEntries

    $script:outputStream.WriteLine('    </PhysicalStock>')
    $script:outputStream.WriteLine('    <Owners>')
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
    $script:outputStream.WriteLine('    </MovementOfGoods>')
    $script:outputStream.WriteLine('  </SourceDocuments>')
    $script:outputStream.WriteLine('</AuditFile>')
} finally {
    if ($null -ne $script:outputStream) {
        $script:outputStream.Close()
    }
}

$distinctFallback = ($script:fallbackRawList -join ", ")
if ([string]::IsNullOrWhiteSpace($distinctFallback)) { $distinctFallback = "-" }

$logLines = New-Object System.Collections.Generic.List[string]
[void]$logLines.Add("Data si ora rularii: $logDateTime")
[void]$logLines.Add("Fisier CSV stocuri procesat: $($csvFile.Name)")
if ($uomFile) { [void]$logLines.Add("Fisier UOM utilizat: $($uomFile.Name)") }
[void]$logLines.Add("Perioada raportata: $periodStart/$periodStartYear - $periodEnd/$periodEndYear")
[void]$logLines.Add("Fisier XML generat: $(Split-Path $OutputPath -Leaf)")
[void]$logLines.Add("Data crearii din antet: $auditFileDateCreated")
[void]$logLines.Add("")
[void]$logLines.Add("Statistici procesare:")
[void]$logLines.Add("---------------------")
[void]$logLines.Add("Numar total inregistrari procesate: $($script:totalRecords)")
[void]$logLines.Add("Inregistrari scrise in XML: $($script:successRecords)")
[void]$logLines.Add("Inregistrari sarite (MAGAZIE sau COD_PRODUS gol): $($script:skippedRecords)")
[void]$logLines.Add("Unitati traduse din MEASUREUNITID: $($script:mappedFromIdCount)")
[void]$logLines.Add("Unitati deja cod DUK (ABBREVIATION): $($script:alreadyAbbrCount)")
[void]$logLines.Add("Inregistrari cu UOM in fallback H87: $($script:fallbackCount)")
[void]$logLines.Add("UOM distincte trimise in fallback H87: $distinctFallback")
[void]$logLines.Add("Valori numerice neparsabile: $($script:unparseableCount)")
[void]$logLines.Add("Inregistrari cu valori negative: $($script:negativeRecords)")
[void]$logLines.Add("")

if ($script:skippedRecords -gt 0) {
    [void]$logLines.Add("Detalii inregistrari sarite (linia, MAGAZIE, COD_PRODUS):")
    $logLines.AddRange($script:skippedList)
    [void]$logLines.Add("")
}

if ($script:fallbackCount -gt 0) {
    [void]$logLines.Add("Detalii UOM in fallback H87 (MAGAZIE, COD_PRODUS, UOM original):")
    $logLines.AddRange($script:fallbackDetails)
    [void]$logLines.Add("")
}

if ($script:unparseableCount -gt 0) {
    [void]$logLines.Add("Valorile neparsabile sunt scrise in XML ca 0.00 (pret/valoare) sau 0.000 (cantitate).")
    [void]$logLines.Add("Detalii valori neparsabile (linia, coloana, valoarea):")
    $logLines.AddRange($script:unparseableList)
    [void]$logLines.Add("")
}

if ($script:negativeRecords -gt 0) {
    [void]$logLines.Add("Detalii inregistrari negative (MAGAZIE, COD_PRODUS, PRET, STOC_INI, VAL_INI, STOC_FIN, VAL_FIN):")
    $logLines.AddRange($script:negativeList)
}

$logLines | Out-File -FilePath $logPath -Encoding UTF8

Write-Host "Proces complet!"
Write-Host "Fisier XML: $OutputPath"
Write-Host "Log procesare: $logPath"
