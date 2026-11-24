#-------------------------------------------------------------
# AUTOSCRIPT:			CXADDTOCXFOLOSINTA
# DESCRIPTION:			Adauga linie noua in CXFOLOSINTA cu Persoana + stoc in folosinta Ob. de inventar
# AUTHOR:				Silviu Capustinschi
# Created:				27-01-2024
# LOGLEVEL:				ERROR
#-------------------------------------------------------------

from psdi.mbo import Mbo, MboConstants
from psdi.server import MXServer
from psdi.security import UserInfo
from psdi.mbo import SqlFormat

#####################################
# Running Code
#####################################

userInfo = mbo.getUserInfo()
currentDate = MXServer.getMXServer().getDate()
mxServer = MXServer.getMXServer()

if launchPoint == 'CXADDTOCXFOLOS_ACT01':
    cxFolosintaMboSet=mxServer.getMboSet("CXFOLOSINTA", userInfo)
    # adauga inregistrare noua in CXFOLOSINTA
    linieFolosintaMbo=cxFolosintaMboSet.addAtEnd()
    linieFolosintaMbo.setValue("PERSONID",mbo.getString("PERSONID"))
    linieFolosintaMbo.setValue("ROTASSETNUM",mbo.getString("ROTASSETNUM"))
    linieFolosintaMbo.setValue("ITEMNUM", mbo.getString("ITEMNUM"))
    linieFolosintaMbo.setValue("SITEID",mbo.getString("SITEID"))
    linieFolosintaMbo.setValue("ORGID",mbo.getString("ORGID"))
    linieFolosintaMbo.setValue("LOCATION",mbo.getString("LOCATION"))
    linieFolosintaMbo.setValue("COMMODITYGROUP",mbo.getString("COMMODITYGROUP"))
    linieFolosintaMbo.setValue("CXFROMDATE",mbo.getDate("CXFROMDATE"))
    linieFolosintaMbo.setValue("QUANTITY",mbo.getDouble("QUANTITY"))
    linieFolosintaMbo.setValue("UNITCOST",mbo.getDouble("UNITCOST"))
    linieFolosintaMbo.setValue("CXREFID",mbo.getLong("CXFOLOSINTAID"))
    linieFolosintaMbo.setValue("CXREFMBO", "CXFOLOSINTA")
    linieFolosintaMbo.setValue("CXNRDOC", mbo.getString("CXNRDOC"))                
    linieFolosintaMbo.getThisMboSet().save()
    #linieFolosintaMbo.getThisMboSet().close()

    #dupa ce insereaza linia noua, actualizeaza linia din CXFOLOSINTA de pe care s-a luat obiectul de inventar
    if not mbo.isNull('ROTASSETNUM'):
        mbo.getOwner().setValue("CXLADATA",mbo.getDate("CXFROMDATE"))
        mbo.getOwner().setValue("CXREFMBOTO", 'CXFOLOSINTA')
        mbo.getOwner().setValue("CXREFIDTO",linieFolosintaMbo.getLong("CXFOLOSINTAID"))
        #mbo.getOwner().getThisMboSet().save()
    else:
        origMbo = mbo.getOwner()
        cantInFolosinta = origMbo.getDouble("QUANTITY")
        if cantInFolosinta == mbo.getDouble("QUANTITY"):                               
            origMbo.setValue("CXLADATA",mbo.getDate("CXFROMDATE"))
            origMbo.setValue("CXREFMBOTO", 'CXFOLOSINTA')
            origMbo.setValue("CXREFIDTO",linieFolosintaMbo.getLong("CXFOLOSINTAID"))
            #origMbo.getThisMboSet().save()
        elif cantInFolosinta > mbo.getDouble("QUANTITY"):
            cantRamasFolosinta = cantInFolosinta - mbo.getDouble("QUANTITY")
            origMbo.setValue("CXLADATA",mbo.getDate("CXFROMDATE"))
            origMbo.setValue("QUANTITY",mbo.getDouble("QUANTITY")) 
            origMbo.setValue("CXREFMBOTO", 'CXFOLOSINTA')
            origMbo.setValue("CXREFIDTO",linieFolosintaMbo.getLong("CXFOLOSINTAID"))
            #origMbo.getThisMboSet().save()
                            
            #adauga o linie in CXFOLOSINTA cu cantiatea ramasa in folosinta la persoana initiala
            dinFolosintaNewMbo=origMbo.getThisMboSet().addAtEnd()
            dinFolosintaNewMbo.setValue("PERSONID",origMbo.getString("PERSONID"))
            #dinFolosintaNewMbo.setValue("ROTASSETNUM",dinFolosinta.getString("ROTASSETNUM"))
            dinFolosintaNewMbo.setValue("ITEMNUM", origMbo.getString("ITEMNUM"))
            dinFolosintaNewMbo.setValue("SITEID",origMbo.getString("SITEID"))
            dinFolosintaNewMbo.setValue("ORGID",origMbo.getString("ORGID"))
            dinFolosintaNewMbo.setValue("LOCATION",origMbo.getString("LOCATION"))
            dinFolosintaNewMbo.setValue("COMMODITYGROUP",origMbo.getString("COMMODITYGROUP"))
            dinFolosintaNewMbo.setValue("CXFROMDATE",origMbo.getDate("CXLADATA"))
            dinFolosintaNewMbo.setValue("QUANTITY", cantRamasFolosinta)
            dinFolosintaNewMbo.setValue("UNITCOST",origMbo.getDouble("UNITCOST"))
            dinFolosintaNewMbo.setValue("CXREFID",origMbo.getLong("CXREFID"))
            dinFolosintaNewMbo.setValue("CXREFMBO", origMbo.getString("CXREFMBO"))
            dinFolosintaNewMbo.setValue("CXNRDOC", origMbo.getString("CXNRDOC"))                
            #dinFolosintaNewMbo.getThisMboSet().save()


    service.closeDialog()