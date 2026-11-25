#-------------------------------------------------------------
# AUTOSCRIPT:			CXADDTOCXFOLOSINTA
# DESCRIPTION:			Adauga linie noua in CXFOLOSINTA cu Persoana + stoc in folosinta Ob. de inventar
# AUTHOR:				Silviu Capustinschi
# Created:				27-01-2024
# LOGLEVEL:				ERROR
# UPDATE:				25.11.2026 - nu mai insera o copie; dialogul salveaza singur randul nou
#-------------------------------------------------------------

from psdi.mbo import MboConstants

#####################################
# Running Code
#####################################

if launchPoint == 'CXADDTOCXFOLOS_ACT01':
    # mbo este randul nou din dialog. closeDialog() il salveaza.
    # O a doua linie pe un MboSet separat ramanea si ea, cu aceleasi valori.
    owner = mbo.getOwner()
    flags = MboConstants.NOACCESSCHECK
    mbo.setValue("CXREFMBO", "CXFOLOSINTA", flags)
    mbo.setValue("CXREFID", owner.getLong("CXFOLOSINTAID"), flags)

    #dupa ce insereaza linia noua, actualizeaza linia din CXFOLOSINTA de pe care s-a luat obiectul de inventar
    if not mbo.isNull('ROTASSETNUM'):
        owner.setValue("CXLADATA", mbo.getDate("CXFROMDATE"))
        owner.setValue("CXREFMBOTO", "CXFOLOSINTA")
        owner.setValue("CXREFIDTO", mbo.getLong("CXFOLOSINTAID"))
    else:
        origMbo = owner
        cantInFolosinta = origMbo.getDouble("QUANTITY")
        if cantInFolosinta == mbo.getDouble("QUANTITY"):
            origMbo.setValue("CXLADATA", mbo.getDate("CXFROMDATE"))
            origMbo.setValue("CXREFMBOTO", "CXFOLOSINTA")
            origMbo.setValue("CXREFIDTO", mbo.getLong("CXFOLOSINTAID"))
        elif cantInFolosinta > mbo.getDouble("QUANTITY"):
            cantRamasFolosinta = cantInFolosinta - mbo.getDouble("QUANTITY")
            origMbo.setValue("CXLADATA", mbo.getDate("CXFROMDATE"))
            origMbo.setValue("QUANTITY", mbo.getDouble("QUANTITY"))
            origMbo.setValue("CXREFMBOTO", "CXFOLOSINTA")
            origMbo.setValue("CXREFIDTO", mbo.getLong("CXFOLOSINTAID"))

            #adauga o linie in CXFOLOSINTA cu cantiatea ramasa in folosinta la persoana initiala
            dinFolosintaNewMbo = origMbo.getThisMboSet().addAtEnd()
            dinFolosintaNewMbo.setValue("PERSONID", origMbo.getString("PERSONID"))
            dinFolosintaNewMbo.setValue("ITEMNUM", origMbo.getString("ITEMNUM"))
            dinFolosintaNewMbo.setValue("SITEID", origMbo.getString("SITEID"))
            dinFolosintaNewMbo.setValue("ORGID", origMbo.getString("ORGID"))
            dinFolosintaNewMbo.setValue("LOCATION", origMbo.getString("LOCATION"))
            dinFolosintaNewMbo.setValue("COMMODITYGROUP", origMbo.getString("COMMODITYGROUP"))
            dinFolosintaNewMbo.setValue("CXFROMDATE", origMbo.getDate("CXLADATA"))
            dinFolosintaNewMbo.setValue("QUANTITY", cantRamasFolosinta)
            dinFolosintaNewMbo.setValue("UNITCOST", origMbo.getDouble("UNITCOST"))
            dinFolosintaNewMbo.setValue("CXREFID", origMbo.getLong("CXREFID"))
            dinFolosintaNewMbo.setValue("CXREFMBO", origMbo.getString("CXREFMBO"))
            dinFolosintaNewMbo.setValue("CXNRDOC", origMbo.getString("CXNRDOC"))

    service.closeDialog()
