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
#
################################################

service.log_info('*** Starting Script CXINVLIFOFIFO ***')

def lookup_ref(name, id_field, ref_id):
    ms = mbo.getMboSet("$CXINVLFIFO_" + name, name, id_field + " = " + str(ref_id))
    try:
        return ms.getMbo(0)
    finally:
        # ponytail: set temporar pe acelasi MBO; cleanup e suficient, fara close agresiv.
        try:
            ms.cleanup()
        except Exception:
            pass

if mbo.isNull("REFOBJECT") or mbo.isNull("REFOBJECTID"):
    service.log_info('*** CXINVLIFOFIFO: fara REFOBJECT/REFOBJECTID; COSTDATE neschimbat ***')
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
            if src is not None and src.getString("ISSUETYPE") != "ISSUE":
                mbo.setValue("COSTDATE", src.getDate("ACTUALDATE"))
            elif src is None:
                service.log_info('*** MATRECTRANS %s negasit; COSTDATE neschimbat ***' % refId)
        except Exception:
            service.log_info('*** Err set costdate from matrectrans***')

    # case MATUSETRANS
    if refObj == "MATUSETRANS":
        service.log_info('*** Avem MATUSETRANS record***')
        try:
            src = lookup_ref("MATUSETRANS", "MATUSETRANSID", refId)
            # USETYPE pe unele configuratii; ISSUETYPE e campul standard Maximo.
            use_type = src.getString("ISSUETYPE") if src is not None and not src.isNull("ISSUETYPE") else (
                src.getString("USETYPE") if src is not None and not src.isNull("USETYPE") else "")
            if src is not None and use_type != "ISSUE":
                mbo.setValue("COSTDATE", src.getDate("ACTUALDATE"))
            elif src is None:
                service.log_info('*** MATUSETRANS %s negasit; COSTDATE neschimbat ***' % refId)
        except Exception:
            service.log_info('*** Err set costdate from matusetrans***')

    # case INVUSELINE
    if refObj == "INVUSELINE":
        service.log_info('*** Avem INVUSELINE record***')
        try:
            src = lookup_ref("INVUSELINE", "INVUSELINEID", refId)
            use_type = src.getString("USETYPE") if src is not None and not src.isNull("USETYPE") else (
                src.getString("ISSUETYPE") if src is not None and not src.isNull("ISSUETYPE") else "")
            if src is not None and use_type != "ISSUE":
                mbo.setValue("COSTDATE", src.getDate("ACTUALDATE"))
            elif src is None:
                service.log_info('*** INVUSELINE %s negasit; COSTDATE neschimbat ***' % refId)
        except Exception:
            service.log_info('*** Err set costdate from invuseline***')

    # case INVTRANS
    if refObj == "INVTRANS":
        service.log_info('*** Avem INVTRANS record***')
        try:
            src = lookup_ref("INVTRANS", "INVTRANSID", refId)
            if src is not None and not src.isNull("TRANSDATE"):
                mbo.setValue("COSTDATE", src.getDate("TRANSDATE"))
            elif src is None:
                service.log_info('*** INVTRANS %s negasit; COSTDATE neschimbat ***' % refId)
        except Exception:
            service.log_info('*** Err set costdate from invtrans***')
