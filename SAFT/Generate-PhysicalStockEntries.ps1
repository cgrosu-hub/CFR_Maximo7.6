# Functie pentru formatare valori numerice (2 zecimale)
function Format-Number2Decimals {
    param ([string]$value)
    if ([string]::IsNullOrWhiteSpace($value)) { return "0.00" }
    try {
        $num = [double]$value
        return "{0:F2}" -f $num
    } catch {
        return "0.00"
    }
}

# Functie pentru escape caractere speciale XML
function Escape-Xml {
    param([string]$text)
    if ($null -eq $text) { return "" }
    return [System.Security.SecurityElement]::Escape($text)
}

# Directorul in care se afla scriptul
$scriptDirectory = Split-Path -Parent $MyInvocation.MyCommand.Path

# 1. Cauta fisierul UOM (Unitati de Masura)
$uomFile = Get-ChildItem -Path $scriptDirectory -Filter "UOM*.csv" -File |
           Sort-Object LastWriteTime -Descending |
           Select-Object -First 1

# Dictionar pentru mapare UOM: Cheie=MEASUREUNITID (ex: BUC), Valoare=ABBREVIATION (ex: H87)
$uomMapping = @{}
$uomEntriesForXml = @() # Lista pentru a popula UOMTable mai tarziu

if ($uomFile) {
    Write-Host "Fisier UOM detectat: $($uomFile.Name)"
    try {
        $uomData = Import-Csv -Path $uomFile.FullName
        foreach ($row in $uomData) {
            # Mapare pentru lookup (ex: BUC -> H87)
            # Folosim coloana MEASUREUNITID ca si cheie de cautare din fisierul de stocuri
            $key = ($row.MEASUREUNITID + "").Trim()
            $abbr = ($row.ABBREVIATION + "").Trim()
            $desc = ($row.DESCRIPTION + "").Trim()

            if (-not [string]::IsNullOrWhiteSpace($key) -and -not [string]::IsNullOrWhiteSpace($abbr)) {
                $uomMapping[$key] = $abbr
            }

            # Date pentru sectiunea UOMTable din XML
            if (-not [string]::IsNullOrWhiteSpace($abbr)) {
                $uomEntriesForXml += @{
                    Code = $abbr
                    Description = $desc
                }
            }
        }
        Write-Host "Au fost incarcate $($uomMapping.Count) mapari de unitati de masura."
    } catch {
        Write-Warning "Eroare la citirea fisierului UOM: $_"
    }
} else {
    Write-Warning "Nu a fost gasit niciun fisier UOM*.csv. Se va folosi valoarea directa din fisierul de export."
}

# 2. Cauta fisierul principal de STOCURI (EXPORT...)
$csvFile = Get-ChildItem -Path $scriptDirectory -Filter "EXPORT*" -File | 
           Sort-Object LastWriteTime -Descending | 
           Select-Object -First 1

if (-not $csvFile) {
    Write-Error "Nu a fost gasit niciun fisier CSV care sa inceapa cu 'EXPORT' in folderul curent: $scriptDirectory"
    exit 1
}

$CsvPath = $csvFile.FullName
Write-Host "Fisier CSV stocuri detectat: $($csvFile.Name)"

# Extrage PeriodStart si PeriodEnd din numele fisierului
$fileName = $csvFile.Name
$startMatch = [regex]::Match($fileName, 'start_(\d{2})(\d{4})')
$endMatch   = [regex]::Match($fileName, 'end_(\d{2})(\d{4})')

if (-not $startMatch.Success -or -not $endMatch.Success) {
    Write-Warning "Formatul numelui fisierului nu contine start_MMYYYY si end_MMYYYY. Se vor folosi valori implicite: 01/2025 - 12/2025"
    $periodStart = "01"
    $periodStartYear = "2025"
    $periodEnd = "12"
    $periodEndYear = "2025"
} else {
    $periodStart = $startMatch.Groups[1].Value
    $periodStartYear = $startMatch.Groups[2].Value
    $periodEnd = $endMatch.Groups[1].Value
    $periodEndYear = $endMatch.Groups[2].Value
}

Write-Host "Perioada detectata: Start $periodStart/$periodStartYear - End $periodEnd/$periodEndYear"

# Genereaza numele fisierului de iesire: SAFT_YYYYMMDD.xml
$currentDate = Get-Date -Format "yyyyMMdd"
$OutputPath = Join-Path $scriptDirectory "SAFT_$currentDate.xml"
Write-Host "Fisierul SAF-T va fi salvat ca: $OutputPath"

# Pregatire fisier LOG
$logDateTime = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
$logPath = Join-Path $scriptDirectory\log "SAFT_Log_$currentDate.txt"
# Creare folder log daca nu exista
if (!(Test-Path -Path "$scriptDirectory\log")) {
    New-Item -ItemType Directory -Path "$scriptDirectory\log" | Out-Null
}

$logLines = @()
$logLines += "Data si ora rularii: $logDateTime"
$logLines += "Fisier CSV stocuri procesat: $($csvFile.Name)"
if ($uomFile) { $logLines += "Fisier UOM utilizat: $($uomFile.Name)" }
$logLines += "Perioada raportata: $periodStart/$periodStartYear - $periodEnd/$periodEndYear"
$logLines += "Fisier XML generat: $(Split-Path $OutputPath -Leaf)"
$logLines += ""

# Contori
$totalRecords = 0
$successRecords = 0
$negativeRecords = 0
$negativeList = @()
$mappedUomCount = 0
$unmappedUomCount = 0

# Deschide fisierul de iesire XML cu encoding UTF-8
$outputStream = [System.IO.StreamWriter]::new($OutputPath, $false, [System.Text.Encoding]::UTF8)

# Scrie header-ul fix SAF-T
$outputStream.WriteLine('<?xml version="1.0" encoding="UTF-8"?>')
$outputStream.WriteLine('<AuditFile xmlns:xsi=''http://www.w3.org/2001/XMLSchema-instance'' xmlns=''mfp:anaf:dgti:d406:declaratie:v1''>')
$outputStream.WriteLine('  <Header>')
$outputStream.WriteLine('    <AuditFileVersion>1.0</AuditFileVersion>')
$outputStream.WriteLine('    <AuditFileCountry>RO</AuditFileCountry>')
$outputStream.WriteLine('    <AuditFileRegion>RO-B</AuditFileRegion>')
$outputStream.WriteLine('    <AuditFileDateCreated>2025-12-31</AuditFileDateCreated>')
$outputStream.WriteLine('    <SoftwareCompanyName>FIA INTEGRA</SoftwareCompanyName>')
$outputStream.WriteLine('    <SoftwareID>IBM MAXIMO</SoftwareID>')
$outputStream.WriteLine('    <SoftwareVersion>9.1</SoftwareVersion>')
$outputStream.WriteLine('    <Company>')
$outputStream.WriteLine('      <RegistrationNumber>11054545</RegistrationNumber>')
$outputStream.WriteLine('      <Name>SNTFC CFR CALATORI S.A.</Name>')
$outputStream.WriteLine('      <Address>')
$outputStream.WriteLine('        <StreetName>B-dul Dinicu Golescu</StreetName>')
$outputStream.WriteLine('        <Number>38</Number>')
$outputStream.WriteLine('        <AdditionalAddressDetail>B-dul Dinicu Golescu</AdditionalAddressDetail>')
$outputStream.WriteLine('        <Building>Palat CFR</Building>')
$outputStream.WriteLine('        <City>Bucuresti</City>')
$outputStream.WriteLine('        <PostalCode>010873</PostalCode>')
$outputStream.WriteLine('        <Region>RO-B</Region>')
$outputStream.WriteLine('        <Country>RO</Country>')
$outputStream.WriteLine('      </Address>')
$outputStream.WriteLine('      <Contact>')
$outputStream.WriteLine('        <ContactPerson>')
$outputStream.WriteLine('          <FirstName>PREOTEASA</FirstName>')
$outputStream.WriteLine('          <LastName>TRAIAN</LastName>')
$outputStream.WriteLine('        </ContactPerson>')
$outputStream.WriteLine('        <Telephone>+40213199529</Telephone>')
$outputStream.WriteLine('      </Contact>')
$outputStream.WriteLine('      <TaxRegistration>')
$outputStream.WriteLine('        <TaxRegistrationNumber>11054545</TaxRegistrationNumber>')
$outputStream.WriteLine('        <TaxType>100010</TaxType>')
$outputStream.WriteLine('        <TaxNumber>11054545</TaxNumber>')
$outputStream.WriteLine('        <TaxAuthority>ANAF</TaxAuthority>')
$outputStream.WriteLine('        <TaxVerificationDate>1998-10-08</TaxVerificationDate>')
$outputStream.WriteLine('      </TaxRegistration>')
$outputStream.WriteLine('      <BankAccount>')
$outputStream.WriteLine('        <IBANNumber>RO24BACX0000000070230310</IBANNumber>')
$outputStream.WriteLine('      </BankAccount>')
$outputStream.WriteLine('    </Company>')
$outputStream.WriteLine('    <DefaultCurrencyCode>RON</DefaultCurrencyCode>')
$outputStream.WriteLine('    <SelectionCriteria>')
$outputStream.WriteLine('      <TaxReportingJurisdiction>Romania</TaxReportingJurisdiction>')
$outputStream.WriteLine('      <CompanyEntity>SNTFC CFR CALATORI S.A.</CompanyEntity>')
$outputStream.WriteLine("      <PeriodStart>$periodStart</PeriodStart>")
$outputStream.WriteLine("      <PeriodStartYear>$periodStartYear</PeriodStartYear>")
$outputStream.WriteLine("      <PeriodEnd>$periodEnd</PeriodEnd>")
$outputStream.WriteLine("      <PeriodEndYear>$periodEndYear</PeriodEndYear>")
$outputStream.WriteLine('    </SelectionCriteria>')
$outputStream.WriteLine('    <HeaderComment>C</HeaderComment>')
$outputStream.WriteLine('    <SegmentIndex>1</SegmentIndex>')
$outputStream.WriteLine('    <TotalSegmentsInsequence>1</TotalSegmentsInsequence>')
$outputStream.WriteLine('    <TaxAccountingBasis>IFRS</TaxAccountingBasis>')
$outputStream.WriteLine('    <TaxEntity>Company</TaxEntity>')
$outputStream.WriteLine('  </Header>')
$outputStream.WriteLine('  <MasterFiles>')
$outputStream.WriteLine('    <GeneralLedgerAccounts>')
$outputStream.WriteLine('    </GeneralLedgerAccounts>')
$outputStream.WriteLine('    <Customers>')
$outputStream.WriteLine('    </Customers>')
$outputStream.WriteLine('    <Suppliers>')
$outputStream.WriteLine('    </Suppliers>')
$outputStream.WriteLine('    <TaxTable>')
$outputStream.WriteLine('    </TaxTable>')

# === SECTIUNEA UOMTable POPULATA DIN CSV ===
$outputStream.WriteLine('    <UOMTable>')
if ($uomEntriesForXml.Count -gt 0) {
    foreach ($item in $uomEntriesForXml) {
        $codeEsc = Escape-Xml $item.Code
        $descEsc = Escape-Xml $item.Description
        $outputStream.WriteLine('      <UOMTableEntry>')
        $outputStream.WriteLine("        <UnitOfMeasure>$codeEsc</UnitOfMeasure>")
        $outputStream.WriteLine("        <Description>$descEsc</Description>")
        $outputStream.WriteLine('      </UOMTableEntry>')
    }
}
$outputStream.WriteLine('    </UOMTable>')
# ============================================

$outputStream.WriteLine('    <AnalysisTypeTable>')
$outputStream.WriteLine('    </AnalysisTypeTable>')
$outputStream.WriteLine('    <MovementTypeTable>')
$outputStream.WriteLine('    </MovementTypeTable>')
$outputStream.WriteLine('    <Products>')
$outputStream.WriteLine('    </Products>')
$outputStream.WriteLine('    <PhysicalStock>')

# Procesare CSV principal (Stocuri)
$reader = [System.IO.StreamReader]::new($CsvPath)
$headerRead = $false

while ($null -ne ($line = $reader.ReadLine())) {
    if (-not $headerRead) {
        $headerRead = $true
        continue
    }

    $totalRecords++

    $row = $line | ConvertFrom-Csv -Header "SITEID","GESTIUNE_BALANTA","MAGAZIE","TIP_GESTIUNE","COD_PRODUS","DESCRIERE_PRODUS","UNITATE_MASURA","PRET_UNITAR","STOC_INITIAL","VALOARE_INITIALA","CANTITATE_INTRATA","CANTITATE_IESITA","STOC_FINAL","VALOARE_FINALA"

    $warehouse   = Escape-Xml $row.MAGAZIE.Trim()
    $productCode = Escape-Xml $row.COD_PRODUS.Trim()
    
# === LOGICA DE MAPARE UOM (cu fallback H87) ===
$rawUom = ($row.UNITATE_MASURA + "").Trim()

if ([string]::IsNullOrWhiteSpace($rawUom)) {
    # Daca nu avem UOM in CSV, folosim valoarea fixa ceruta
    $finalUom = "H87"
    $unmappedUomCount++
}
elseif ($uomMapping.ContainsKey($rawUom)) {
    # Am gasit maparea (ex: BUC -> H87)
    $finalUom = $uomMapping[$rawUom]
    $mappedUomCount++
}
else {
    # Nu am gasit maparea, folosesc valoarea originala
    $finalUom = $rawUom
    $unmappedUomCount++
}

$finalUomEsc = Escape-Xml $finalUom
# =============================================

    $unitPrice   = Format-Number2Decimals $row.PRET_UNITAR
    $openingQty  = Format-Number2Decimals $row.STOC_INITIAL
    $openingVal  = Format-Number2Decimals $row.VALOARE_INITIALA
    $closingQty  = Format-Number2Decimals $row.STOC_FINAL
    $closingVal  = Format-Number2Decimals $row.VALOARE_FINALA

    # Verificare valori negative
    $hasNegative = $false
    try {
        if ([double]$row.PRET_UNITAR -lt 0) { $hasNegative = $true }
        if ([double]$row.STOC_INITIAL -lt 0) { $hasNegative = $true }
        if ([double]$row.VALOARE_INITIALA -lt 0) { $hasNegative = $true }
        if ([double]$row.STOC_FINAL -lt 0) { $hasNegative = $true }
        if ([double]$row.VALOARE_FINALA -lt 0) { $hasNegative = $true }
    } catch {}

    if ($hasNegative) {
        $negativeRecords++
        $negativeList += "$warehouse, $productCode, $unitPrice, $openingQty, $openingVal, $closingQty, $closingVal"
    }

    # Construire si scriere intrare XML
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

    $outputStream.WriteLine($entry)
    $successRecords++
}

$reader.Close()

# Scrie footer-ul final SAF-T
$outputStream.WriteLine('    </PhysicalStock>')
$outputStream.WriteLine('    <Owners>')
$outputStream.WriteLine('    </Owners>')
$outputStream.WriteLine('    <Assets>')
$outputStream.WriteLine('    </Assets>')
$outputStream.WriteLine('  </MasterFiles>')
$outputStream.WriteLine('  <GeneralLedgerEntries></GeneralLedgerEntries>')
$outputStream.WriteLine('  <SourceDocuments>')
$outputStream.WriteLine('    <SalesInvoices></SalesInvoices>')
$outputStream.WriteLine('    <PurchaseInvoices></PurchaseInvoices>')
$outputStream.WriteLine('    <Payments></Payments>')
$outputStream.WriteLine('    <MovementOfGoods>')
$outputStream.WriteLine('    </MovementOfGoods>')
$outputStream.WriteLine('  </SourceDocuments>')
$outputStream.WriteLine('</AuditFile>')

$outputStream.Close()

# Completare LOG
$logLines += "Statistici procesare:"
$logLines += "---------------------"
$logLines += "Numar total inregistrari procesate: $totalRecords"
$logLines += "Unitati de masura mapate cu succes (din fisier UOM): $mappedUomCount"
$logLines += "Unitati de masura nemapate (folosit originalul): $unmappedUomCount"
$logLines += "Inregistrari cu valori negative: $negativeRecords"
$logLines += ""

if ($negativeRecords -gt 0) {
    $logLines += "Detalii inregistrari negative (MAGAZIE, COD_PRODUS, PRET, STOC_INI, VAL_INI, STOC_FIN, VAL_FIN):"
    $logLines += $negativeList
}

# Salveaza fisierul LOG
$logLines | Out-File -FilePath $logPath -Encoding UTF8

Write-Host "Proces complet!"
Write-Host "Fisier XML: $OutputPath"
Write-Host "Log procesare: $logPath"