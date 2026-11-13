################################################
#
# script CXINVLIFOFIFO
#   on add/update before save
# seteaza COSTDATE pe baza
#   MATRECTRANS.ACTUALDATE
#   MATUSETRANS.ACTUALDATE
#   INVUSELINE.ACTUALDATE
#   INVTRANS.TRANSDATE
# Nu depinde de lantul getOwner(): Check FIFO salveaza INVLIFOFIFOCOST
# de pe INVENTORY, unde getOwner()/getOwner().getOwner() pot fi None.
# COSTDATE e read-only / cheie: se scrie doar la add sau daca e null.
# Update-urile de QUANTITY din Check FIFO nu trebuie sa atinga COSTDATE.
# ITEM.ROTATING=1: nu modifica INVLIFOFIFOCOST (strat qty=1 / assetnum propriu).
#
################################################

from psdi.mbo import MboConstants, SqlFormat
from psdi.server import MXServer

FLAGS = MboConstants.NOACCESSCHECK | MboConstants.NOVALIDATION_AND_NOACTION

service.log_info('*** Starting Script CXINVLIFOFIFO ***')

def item_is_rotating():
    ms = None
    try:
        if mbo.isNull("ITEMNUM"):
            return False
        ms = MXServer.getMXServer().getMboSet("ITEM", mbo.getUserInfo())
        if mbo.isNull("ITEMSETID"):
            sql = SqlFormat("ITEMNUM=:1")
            sql.setObject(1, "ITEM", "ITEMNUM", mbo.getString("ITEMNUM"))
        else:
            sql = SqlFormat("ITEMNUM=:1 AND ITEMSETID=:2")
            sql.setObject(1, "ITEM", "ITEMNUM", mbo.getString("ITEMNUM"))
            sql.setObject(2, "ITEM", "ITEMSETID", mbo.getString("ITEMSETID"))
        ms.setWhere(sql.format())
        ms.reset()
        item = ms.moveFirst()
        return item is not None and item.getBoolean("ROTATING")
    finally:
        if ms is not None:
            try:
                ms.cleanup()
            except Exception:
                pass
            try:
                ms.close()
            except Exception:
                pass

def lookup_ref(name, id_field, ref_id):
    ms = mbo.getMboSet("$CXINVLFIFO_" + name, name, id_field + " = " + str(ref_id))
    try:
        return ms.getMbo(0)
    finally:
        try:
            ms.cleanup()
        except Exception:
            pass

def set_costdate(value):
    # BMXAA0019I pe update: COSTDATE read-only / parte din cheie.
    if value is None:
        return False
    if not mbo.toBeAdded() and not mbo.isNull("COSTDATE"):
        service.log_info('*** CXINVLIFOFIFO: COSTDATE deja setat pe update; neschimbat ***')
        return False
    try:
        mbo.setValue("COSTDATE", value, FLAGS)
        return True
    except Exception:
        service.log_info('*** CXINVLIFOFIFO: COSTDATE nu poate fi scris (read-only/cheie) ***')
        return False

if item_is_rotating():
    service.log_info('*** CXINVLIFOFIFO: ROTATING=1; INVLIFOFIFOCOST neschimbat ***')
elif mbo.isNull("REFOBJECT") or mbo.isNull("REFOBJECTID"):
    service.log_info('*** CXINVLIFOFIFO: fara REFOBJECT/REFOBJECTID; COSTDATE neschimbat ***')
elif not mbo.toBeAdded() and not mbo.isNull("COSTDATE"):
    # Check FIFO (si alte update-uri pe cantitate): nu atinge Data costului.
    service.log_info('*** CXINVLIFOFIFO: update pe rand existent; COSTDATE neschimbat ***')
else:
    refObj = mbo.getString("REFOBJECT")
    refId = mbo.getLong("REFOBJECTID")
    service.log_info('*** Avem refobject ***' + refObj)
    service.log_info('*** Avem refobjectid ***' + str(refId))

    # case MATRECTRANS
    if refObj == "MATRECTRANS":
        service.log_info('*** Avem matrectrans record***')
        try:
            src = lookup_ref("MATRECTRANS", "MATRECTRANSID", refId)
            if src is None:
                service.log_info('*** MATRECTRANS %s negasit; COSTDATE neschimbat ***' % refId)
            elif src.getString("ISSUETYPE") != "ISSUE":
                set_costdate(src.getDate("ACTUALDATE"))
        except Exception:
            service.log_info('*** Err set costdate from matrectrans***')

    # case MATUSETRANS
    if refObj == "MATUSETRANS":
        service.log_info('*** Avem MATUSETRANS record***')
        try:
            src = lookup_ref("MATUSETRANS", "MATUSETRANSID", refId)
            if src is None:
                service.log_info('*** MATUSETRANS %s negasit; COSTDATE neschimbat ***' % refId)
            else:
                use_type = src.getString("ISSUETYPE") if not src.isNull("ISSUETYPE") else (
                    src.getString("USETYPE") if not src.isNull("USETYPE") else "")
                if use_type != "ISSUE":
                    set_costdate(src.getDate("ACTUALDATE"))
        except Exception:
            service.log_info('*** Err set costdate from matusetrans***')

    # case INVUSELINE
    if refObj == "INVUSELINE":
        service.log_info('*** Avem INVUSELINE record***')
        try:
            src = lookup_ref("INVUSELINE", "INVUSELINEID", refId)
            if src is None:
                service.log_info('*** INVUSELINE %s negasit; COSTDATE neschimbat ***' % refId)
            else:
                use_type = src.getString("USETYPE") if not src.isNull("USETYPE") else (
                    src.getString("ISSUETYPE") if not src.isNull("ISSUETYPE") else "")
                if use_type != "ISSUE":
                    set_costdate(src.getDate("ACTUALDATE"))
        except Exception:
            service.log_info('*** Err set costdate from invuseline***')

    # case INVTRANS
    if refObj == "INVTRANS":
        service.log_info('*** Avem INVTRANS record***')
        try:
            src = lookup_ref("INVTRANS", "INVTRANSID", refId)
            if src is None:
                service.log_info('*** INVTRANS %s negasit; COSTDATE neschimbat ***' % refId)
            elif not src.isNull("TRANSDATE"):
                set_costdate(src.getDate("TRANSDATE"))
        except Exception:
            service.log_info('*** Err set costdate from invtrans***')
