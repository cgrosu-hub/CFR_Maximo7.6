#-------------------------------------------------------------
# AUTOSCRIPT:           CXADDTOCXSTOCURI
# DESCRIPTION:          item inventory movement to CXSTOCURI
# AUTHOR:               Fernando Prajitura
# Created:              12-12-2023
# LOGLEVEL:             ERROR
# UPDATE:               21.09.2026 - Bug #1690 Corectie SHIPTRANSFER/SHIPCANCEL
# UPDATE:               30.10.2026 - Cristian Grosu - protectie update MATUSETRANS
# VERSION:              2026.10.30-MATUSETRANS-ADD-ONLY
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
        linieStocMbo.setValue("UNITCOST",mbo.getDouble("UNITCOST"))
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