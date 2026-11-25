#-------------------------------------------------------------
# AUTOSCRIPT:           CXADDTOCXSTOCURI
# DESCRIPTION:          item inventory movement to CXSTOCURI
# AUTHOR:               Fernando Prajitura
# Created:              12-12-2023
# LOGLEVEL:             ERROR
# UPDATE:               21.09.2026 - Bug #1690 Corectie SHIPTRANSFER/SHIPCANCEL
# UPDATE:               30.10.2026 - Cristian Grosu - protectie update MATUSETRANS
# UPDATE:               16.11.2026 - ISSUE: pretul receptiei daca diferenta e 0.001
# UPDATE:               25.11.2026 - TRANSFER LABOR -> CASARE: CXFOLOSINTA
# VERSION:              2026.11.25-CASARE-FOLOSINTA
#-------------------------------------------------------------
# Pentru magaziile sursa normale, CXSTOCURI foloseste COMMODITYGROUP din MATRECTRANS;
# pentru gestiunile speciale se pastreaza codul secundar conform configuratiei LOCATIONS.
# CXCURBAL nu se scrie aici. Soldul e cumulat pe partitie si il completeaza
# CXSTOCURIUPDATECURBAL, in aceeasi ordine ca ledger-ul din CXUPDFIFOROW / CXFIFOFIXISSUE.

from psdi.mbo import Mbo, MboConstants
from psdi.server import MXServer
from psdi.security import UserInfo
from psdi.mbo import SqlFormat
from psdi.webclient.system.session import WebClientSession
from java.io import FileOutputStream
from java.math import BigDecimal
from java.text import NumberFormat, ParsePosition

service.log_info('*** Starting Script CXADDTOCXSTOCURI ***')


#####################################
# Define functions
#####################################

def getAppName():
    current_app = globals().get('app')
    if current_app:
        return str(current_app)
    try:
        wcs = service.webclientsession()
        if wcs:
            current_app = wcs.getCurrentAppId()
            if current_app:
                return str(current_app)
    except Exception:
        pass
    parent_app = mbo.getThisMboSet().getParentApp()
    return str(parent_app) if parent_app else 'None'

def _milli(text):
    # Identic in CXSTOCURIUPDATECURBAL. Preturile sunt la 3 zecimale.
    s = str(text).strip()
    sign = -1 if s.startswith("-") else 1
    if s[:1] in "-+":
        s = s[1:]
    if "." not in s:
        s += ".000"
    whole, frac = s.split(".", 1)
    frac = (frac + "0000")[:4]
    base = int(whole or "0") * 1000 + int(frac[:3])
    if int(frac[3]) >= 5:
        base += 1
    return sign * base

def plain_milli(value):
    sign = "-" if value < 0 else ""
    value = abs(int(value))
    return "%s%d.%03d" % (sign, value // 1000, value % 1000)

def snap_issue_cost(issue_cost, receipt_cost, qty, line_cost):
    # Identic in CXSTOCURIUPDATECURBAL. Doar rotunjirea Maximo de 0.001.
    if issue_cost is None or receipt_cost is None or qty is None or line_cost is None:
        return None
    issue = _milli(issue_cost)
    receipt = _milli(receipt_cost)
    gap = abs(issue - receipt)
    if gap == 0 or gap > 1:
        return None
    value = (abs(_milli(qty)) * abs(receipt) + 500) // 1000
    if abs(_milli(line_cost)) != value:
        return None
    return plain_milli(receipt)

def plain_from_mbo(mbo, field):
    if mbo is None or mbo.isNull(field):
        return None
    raw = mbo.getMboValue(field).getCurrentValue().asString().strip()
    if raw == "":
        return None
    try:
        return BigDecimal(raw).stripTrailingZeros().toPlainString()
    except Exception:
        parser = NumberFormat.getNumberInstance(mbo.getUserInfo().getLocale())
        parser.setParseBigDecimal(True)
        pos = ParsePosition(0)
        value = parser.parse(raw, pos)
        if value is None or pos.getIndex() != len(raw):
            return None
        return value.stripTrailingZeros().toPlainString()

def remember_price(mbo, line):
    flags = MboConstants.NOACCESSCHECK | MboConstants.NOVALIDATION_AND_NOACTION
    old = ""
    try:
        if not mbo.isNull("DESCRIPTION_LONGDESCRIPTION"):
            old = mbo.getString("DESCRIPTION_LONGDESCRIPTION") or ""
    except Exception:
        old = ""
    if line in old:
        return
    text = line if not old.strip() else old.rstrip() + "\n" + line
    mbo.setValue("DESCRIPTION_LONGDESCRIPTION", text, flags)
    try:
        mbo.setValue("HASLD", 1, flags)
    except Exception:
        pass

def issue_receipt_snap(issue):
    if issue.isNull("MATRECTRANSID"):
        return None
    ms = issue.getMboSet("$CXPU_REC", "MATRECTRANS", "MATRECTRANSID=:MATRECTRANSID")
    ms.reset()
    rec = ms.getMbo(0)
    if rec is None:
        return None
    issue_cost = plain_from_mbo(issue, "UNITCOST")
    snapped = snap_issue_cost(
        issue_cost, plain_from_mbo(rec, "UNITCOST"),
        plain_from_mbo(issue, "QUANTITY"), plain_from_mbo(issue, "LINECOST"))
    if snapped is None:
        return None
    return snapped, "PU-RECEPTIE: %s -> %s MATRECTRANS %s" % (
        plain_milli(_milli(issue_cost)), snapped, issue.getLong("MATRECTRANSID"))

def shouldCreateMatUseJournal():
    # onadd/onupdate descriu operatia sursei, nu starea noului rand CXSTOCURI.
    # In After Save se prefera onadd fata de deducerea dupa existenta in DB.
    if bool(globals().get('ondelete', False)):
        service.log_info('CXADDTOCXSTOCURI: MATUSETRANS delete; fara adaugare jurnal.')
        return False
    if 'onadd' in globals():
        is_creation = bool(globals().get('onadd'))
    elif bool(globals().get('onupdate', False)):
        is_creation = False
    else:
        is_creation = mbo.toBeAdded()
    if not is_creation:
        service.log_info('CXADDTOCXSTOCURI: MATUSETRANS existent; adaugare jurnal omisa. ID=' +
                         str(mbo.getLong('MATUSETRANSID')))
        return False
    if mbo.isNull('MATUSETRANSID') or mbo.getLong('MATUSETRANSID') <= 0:
        raise ValueError('MATUSETRANS nou fara ID persistent; jurnalul nu poate fi creat.')
    # Verificare suplimentara, nu o constrangere unica la nivelul bazei de date.
    existing = mbo.getMboSet(
        '$CXFIFO_EXISTING_USE_JOURNAL', 'CXSTOCURI',
        "CXREFMBO='MATUSETRANS' AND CXREFID=:MATUSETRANSID"
    )
    existing.reset()
    if existing.getMbo(0) is not None:
        service.log_info('CXADDTOCXSTOCURI: jurnal deja existent; fara duplicare. MATUSETRANSID=' +
                         str(mbo.getLong('MATUSETRANSID')))
        return False
    return True

def shouldCreateMatRecJournal():
    # Evita jurnal duplicat cand CXFIFOFIX creeaza deja CXSTOCURI pentru RECEIPT split.
    if bool(globals().get('ondelete', False)):
        return False
    if 'onadd' in globals():
        is_creation = bool(globals().get('onadd'))
    elif bool(globals().get('onupdate', False)):
        is_creation = False
    else:
        is_creation = mbo.toBeAdded()
    if not is_creation:
        return False
    if mbo.isNull('MATRECTRANSID') or mbo.getLong('MATRECTRANSID') <= 0:
        raise ValueError('MATRECTRANS nou fara ID persistent; jurnalul nu poate fi creat.')
    existing = mbo.getMboSet(
        '$CXFIFO_EXISTING_REC_JOURNAL', 'CXSTOCURI',
        "CXREFMBO='MATRECTRANS' AND CXREFID=:MATRECTRANSID"
    )
    existing.reset()
    if existing.getMbo(0) is not None:
        service.log_info('CXADDTOCXSTOCURI: jurnal MATRECTRANS deja existent; fara duplicare. ID=' +
                         str(mbo.getLong('MATRECTRANSID')))
        return False
    return True


# --- casare folosinta rules ---
def sql_quote(value):
    return str(value).replace("'", "''")

def is_labor_casare_transfer(issue_type, rotasset, qty, from_type, to_type, to_loc, from_site, to_site):
    # Doar rotating qty 1, acelasi site, LABOR -> LABOR cu CASARE in numele destinatiei.
    if issue_type != "TRANSFER":
        return False
    if rotasset is None or not str(rotasset).strip():
        return False
    try:
        qty_value = float(qty)
    except Exception:
        return False
    if abs(qty_value - 1.0) > 0.000001:
        return False
    if from_type != "LABOR" or to_type != "LABOR":
        return False
    if to_loc is None or "CASARE" not in str(to_loc).upper():
        return False
    if not from_site or not to_site or from_site != to_site:
        return False
    return True

def casare_folosinta_action(dest_exists, open_count):
    # Un singur rand deschis si niciun rand deja legat de acest MATRECTRANS.
    if dest_exists or open_count != 1:
        return "skip"
    return "write"

def _casare_folosinta_self_check():
    ok = is_labor_casare_transfer
    assert ok("TRANSFER", "162215", 1.0, "LABOR", "LABOR", "C01104CASARE", "S", "S")
    assert ok("TRANSFER", "162215", 1.0, "LABOR", "LABOR", "c01104casare", "S", "S")
    assert not ok("TRANSFER", "162215", 1.0, "LABOR", "LABOR", "C01104", "S", "S")
    assert not ok("ISSUE", "162215", 1.0, "LABOR", "LABOR", "C01104CASARE", "S", "S")
    assert not ok("TRANSFER", "", 1.0, "LABOR", "LABOR", "C01104CASARE", "S", "S")
    assert not ok("TRANSFER", None, 1.0, "LABOR", "LABOR", "C01104CASARE", "S", "S")
    assert not ok("TRANSFER", "162215", 2.0, "LABOR", "LABOR", "C01104CASARE", "S", "S")
    assert not ok("TRANSFER", "162215", 1.0, "STOREROOM", "LABOR", "C01104CASARE", "S", "S")
    assert not ok("TRANSFER", "162215", 1.0, "LABOR", "STOREROOM", "C01104CASARE", "S", "S")
    assert not ok("TRANSFER", "162215", 1.0, "LABOR", "LABOR", "C01104CASARE", "A", "B")
    assert not ok("TRANSFER", "162215", 1.0, "LABOR", "LABOR", "C01104CASARE", "S", "")
    assert casare_folosinta_action(True, 1) == "skip"
    assert casare_folosinta_action(False, 0) == "skip"
    assert casare_folosinta_action(False, 2) == "skip"
    assert casare_folosinta_action(False, 1) == "write"
    assert sql_quote("O'Brien") == "O''Brien"
# --- end casare folosinta rules ---

def location_type(mx_server, user_info, location, siteid):
    if not location or not siteid:
        return ""
    loc_set = mx_server.getMboSet("LOCATIONS", user_info)
    try:
        loc_set.setWhere("LOCATION='%s' AND SITEID='%s'" % (sql_quote(location), sql_quote(siteid)))
        loc_set.reset()
        loc = loc_set.getMbo(0)
        if loc is None:
            return ""
        return loc.getString("TYPE")
    finally:
        loc_set.close()

def sync_labor_casare_folosinta(mbo, mx_server, user_info):
    # Inchide fișa deschisă de pe FROMSTORELOC și scrie rândul de casare
    # CXREFMBO/CXREFID = MATRECTRANS, contractul pe care CXCANBC îl anulează.
    # ponytail: exceptia nu iese din script. Jurnalul CXSTOCURI e deja save()-uit,
    # iar o exceptie aici ar da inapoi MATRECTRANS si ar lasa jurnalul scris.
    # Plafon: eroarea ramane in log. Daca apare des, muta apelul inainte de save-ul jurnalului.
    try:
        to_loc = "" if mbo.isNull("TOSTORELOC") else mbo.getString("TOSTORELOC")
        rot = "" if mbo.isNull("ROTASSETNUM") else mbo.getString("ROTASSETNUM")
        from_site = "" if mbo.isNull("FROMSITEID") else mbo.getString("FROMSITEID")
        to_site = "" if mbo.isNull("SITEID") else mbo.getString("SITEID")
        from_loc = "" if mbo.isNull("FROMSTORELOC") else mbo.getString("FROMSTORELOC")
        from_type = location_type(mx_server, user_info, from_loc, from_site)
        to_type = location_type(mx_server, user_info, to_loc, to_site)
        if not is_labor_casare_transfer(
                mbo.getString("ISSUETYPE"), rot, mbo.getDouble("QUANTITY"),
                from_type, to_type, to_loc, from_site, to_site):
            return
        if mbo.isNull("MATRECTRANSID") or int(mbo.getLong("MATRECTRANSID")) <= 0:
            service.log_info("*** CASARE CXFOLOSINTA skip, MATRECTRANSID lipsa ROTASSETNUM=%s ***" % rot)
            return
        if mbo.isNull("ACTUALDATE"):
            service.log_info("*** CASARE CXFOLOSINTA skip, ACTUALDATE lipsa ROTASSETNUM=%s ***" % rot)
            return
        mat_id = int(mbo.getLong("MATRECTRANSID"))
        actual = mbo.getDate("ACTUALDATE")
        dest_set = mx_server.getMboSet("CXFOLOSINTA", user_info)
        try:
            dest_set.setWhere("CXREFMBO='MATRECTRANS' AND CXREFID=%s" % mat_id)
            dest_set.reset()
            dest_exists = dest_set.getMbo(0) is not None
        finally:
            dest_set.close()
        open_set = mx_server.getMboSet("CXFOLOSINTA", user_info)
        try:
            open_set.setWhere(
                "ROTASSETNUM='%s' AND SITEID='%s' AND LOCATION='%s' AND CXLADATA IS NULL"
                % (sql_quote(rot), sql_quote(to_site), sql_quote(from_loc)))
            open_set.reset()
            ids = []
            index = 0
            row = open_set.getMbo(index)
            while row is not None and index < 5:
                ids.append(str(row.getLong("CXFOLOSINTAID")))
                index += 1
                row = open_set.getMbo(index)
            if casare_folosinta_action(dest_exists, index) != "write":
                service.log_info(
                    "*** CASARE CXFOLOSINTA skip ROTASSETNUM=%s MATRECTRANSID=%s FROM=%s open=%s ids=%s dest=%s ***"
                    % (rot, mat_id, from_loc, index, ",".join(ids), dest_exists))
                return
            src = open_set.getMbo(0)
            person = "" if src.isNull("PERSONID") else src.getString("PERSONID")
            if src.isNull("COMMODITYGROUP"):
                commodity = "" if mbo.isNull("COMMODITYGROUP") else mbo.getString("COMMODITYGROUP")
            else:
                commodity = src.getString("COMMODITYGROUP")
            if src.isNull("UNITCOST"):
                unitcost = mbo.getDouble("UNITCOST")
            else:
                unitcost = src.getDouble("UNITCOST")
            src.setValue("CXLADATA", actual)
            src.setValue("CXREFMBOTO", "MATRECTRANS")
            src.setValue("CXREFIDTO", mat_id)
            dest = open_set.addAtEnd()
            flags = MboConstants.NOACCESSCHECK | MboConstants.NOVALIDATION_AND_NOACTION
            dest.setValue("HASLD", 0, flags)
            if person:
                dest.setValue("PERSONID", person)
            dest.setValue("ROTASSETNUM", rot)
            dest.setValue("ITEMNUM", mbo.getString("ITEMNUM"))
            dest.setValue("SITEID", to_site)
            dest.setValue("ORGID", mbo.getString("ORGID"))
            dest.setValue("LOCATION", to_loc)
            if commodity:
                dest.setValue("COMMODITYGROUP", commodity)
            dest.setValue("CXFROMDATE", actual)
            dest.setValue("QUANTITY", 1.0)
            dest.setValue("UNITCOST", unitcost)
            if not src.isNull("CXNRDOC"):
                dest.setValue("CXNRDOC", src.getString("CXNRDOC"))
            if not src.isNull("DESCRIPTION"):
                dest.setValue("DESCRIPTION", src.getString("DESCRIPTION"))
            dest.setValue("CXREFMBO", "MATRECTRANS")
            dest.setValue("CXREFID", mat_id)
            open_set.save()
            service.log_info(
                "*** CASARE CXFOLOSINTA write ROTASSETNUM=%s MATRECTRANSID=%s FROM=%s TO=%s ***"
                % (rot, mat_id, from_loc, to_loc))
        finally:
            open_set.close()
    except Exception as ex:
        service.log_info("*** CASARE CXFOLOSINTA eroare (transferul continua): %s ***" % ex)


#####################################
# Running Code
#####################################

app = getAppName().upper()
userInfo = mbo.getUserInfo()
currentDate = MXServer.getMXServer().getDate()
mxServer = MXServer.getMXServer()
service.log_info('CXADDTOCXSTOCURI script is running from launch point - ' + str(launchPoint) + ' on app - ' + app )
delimitator = '-'
codCustodieInventar ='000' # default value for cod custodie in inventory
cxCodTipGestiuneInv ='000' # default value for cod tip gestiune in inventory
###########
# mbo INVTRANS
###########
if launchPoint == 'CXNEWINVTRANS':
    # # inventory adjustments only
    if mbo.getString('TRANSTYPE') == 'RECBALADJ':
        
        #verifica daca au fost selectate Centru de Cost si Activitate 
        if app == 'CXINVENTOR':
            contCheltuieli = mbo.getString('GLDEBITACCT')
            contDeVerificat = contCheltuieli.split(delimitator, 5)
            if (len(contDeVerificat) <= 4 or
                    contDeVerificat[2] == '00000' or
                    contDeVerificat[4] == '00000'):
                service.error("CXINVADJ", "CXCentruCostActivitate")
            
        # set cod tip gestiune din inventar daca are valoare acolo
        articolInventar = mbo.getMboSet('$CXArtInventar', 'INVENTORY', "location=:STORELOC and siteid=:siteid and itemnum=:itemnum").getMbo(0)
        articol = mbo.getMboSet('$CXItem', 'ITEM', "itemnum=:itemnum").getMbo(0)
        cxCodTipGestuneItem = articol.getString("COMMODITYGROUP")
        cxCodTipGestiuneInv = articolInventar.getString("CXCODTIPGESTIUNE")
        if cxCodTipGestiuneInv:
            cxCodTipGestiune = cxCodTipGestiuneInv
        else:
            cxCodTipGestiune = cxCodTipGestuneItem
            
        # get document date from count date in INVBALANCES for item/storeroom
        invBalMbo = mbo.getMboSet('$CXinvBal', 'INVBALANCES', "location=:STORELOC and siteid=:siteid and itemnum=:itemnum").getMbo(0)
            
        cxStocuriMboSet=mxServer.getMboSet("CXSTOCURI", userInfo)
        # add new line to CXSTOCURI
        linieStocMbo=cxStocuriMboSet.addAtEnd()
        
        linieStocMbo.setValue("ITEMNUM", mbo.getString("ITEMNUM"))
        linieStocMbo.setValue("SITEID",mbo.getString("SITEID"))
        linieStocMbo.setValue("ORGID",mbo.getString("ORGID"))
        linieStocMbo.setValue("LOCATION",mbo.getString("STORELOC"))
        linieStocMbo.setValue("COMMODITYGROUP",cxCodTipGestiune)
        linieStocMbo.setValue("CXDOCUMENTDATE",invBalMbo.getDate("PHYSCNTDATE"))
        linieStocMbo.setValue("CXQTY",mbo.getDouble("QUANTITY"))
        linieStocMbo.setValue("UNITCOST",mbo.getDouble("NEWCOST"))
        linieStocMbo.setValue("CXREFMBO","INVTRANS")
        linieStocMbo.setValue("CXREF",mbo.getString("TRANSTYPE"))
        linieStocMbo.setValue("CXREFID",mbo.getLong("INVTRANSID"))
        # linieStocMbo.setValue("DESCRIPTION",mbo.getString("DESCRIPTION"))
        linieStocMbo.setValue("GLCREDITACCT",mbo.getString("GLCREDITACCT"))
        linieStocMbo.setValue("GLDEBITACCT",mbo.getString("GLDEBITACCT"))
        # linieStocMbo.setValue("CURRENCYCODE","RON")
        
        linieStocMbo.getThisMboSet().save()




###########
# mbo INVLIFOFIFOCOST
###########




###########
# mbo MATUSETRANS
###########



if launchPoint == 'CXNEWMATUSETRANS' and shouldCreateMatUseJournal():
    # get values  from INVENTORY where ITEMNUM and FROMSTORELOC - disabled; will overwrite invuseline selection if different from inventory
    # set cod tip gestiune din inventar daca are valoare acolo
    # articolInventar = mbo.getMboSet('$CXArtInventar', 'INVENTORY', "location=:STORELOC and siteid=:siteid and itemnum=:itemnum").getMbo(0)
    
    # get from INVUSELINE by INVUSELINEID    
    articolInvUseLine = mbo.getMboSet('$CXArtInvUseLine', 'INVUSELINE', "invuselineid=:invuselineid").getMbo(0)
    # aduce cod custodie daca exista in inventory
    if articolInvUseLine:
        if not articolInvUseLine.isNull('CXCODCUSTODIE'):
            codCustodieInventar =  articolInvUseLine.getString('CXCODCUSTODIE')
    
    
    # check action that triggered this
    # speta ISSUE
    if mbo.getString('ISSUETYPE') == 'ISSUE':
        cxStocuriMboSet=mxServer.getMboSet("CXSTOCURI", userInfo)
        # add new line to CXSTOCURI
        linieStocMbo=cxStocuriMboSet.addAtEnd()
        
        linieStocMbo.setValue("ITEMNUM", mbo.getString("ITEMNUM"))
        linieStocMbo.setValue("SITEID",mbo.getString("SITEID"))
        linieStocMbo.setValue("ORGID",mbo.getString("ORGID"))
        linieStocMbo.setValue("LOCATION",mbo.getString("STORELOC"))
        if codCustodieInventar  != '000':
            #linieStocMbo.setValue("COMMODITYGROUP",codCustodieInventar)
            linieStocMbo.setValue("COMMODITYGROUP",codCustodieInventar)
        else:
            linieStocMbo.setValue("COMMODITYGROUP",mbo.getString("COMMODITYGROUP"))
        linieStocMbo.setValue("CXDOCUMENTDATE",mbo.getDate("ACTUALDATE"))
        linieStocMbo.setValue("CXQTY",mbo.getDouble("QUANTITY"))
        price_trace = issue_receipt_snap(mbo)
        if price_trace is None:
            linieStocMbo.setValue("UNITCOST",mbo.getDouble("UNITCOST"))
        else:
            linieStocMbo.setValue("UNITCOST",price_trace[0])
            try:
                remember_price(linieStocMbo, price_trace[1])
            except Exception as exc:
                service.log_info("CXADDTOCXSTOCURI urma pret indisponibila: " + str(exc))
        linieStocMbo.setValue("CXREF",mbo.getString("ISSUETYPE"))
        linieStocMbo.setValue("CXREFMBO","MATUSETRANS")
        linieStocMbo.setValue("CXREFID",mbo.getLong("MATUSETRANSID"))
        linieStocMbo.setValue("DESCRIPTION",mbo.getString("DESCRIPTION"))
        linieStocMbo.setValue("GLCREDITACCT",mbo.getString("GLCREDITACCT"))
        linieStocMbo.setValue("GLDEBITACCT",mbo.getString("GLDEBITACCT"))
        linieStocMbo.setValue("CURRENCYCODE",mbo.getString("CURRENCYCODE"))
        if not mbo.isNull('ROTASSETNUM'):
            linieStocMbo.setValue("ROTASSETNUM",mbo.getString("ROTASSETNUM"))
        
        linieStocMbo.getThisMboSet().save()
        
    # speta RETURN
    if mbo.getString('ISSUETYPE') == 'RETURN':
        cxStocuriMboSet=mxServer.getMboSet("CXSTOCURI", userInfo)
        # add new line to CXSTOCURI
        linieStocMbo=cxStocuriMboSet.addAtEnd()
        
        linieStocMbo.setValue("ITEMNUM", mbo.getString("ITEMNUM"))
        linieStocMbo.setValue("SITEID",mbo.getString("SITEID"))
        linieStocMbo.setValue("ORGID",mbo.getString("ORGID"))
        linieStocMbo.setValue("LOCATION",mbo.getString("STORELOC"))
        if codCustodieInventar  != '000':
            #linieStocMbo.setValue("COMMODITYGROUP",codCustodieInventar)
            linieStocMbo.setValue("COMMODITYGROUP",codCustodieInventar)
        else:
            linieStocMbo.setValue("COMMODITYGROUP",mbo.getString("COMMODITYGROUP"))
        linieStocMbo.setValue("CXDOCUMENTDATE",mbo.getDate("ACTUALDATE"))
        linieStocMbo.setValue("CXQTY",mbo.getDouble("QUANTITY"))
        linieStocMbo.setValue("UNITCOST",mbo.getDouble("UNITCOST"))
        linieStocMbo.setValue("CXREF",mbo.getString("ISSUETYPE"))
        linieStocMbo.setValue("CXREFMBO","MATUSETRANS")
        linieStocMbo.setValue("CXREFID",mbo.getLong("MATUSETRANSID"))
        linieStocMbo.setValue("DESCRIPTION",mbo.getString("DESCRIPTION"))
        linieStocMbo.setValue("GLCREDITACCT",mbo.getString("GLCREDITACCT"))
        linieStocMbo.setValue("GLDEBITACCT",mbo.getString("GLDEBITACCT"))
        linieStocMbo.setValue("CURRENCYCODE",mbo.getString("CURRENCYCODE"))
        
        linieStocMbo.getThisMboSet().save()

###########
# mbo MATRECTRANS
###########

if launchPoint == 'CXNEWMATRECTRANS':
    # 2 linii de introdus: iesirea din fromstoreloc si intrarea in tostoreloc
       
    articolInvUseLine = mbo.getMboSet('$CXArtInvUseLine', 'INVUSELINE', "invuselineid=:invuselineid").getMbo(0)
    if articolInvUseLine:
        if not articolInvUseLine.isNull('CXCODCUSTODIE'):
            codCustodieInventar =  articolInvUseLine.getString('CXCODCUSTODIE')
            
    
    
    # speta SHIPTRANSFER
    if mbo.getString('ISSUETYPE') == 'SHIPTRANSFER':
        cxStocuriMboSet=mxServer.getMboSet("CXSTOCURI", userInfo)
        # add new line to CXSTOCURI
        linieStocMbo=cxStocuriMboSet.addAtEnd()
        
        linieStocMbo.setValue("ITEMNUM", mbo.getString("ITEMNUM"))
        linieStocMbo.setValue("SITEID",mbo.getString("FROMSITEID"))
        linieStocMbo.setValue("ORGID",mbo.getString("ORGID"))
        linieStocMbo.setValue("LOCATION",mbo.getString("FROMSTORELOC"))
        # Bug #1690 - cod secundar doar pentru gestiuni sursa speciale;
        # pentru magazii normale se pastreaza COMMODITYGROUP din MATRECTRANS.
        gestiuneSursa = mbo.getMboSet('$CXGestiuneSursa1690', 'LOCATIONS', "location=:fromstoreloc and siteid=:fromsiteid").getMbo(0)
        gestiuneSursaSpeciala = False
        if gestiuneSursa:
            gestiuneSursaSpeciala = (
                gestiuneSursa.getBoolean('CXCUSTODIE') or
                gestiuneSursa.getBoolean('CXCUSTODIETERTI') or
                gestiuneSursa.getBoolean('CXCUSTODIELASATATERTI') or
                gestiuneSursa.getBoolean('CXGESTIUNEMARFURI') or
                gestiuneSursa.getBoolean('CXGESTIUNEFINITE') or
                gestiuneSursa.getBoolean('CXGESTIUNEALIMENTATIEPUBLICA')
            )
        if gestiuneSursaSpeciala and codCustodieInventar != '000':
            linieStocMbo.setValue("COMMODITYGROUP",codCustodieInventar)
        else:
            linieStocMbo.setValue("COMMODITYGROUP",mbo.getString("COMMODITYGROUP"))
        linieStocMbo.setValue("CXDOCUMENTDATE",mbo.getDate("ACTUALDATE"))
        #   negative qty value for exit
        linieStocMbo.setValue("CXQTY",(-mbo.getDouble("QUANTITY")))
        linieStocMbo.setValue("UNITCOST",mbo.getDouble("UNITCOST"))
        linieStocMbo.setValue("CXREF",mbo.getString("ISSUETYPE"))
        linieStocMbo.setValue("CXREFMBO","MATRECTRANS")
        linieStocMbo.setValue("CXREFID",mbo.getLong("MATRECTRANSID"))
        linieStocMbo.setValue("DESCRIPTION",mbo.getString("DESCRIPTION"))
        linieStocMbo.setValue("GLCREDITACCT",mbo.getString("GLCREDITACCT"))
        linieStocMbo.setValue("GLDEBITACCT",mbo.getString("GLDEBITACCT"))
        linieStocMbo.setValue("CURRENCYCODE",mbo.getString("CURRENCYCODE"))
        #adaugam persoana catre care se face transferul si articolul rotativ
        #linieStocMbo.setValue("ISSUETO",mbo.getString("ISSUETO"))
        #linieStocMbo.setValue("ROTASSETNUM",mbo.getString("ROTASSETNUM"))
        if not mbo.isNull('ISSUETO'):
            linieStocMbo.setValue("ISSUETO",mbo.getString("ISSUETO"))
        if not mbo.isNull('ROTASSETNUM'):
            linieStocMbo.setValue("ROTASSETNUM",mbo.getString("ROTASSETNUM"))                                                    
        
        linieStocMbo.getThisMboSet().save()
    
    # speta SHIPCANCEL
    
    if mbo.getString('ISSUETYPE') == 'SHIPCANCEL':
        cxStocuriMboSet=mxServer.getMboSet("CXSTOCURI", userInfo)
        # add new line to CXSTOCURI
        linieStocMbo=cxStocuriMboSet.addAtEnd()
        
        linieStocMbo.setValue("ITEMNUM", mbo.getString("ITEMNUM"))
        linieStocMbo.setValue("SITEID",mbo.getString("FROMSITEID"))
        linieStocMbo.setValue("ORGID",mbo.getString("ORGID"))
        linieStocMbo.setValue("LOCATION",mbo.getString("FROMSTORELOC"))
        # Bug #1690 - cod secundar doar pentru gestiuni sursa speciale;
        # pentru magazii normale se pastreaza COMMODITYGROUP din MATRECTRANS.
        gestiuneSursa = mbo.getMboSet('$CXGestiuneSursa1690', 'LOCATIONS', "location=:fromstoreloc and siteid=:fromsiteid").getMbo(0)
        gestiuneSursaSpeciala = False
        if gestiuneSursa:
            gestiuneSursaSpeciala = (
                gestiuneSursa.getBoolean('CXCUSTODIE') or
                gestiuneSursa.getBoolean('CXCUSTODIETERTI') or
                gestiuneSursa.getBoolean('CXCUSTODIELASATATERTI') or
                gestiuneSursa.getBoolean('CXGESTIUNEMARFURI') or
                gestiuneSursa.getBoolean('CXGESTIUNEFINITE') or
                gestiuneSursa.getBoolean('CXGESTIUNEALIMENTATIEPUBLICA')
            )
        if gestiuneSursaSpeciala and codCustodieInventar != '000':
            linieStocMbo.setValue("COMMODITYGROUP",codCustodieInventar)
        else:
            linieStocMbo.setValue("COMMODITYGROUP",mbo.getString("COMMODITYGROUP"))
        linieStocMbo.setValue("CXDOCUMENTDATE",mbo.getDate("ACTUALDATE"))
        linieStocMbo.setValue("CXQTY",(mbo.getDouble("QUANTITY")))
        linieStocMbo.setValue("UNITCOST",mbo.getDouble("UNITCOST"))
        linieStocMbo.setValue("CXREF",mbo.getString("ISSUETYPE"))
        linieStocMbo.setValue("CXREFMBO","MATRECTRANS")
        linieStocMbo.setValue("CXREFID",mbo.getLong("MATRECTRANSID"))
        linieStocMbo.setValue("DESCRIPTION",mbo.getString("DESCRIPTION"))
        linieStocMbo.setValue("GLCREDITACCT",mbo.getString("GLCREDITACCT"))
        linieStocMbo.setValue("GLDEBITACCT",mbo.getString("GLDEBITACCT"))
        linieStocMbo.setValue("CURRENCYCODE",mbo.getString("CURRENCYCODE"))
        
        linieStocMbo.getThisMboSet().save()
    
    # speta SHIPRECEIPT
    if mbo.getString('ISSUETYPE') == 'SHIPRECEIPT' and shouldCreateMatRecJournal():
        cxStocuriMboSet=mxServer.getMboSet("CXSTOCURI", userInfo)
        # add new line to CXSTOCURI
        linieStocMbo=cxStocuriMboSet.addAtEnd()
        
        linieStocMbo.setValue("ITEMNUM", mbo.getString("ITEMNUM"))
        linieStocMbo.setValue("SITEID",mbo.getString("SITEID"))
        linieStocMbo.setValue("ORGID",mbo.getString("ORGID"))
        
        if mbo.getString('ROTASSETNUM') is not None and mbo.getString('ROTASSETNUM').strip() != "" and mbo.getString('TOSTORELOC').startswith('H') :
           
            tostorelocMbo = mbo.getMboSet('$CXArtNomenclator', 'INVUSELINE', "invuselineid=:invuselineid").getMbo(0)
            if tostorelocMbo:
                linieStocMbo.setValue("LOCATION",tostorelocMbo.getString("TOSTORELOC"))
        else:
            linieStocMbo.setValue("LOCATION",mbo.getString("TOSTORELOC"))
        
        if mbo.getString('CXCODCUSTODIE') is not None and mbo.getString('CXCODCUSTODIE').strip() != "":
        
        #if codCustodieInventar != '000':
            linieStocMbo.setValue("COMMODITYGROUP",mbo.getString('CXCODCUSTODIE') )
        else:
            linieStocMbo.setValue("COMMODITYGROUP",mbo.getString("COMMODITYGROUP"))
        linieStocMbo.setValue("CXDOCUMENTDATE",mbo.getDate("ACTUALDATE"))
        linieStocMbo.setValue("CXQTY",mbo.getDouble("QUANTITY"))
        linieStocMbo.setValue("UNITCOST",mbo.getDouble("UNITCOST"))
        linieStocMbo.setValue("CXREF",mbo.getString("ISSUETYPE"))
        linieStocMbo.setValue("CXREFMBO","MATRECTRANS")
        linieStocMbo.setValue("CXREFID",mbo.getLong("MATRECTRANSID"))
        linieStocMbo.setValue("DESCRIPTION",mbo.getString("DESCRIPTION"))
        linieStocMbo.setValue("GLCREDITACCT",mbo.getString("GLCREDITACCT"))
        linieStocMbo.setValue("GLDEBITACCT",mbo.getString("GLDEBITACCT"))
        linieStocMbo.setValue("CURRENCYCODE",mbo.getString("CURRENCYCODE"))
        #adaugam persoana care a receptionat transferul si articolul rotativ
        if not mbo.isNull('ISSUETO'):
            linieStocMbo.setValue("ISSUETO",mbo.getString("ISSUETO"))
        if not mbo.isNull('ROTASSETNUM'):
            linieStocMbo.setValue("ROTASSETNUM",mbo.getString("ROTASSETNUM"))
                                                                            
        linieStocMbo.getThisMboSet().save()
    
    #   speta VOIDSHIPRECEIPT
    if mbo.getString('ISSUETYPE') == 'VOIDSHIPRECEIPT':
        cxStocuriMboSet=mxServer.getMboSet("CXSTOCURI", userInfo)
        # add new line to CXSTOCURI
        linieStocMbo=cxStocuriMboSet.addAtEnd()
        
        linieStocMbo.setValue("ITEMNUM", mbo.getString("ITEMNUM"))
        linieStocMbo.setValue("SITEID",mbo.getString("FROMSITEID"))
        linieStocMbo.setValue("ORGID",mbo.getString("ORGID"))
        linieStocMbo.setValue("LOCATION",mbo.getString("TOSTORELOC"))
        if codCustodieInventar != '000':
            linieStocMbo.setValue("COMMODITYGROUP",codCustodieInventar )
        else:
            linieStocMbo.setValue("COMMODITYGROUP",mbo.getString("COMMODITYGROUP"))
        linieStocMbo.setValue("CXDOCUMENTDATE",mbo.getDate("ACTUALDATE"))
        linieStocMbo.setValue("CXQTY",(mbo.getDouble("QUANTITY")))
        linieStocMbo.setValue("UNITCOST",mbo.getDouble("UNITCOST"))
        linieStocMbo.setValue("CXREF",mbo.getString("ISSUETYPE"))
        linieStocMbo.setValue("CXREFMBO","MATRECTRANS")
        linieStocMbo.setValue("CXREFID",mbo.getLong("MATRECTRANSID"))
        linieStocMbo.setValue("DESCRIPTION",mbo.getString("DESCRIPTION"))
        linieStocMbo.setValue("GLCREDITACCT",mbo.getString("GLCREDITACCT"))
        linieStocMbo.setValue("GLDEBITACCT",mbo.getString("GLDEBITACCT"))
        linieStocMbo.setValue("CURRENCYCODE",mbo.getString("CURRENCYCODE"))
        
        linieStocMbo.getThisMboSet().save()
    
    #   speta SHIPRETURN
    if mbo.getString('ISSUETYPE') == 'SHIPRETURN':
        cxStocuriMboSet=mxServer.getMboSet("CXSTOCURI", userInfo)
        # add 2 lines to CXSTOCURI for source and destination
        linieStocMbo=cxStocuriMboSet.addAtEnd()
        cxCodCustodie = mbo.getString("CXCODCUSTODIE")
        linieStocMbo.setValue("ITEMNUM", mbo.getString("ITEMNUM"))
        linieStocMbo.setValue("SITEID",mbo.getString("FROMSITEID"))
        linieStocMbo.setValue("ORGID",mbo.getString("ORGID"))
        linieStocMbo.setValue("LOCATION",mbo.getString("FROMSTORELOC"))
        if codCustodieInventar != '000':
            linieStocMbo.setValue("COMMODITYGROUP",codCustodieInventar )
        elif cxCodCustodie:
            # are valoare si nu e string gol
            linieStocMbo.setValue("COMMODITYGROUP", cxCodCustodie)
        else:
            linieStocMbo.setValue("COMMODITYGROUP",mbo.getString("COMMODITYGROUP"))
        linieStocMbo.setValue("CXDOCUMENTDATE",mbo.getDate("ACTUALDATE"))
        linieStocMbo.setValue("CXQTY",(-mbo.getDouble("QUANTITY")))
        linieStocMbo.setValue("UNITCOST",mbo.getDouble("UNITCOST"))
        linieStocMbo.setValue("CXREF",mbo.getString("ISSUETYPE"))
        linieStocMbo.setValue("CXREFMBO","MATRECTRANS")
        linieStocMbo.setValue("CXREFID",mbo.getLong("MATRECTRANSID"))
        linieStocMbo.setValue("DESCRIPTION",mbo.getString("DESCRIPTION"))
        linieStocMbo.setValue("GLCREDITACCT",mbo.getString("GLCREDITACCT"))
        linieStocMbo.setValue("GLDEBITACCT",mbo.getString("GLDEBITACCT"))
        linieStocMbo.setValue("CURRENCYCODE",mbo.getString("CURRENCYCODE"))
        
        linieStocMbo.getThisMboSet().save()
        
        # add for destination negative value
        linieStocMbo=cxStocuriMboSet.addAtEnd()
        
        linieStocMbo.setValue("ITEMNUM", mbo.getString("ITEMNUM"))
        linieStocMbo.setValue("SITEID",mbo.getString("FROMSITEID"))
        linieStocMbo.setValue("ORGID",mbo.getString("ORGID"))
        linieStocMbo.setValue("LOCATION",mbo.getString("TOSTORELOC"))
        linieStocMbo.setValue("COMMODITYGROUP",mbo.getString("COMMODITYGROUP"))
        linieStocMbo.setValue("CXDOCUMENTDATE",mbo.getDate("ACTUALDATE"))
        linieStocMbo.setValue("CXQTY",(mbo.getDouble("QUANTITY")))
        linieStocMbo.setValue("UNITCOST",mbo.getDouble("UNITCOST"))
        linieStocMbo.setValue("CXREF",mbo.getString("ISSUETYPE"))
        linieStocMbo.setValue("CXREFMBO","MATRECTRANS")
        linieStocMbo.setValue("CXREFID",mbo.getLong("MATRECTRANSID"))
        linieStocMbo.setValue("DESCRIPTION",mbo.getString("DESCRIPTION"))
        linieStocMbo.setValue("GLCREDITACCT",mbo.getString("GLCREDITACCT"))
        linieStocMbo.setValue("GLDEBITACCT",mbo.getString("GLDEBITACCT"))
        linieStocMbo.setValue("CURRENCYCODE",mbo.getString("CURRENCYCODE"))
        
        linieStocMbo.getThisMboSet().save()
        
        
    
    
    #   speta RECEIPT        
    if mbo.getString('ISSUETYPE') == 'RECEIPT' and shouldCreateMatRecJournal():
        
        
        # set cod tip gestiune din inventar daca are valoare acolo
        articolInventar = mbo.getMboSet('$CXArtInventar', 'INVENTORY', "location='" + str(mbo.getString("POLINE.STORELOC")) + "' and siteid=:siteid and itemnum=:itemnum").getMbo(0)
        cxStocuriMboSet=mxServer.getMboSet("CXSTOCURI", userInfo)
        service.log_info('*** XXXXXXXXXXXXXXXXXXXXXXXXXXXX ***')
        service.log_info('*** '+ mbo.getString("COMMODITYGROUP")+ '***')
        # add new line to CXSTOCURI
        linieStocMbo=cxStocuriMboSet.addAtEnd()
        
        linieStocMbo.setValue("ITEMNUM", mbo.getString("ITEMNUM"))
        linieStocMbo.setValue("SITEID",mbo.getString("SITEID"))
        linieStocMbo.setValue("ORGID",mbo.getString("ORGID"))                                                                                                   
        # get storeroom info from related POLINE - introduced by rotating assets receiving to avoid holding location
        #linieStocMbo.setValue("LOCATION",mbo.getString("TOSTORELOC"))
        linieStocMbo.setValue("LOCATION",mbo.getString("POLINE.STORELOC"))
        if mbo.isNull('CXCODCUSTODIE'):
            
            # cod gestiune din gestiunea destinatie if exists
            if articolInventar != None:
                
                cxCodTipGestiuneInv = articolInventar.getString("CXCODTIPGESTIUNE")
            if cxCodTipGestiuneInv and cxCodTipGestiuneInv.strip() != "000":
            #if cxCodTipGestiuneInv !="000":
                
                cxCodTipGestiune = cxCodTipGestiuneInv
            else:
                #service.log_info('*** else XXXXXXXXXXXXXXXXXXXXXXXXXXXX'+ mbo.getString("COMMODITYGROUP")+' ***')
                cxCodTipGestiune = mbo.getString("COMMODITYGROUP")
            linieStocMbo.setValue("COMMODITYGROUP",cxCodTipGestiune)
        else:
            linieStocMbo.setValue("COMMODITYGROUP",mbo.getString("CXCODCUSTODIE"))
        linieStocMbo.setValue("CXDOCUMENTDATE",mbo.getDate("ACTUALDATE"))
        linieStocMbo.setValue("CXQTY",mbo.getDouble("QUANTITY"))
        linieStocMbo.setValue("UNITCOST",mbo.getDouble("UNITCOST"))
        linieStocMbo.setValue("CXREF",mbo.getString("ISSUETYPE"))
        linieStocMbo.setValue("CXREFMBO","MATRECTRANS")
        linieStocMbo.setValue("CXREFID",mbo.getLong("MATRECTRANSID"))
        linieStocMbo.setValue("DESCRIPTION",mbo.getString("DESCRIPTION"))
        linieStocMbo.setValue("GLCREDITACCT",mbo.getString("GLCREDITACCT"))
        linieStocMbo.setValue("GLDEBITACCT",mbo.getString("GLDEBITACCT"))
        linieStocMbo.setValue("CURRENCYCODE",mbo.getString("CURRENCYCODE"))
        if not mbo.isNull('ROTASSETNUM'):
            linieStocMbo.setValue("ROTASSETNUM",mbo.getString("ROTASSETNUM"))   
            
        linieStocMbo.getThisMboSet().save()
    
    # speta TRANSFER
    # add 2 lines to CXSTOCURI; one for transfer out, another for transfer in
    #service.log_info('*** AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA ***')
    if mbo.getString('ISSUETYPE') == 'TRANSFER' and not mbo.isNull('FROMSTORELOC'):
        #service.log_info('*** XXXXXXXXXXXXXXXXXX XXXXXXXXXXXXXXXXXXXXXXXXXXXX ***')
        #service.log_info('*** ZZZZZZZZZZZZZZZZZZZZZZ XXXXXXXXXXXXXXXXXXXXXXXXXXXX ***')
        LocSet = mxServer.getMboSet("LOCATIONS", userInfo)
        LocSet.setWhere("location='"+mbo.getString('FROMSTORELOC')+"'")
        LocSet.reset()
        Loc = LocSet.getMbo(0)
        
        if Loc:
            tipLocDest = Loc.getString('TYPE')
            if tipLocDest!='HOLDING':
                cxStocuriMboSet=mxServer.getMboSet("CXSTOCURI", userInfo)
                # add line for transfer out
                linieStocMbo=cxStocuriMboSet.addAtEnd()
                
                linieStocMbo.setValue("ITEMNUM", mbo.getString("ITEMNUM"))
                linieStocMbo.setValue("SITEID",mbo.getString("FROMSITEID"))
                linieStocMbo.setValue("ORGID",mbo.getString("ORGID"))
                linieStocMbo.setValue("LOCATION",mbo.getString("FROMSTORELOC"))
                linieStocMbo.setValue("COMMODITYGROUP",mbo.getString("COMMODITYGROUP"))
                linieStocMbo.setValue("CXDOCUMENTDATE",mbo.getDate("ACTUALDATE"))
                #   negative qty value for exit
                linieStocMbo.setValue("CXQTY",(-mbo.getDouble("QUANTITY")))
                linieStocMbo.setValue("UNITCOST",mbo.getDouble("UNITCOST"))
                linieStocMbo.setValue("CXREF",mbo.getString("ISSUETYPE"))
                linieStocMbo.setValue("CXREFMBO","MATRECTRANS")
                linieStocMbo.setValue("CXREFID",mbo.getLong("MATRECTRANSID"))
                linieStocMbo.setValue("DESCRIPTION",mbo.getString("DESCRIPTION"))
                linieStocMbo.setValue("GLCREDITACCT",mbo.getString("GLCREDITACCT"))
                linieStocMbo.setValue("GLDEBITACCT",mbo.getString("GLDEBITACCT"))
                linieStocMbo.setValue("CURRENCYCODE",mbo.getString("CURRENCYCODE"))
                #adaugam persoana catre care se face transferul si articolul rotativ
                #linieStocMbo.setValue("ISSUETO",mbo.getString("ISSUETO"))
                #linieStocMbo.setValue("ROTASSETNUM",mbo.getString("ROTASSETNUM"))
                if not mbo.isNull('ISSUETO'):
                    linieStocMbo.setValue("ISSUETO",mbo.getString("ISSUETO"))
                if not mbo.isNull('ROTASSETNUM'):
                    linieStocMbo.setValue("ROTASSETNUM",mbo.getString("ROTASSETNUM"))                                                    
                
                linieStocMbo.getThisMboSet().save()
                
                # add line for transfer in
                linieStocMbo=cxStocuriMboSet.addAtEnd()
                
                linieStocMbo.setValue("ITEMNUM", mbo.getString("ITEMNUM"))
                linieStocMbo.setValue("SITEID",mbo.getString("SITEID"))
                linieStocMbo.setValue("ORGID",mbo.getString("ORGID"))
                linieStocMbo.setValue("LOCATION",mbo.getString("TOSTORELOC"))
                linieStocMbo.setValue("COMMODITYGROUP",mbo.getString("COMMODITYGROUP"))
                linieStocMbo.setValue("CXDOCUMENTDATE",mbo.getDate("ACTUALDATE"))
                #   negative qty value for exit
                linieStocMbo.setValue("CXQTY",(mbo.getDouble("QUANTITY")))
                linieStocMbo.setValue("UNITCOST",mbo.getDouble("UNITCOST"))
                linieStocMbo.setValue("CXREF",mbo.getString("ISSUETYPE"))
                linieStocMbo.setValue("CXREFMBO","MATRECTRANS")
                linieStocMbo.setValue("CXREFID",mbo.getLong("MATRECTRANSID"))
                linieStocMbo.setValue("DESCRIPTION",mbo.getString("DESCRIPTION"))
                linieStocMbo.setValue("GLCREDITACCT",mbo.getString("GLCREDITACCT"))
                linieStocMbo.setValue("GLDEBITACCT",mbo.getString("GLDEBITACCT"))
                linieStocMbo.setValue("CURRENCYCODE",mbo.getString("CURRENCYCODE"))
                #adaugam persoana catre care se face transferul si articolul rotativ
                #linieStocMbo.setValue("ISSUETO",mbo.getString("ISSUETO"))
                #linieStocMbo.setValue("ROTASSETNUM",mbo.getString("ROTASSETNUM"))
                if not mbo.isNull('ISSUETO'):
                    linieStocMbo.setValue("ISSUETO",mbo.getString("ISSUETO"))
                if not mbo.isNull('ROTASSETNUM'):
                    linieStocMbo.setValue("ROTASSETNUM",mbo.getString("ROTASSETNUM"))                                                    
                
                linieStocMbo.getThisMboSet().save()
                sync_labor_casare_folosinta(mbo, mxServer, userInfo)
        LocSet.close()   
    #   speta RETURN
    if mbo.getString('ISSUETYPE') == 'RETURN':
        cxStocuriMboSet=mxServer.getMboSet("CXSTOCURI", userInfo)
        # add new line to CXSTOCURI
        linieStocMbo=cxStocuriMboSet.addAtEnd()
        
        linieStocMbo.setValue("ITEMNUM", mbo.getString("ITEMNUM"))
        linieStocMbo.setValue("SITEID",mbo.getString("SITEID"))
        linieStocMbo.setValue("ORGID",mbo.getString("ORGID"))
        linieStocMbo.setValue("LOCATION",mbo.getString("TOSTORELOC"))
        linieStocMbo.setValue("COMMODITYGROUP",mbo.getString("COMMODITYGROUP"))
        linieStocMbo.setValue("CXDOCUMENTDATE",mbo.getDate("ACTUALDATE"))
        linieStocMbo.setValue("CXQTY",mbo.getDouble("QUANTITY"))
        linieStocMbo.setValue("UNITCOST",mbo.getDouble("UNITCOST"))
        linieStocMbo.setValue("CXREF",mbo.getString("ISSUETYPE"))
        linieStocMbo.setValue("CXREFMBO","MATRECTRANS")
        linieStocMbo.setValue("CXREFID",mbo.getLong("MATRECTRANSID"))
        linieStocMbo.setValue("DESCRIPTION",mbo.getString("DESCRIPTION"))
        linieStocMbo.setValue("GLCREDITACCT",mbo.getString("GLCREDITACCT"))
        linieStocMbo.setValue("GLDEBITACCT",mbo.getString("GLDEBITACCT"))
        linieStocMbo.setValue("CURRENCYCODE",mbo.getString("CURRENCYCODE"))
        
        linieStocMbo.getThisMboSet().save()
        
    #   speta VOIDRECEIPT
    if mbo.getString('ISSUETYPE') == 'VOIDRECEIPT':
        
        
        cxStocuriMboSet=mxServer.getMboSet("CXSTOCURI", userInfo)
        # add new line to CXSTOCURI
        linieStocMbo=cxStocuriMboSet.addAtEnd()
        cxCodCustodie = mbo.getString("CXCODCUSTODIE")
        linieStocMbo.setValue("ITEMNUM", mbo.getString("ITEMNUM"))
        linieStocMbo.setValue("SITEID",mbo.getString("SITEID"))
        linieStocMbo.setValue("ORGID",mbo.getString("ORGID"))
        linieStocMbo.setValue("LOCATION",mbo.getString("TOSTORELOC"))
        if codCustodieInventar != '000':
            linieStocMbo.setValue("COMMODITYGROUP",codCustodieInventar )
        elif cxCodCustodie:
            # are valoare si nu e string gol
            linieStocMbo.setValue("COMMODITYGROUP", cxCodCustodie)
        else:
            linieStocMbo.setValue("COMMODITYGROUP",mbo.getString("COMMODITYGROUP"))
        
        linieStocMbo.setValue("CXDOCUMENTDATE",mbo.getDate("ACTUALDATE"))
        linieStocMbo.setValue("CXQTY",mbo.getDouble("QUANTITY"))
        linieStocMbo.setValue("UNITCOST",mbo.getDouble("UNITCOST"))
        linieStocMbo.setValue("CXREF",mbo.getString("ISSUETYPE"))
        linieStocMbo.setValue("CXREFMBO","MATRECTRANS")
        linieStocMbo.setValue("CXREFID",mbo.getLong("MATRECTRANSID"))
        linieStocMbo.setValue("DESCRIPTION",mbo.getString("DESCRIPTION"))
        linieStocMbo.setValue("GLCREDITACCT",mbo.getString("GLCREDITACCT"))
        linieStocMbo.setValue("GLDEBITACCT",mbo.getString("GLDEBITACCT"))
        linieStocMbo.setValue("CURRENCYCODE",mbo.getString("CURRENCYCODE"))
        
        linieStocMbo.getThisMboSet().save()