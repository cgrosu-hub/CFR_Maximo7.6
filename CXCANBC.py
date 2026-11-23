###############################################
#
#   CXCANBC script - INVUSE
#   Author: Cristian Grosu / Irina Prodan
#   Version: 17.1 DRAFT - rotating SQL rules + mesaj eroare relevant
#   Launchpoint: Buton CXCANBC de pe Bon Consum (INVUSE)
#   Anulare Bon Consum / Transfer CFR
#   v13.6: fix postcheck pentru mai multe linii cu acelasi ITEMNUM
#   v13.9: SHIPPED precheck stoc + suport multi-split rotating per transfer/receipt
#   v13.9.1: cleanup ASSETTRANS + CXFOLOSINTA legat exact de SHIPRECEIPT
#   v16: INVUSE/INVUSELINE pastrate; STATUS=CANCELLED
#   v17 rotating=1:
#     - sterge INVUSELINESPLIT; pastreaza INVUSELINE
#     - FARA UPDATE CXSTOCURI.CXCURBAL / INVBALANCES (CHECK FIFO manual)
#     - INVLIFOFIFOCOST: UPDATE LOCATION->FROMSTORELOC (fara DELETE, fara INSERT)
#     - INSERT doar INVUSESTATUS
#     - DELETE: ASSETTRANS, CXFOLOSINTA(dest), CXSTOCURI x2, MATRECTRANS
#     - CXFOLOSINTA (reguli CXADDTOCXFOLOSINTA):
#         * dest (CXREFMBO=MATRECTRANS) trebuie sa fie varful lantului
#           (CXLADATA/CXREFMBOTO/CXREFIDTO NULL, fara copil CXREFMBO=CXFOLOSINTA)
#         * daca exista sursa inchisa pe CXREFMBOTO/CXREFIDTO -> REOPEN
#           (NULL pe CXLADATA/CXREFMBOTO/CXREFIDTO), apoi DELETE dest
#
###############################################
from psdi.server import MXServer
from java.sql import Connection, Statement, ResultSet
from psdi.mbo import Mbo
from psdi.util import MXApplicationException
from java.math import BigDecimal
mxserver = MXServer.getMXServer(); userInfo = mxserver.getSystemUserInfo(); service.log_info('*** Starting Script CXCANBC - INVUSE ***')
# Mbo-ul curent de pe obiectul INVUSE
invuse_mbo = mbo
if invuse_mbo is None:
    service.log_info('*** No current INVUSE Mbo, exiting ***')
    raise MXApplicationException("CXANULARE", "NOMBO")
invusenum   = invuse_mbo.getString("INVUSENUM"); invuseid    = invuse_mbo.getLong("INVUSEID"); status      = invuse_mbo.getString("STATUS"); usetype     = invuse_mbo.getString("USETYPE"); orgid       = invuse_mbo.getString("ORGID"); siteid      = invuse_mbo.getString("SITEID"); fromstoreloc = invuse_mbo.getString("FROMSTORELOC")
service.log_info( '*** INVUSENUM = %s, INVUSEID = %s, STATUS = %s, USETYPE = %s ***' % (invusenum, str(invuseid), status, usetype) )
# 1. Conditii de rulare:
#    - status = COMPLETE
#    - sau status = SHIPPED si USETYPE = TRANSFER
#    - exista cel putin o linie in INVUSELINE
linesSet = invuse_mbo.getMboSet("INVUSELINE"); conditii_ok = True
if status not in ("COMPLETE", "SHIPPED"): service.log_info('*** Status nu este COMPLETE sau SHIPPED, nu se ruleaza scriptul ***'); conditii_ok = False
if status == "SHIPPED" and usetype != "TRANSFER": service.log_info('*** Status SHIPPED permis doar pentru USETYPE=TRANSFER ***'); service.error("CXANULARE", "NECESITASUPORT", [invusenum, "Bonul SHIPPED cu tipul %s necesita verificare de suport." % usetype])
if status == "SHIPPED": service.error("CXANULARE", "NECESITASUPORT", [invusenum, "Provenienta FIFO a transferului SHIPPED nu este inca validata pentru anulare automata."])
if linesSet is None or linesSet.isEmpty():
    service.log_info('*** Nu exista linii INVUSELINE, nu se ruleaza scriptul ***'); conditii_ok = False
# daca nu sunt indeplinite conditiile -> afisam mesaj si oprim
if not conditii_ok:
    raise MXApplicationException("CXANULARE", "CONDITII")
# 2. Obtinem conexiune DB (pe obiectul INVUSE)
currentSet = mxserver.getMboSet("INVUSE", userInfo); currentMbo = currentSet.getMbo(0); con = currentMbo.getMboServer().getDBConnection(userInfo.getConnectionKey()); schema = currentMbo.getMboServer().getSchemaOwner().upper(); s = con.createStatement()
def build_cxcurbal_rebase_plan(partitions, target_ids):
    """Calculeaza doar efectul bonului, dupa cheia/ordinea CXSTOCURIUPDATECURBAL."""
    plan = []; found_target_ids = set()
    for item, location, site, group, cost in sorted(partitions):
        rows_sql = ( "SELECT CXSTOCURIID, CXDOCUMENTDATE, CXREFID, CXREF, CXQTY, CXCURBAL " "FROM CXSTOCURI WHERE ITEMNUM='%s' AND LOCATION='%s' " "AND SITEID='%s' AND COMMODITYGROUP='%s' AND UNITCOST=%s " "ORDER BY CXDOCUMENTDATE, CXREFID" % (item.replace("'", "''"), location.replace("'", "''"), site.replace("'", "''"), group.replace("'", "''"), cost) )
        rs = s.executeQuery(rows_sql); rows = []
        while rs.next():
            refid = rs.getLong(3)
            if rs.wasNull(): refid = None
            rows.append((rs.getLong(1), rs.getTimestamp(2), refid, rs.getString(4), rs.getBigDecimal(5), rs.getBigDecimal(6)))
        rs.close(); removed_qty = BigDecimal("0"); previous_order_key = None
        for rowid, document_date, refid, ref, qty, old_balance in rows:
            if document_date is None: raise Exception("CXCURBAL: CXDOCUMENTDATE lipsa pentru CXSTOCURIID=%s" % str(rowid))
            order_key = (str(document_date), refid)
            if order_key == previous_order_key: raise Exception("CXCURBAL: ordine ambigua CXDOCUMENTDATE/CXREFID pentru CXSTOCURIID=%s" % str(rowid))
            previous_order_key = order_key
            if ref == "INITIAL":
                if rowid in target_ids: raise Exception("CXCURBAL: nu se poate elimina un rand INITIAL, CXSTOCURIID=%s" % str(rowid))
                removed_qty = BigDecimal("0")
                continue
            if rowid in target_ids:
                if qty is None: raise Exception("CXCURBAL: CXQTY lipsa pe randul de anulat, CXSTOCURIID=%s" % str(rowid))
                found_target_ids.add(rowid); removed_qty = removed_qty.add(qty)
            elif removed_qty.signum() != 0:
                if old_balance is None: raise Exception("CXCURBAL: sold ulterior lipsa, CXSTOCURIID=%s" % str(rowid))
                plan.append((rowid, old_balance, old_balance.subtract(removed_qty)))
    if found_target_ids != target_ids: raise Exception("CXCURBAL: nu au fost gasite toate randurile de anulat in partitiile validate")
    return plan
def apply_cxcurbal_rebase_plan(plan):
    """Aplica ajustarile in tranzactia bonului, dupa stergerea randurilor tinta."""
    for rowid, old_balance, new_balance in plan:
        update_sql = ( "UPDATE CXSTOCURI SET CXCURBAL=%s " "WHERE CXSTOCURIID=%s AND CXCURBAL=%s" % (str(new_balance), str(rowid), str(old_balance)) )
        if s.executeUpdate(update_sql) != 1: raise Exception("CXCURBAL: rand modificat concurent, CXSTOCURIID=%s" % str(rowid))
def preflight_reason(error):
    """Motiv relevant pentru utilizator = textul exceptiei (scurtat); jurnalul pastreaza tot."""
    detail = str(error).strip()
    if not detail: return "Verificarile automate au esuat fara detalii."
    # Mesajele de exceptie din script sunt deja in romana si actionabile.
    # Nu le mai comprimam in formule generice (ex. FIFO -> "stratului de cost").
    if len(detail) > 240: return detail[:237] + "..."
    return detail
phase = "setup"; committed = False
try:
    service.log_info('*** CXCANBC - START DB OPERATIONS ***')
    if con.getAutoCommit(): raise Exception("CXCANBC necesita tranzactie DB cu AutoCommit dezactivat pentru rollback complet")
    phase = "preflight"
    if usetype == "TRANSFER":
        # Nu trimitem un bon cu tranzactii de consum in ramura de transfer.
        # Exemplele MIXED din TEST arata ca tipul din antet nu e suficient;
        # aici validam explicit ca ramura aleasa contine doar transferuri.
        matuseCountSql = "SELECT COUNT(*) FROM MATUSETRANS WHERE INVUSEID=%s" % str(invuseid); rsMatuseCount = s.executeQuery(matuseCountSql); rsMatuseCount.next(); matuse_count = rsMatuseCount.getInt(1); rsMatuseCount.close()
        if matuse_count != 0: raise Exception("CXCANBC v14: bonul TRANSFER are %s MATUSETRANS; anularea necesita ramura mixta" % str(matuse_count))
        check_line = linesSet.moveFirst()
        while check_line:
            if check_line.getString("USETYPE") != "TRANSFER": raise Exception("CXCANBC v14: INVUSELINEID=%s are USETYPE=%s, diferit de TRANSFER" % (str(check_line.getLong("INVUSELINEID")), check_line.getString("USETYPE")))
            check_line = linesSet.moveNext()
    # 3. Anulare status COMPLETE
    #    v13.5:
    #    - NON-TRANSFER: pastreaza logica v12 neschimbata
    #    - COMPLETE + TRANSFER, same-site, rotating:
    #         1) STOREROOM -> LABOR (validat in v13.1)
    #         2) LABOR -> LABOR CASARE (validat in v13.2)
#         3) LABOR -> LABOR normal, non-CASARE (nou in v13.3)
    #      Celelalte spete COMPLETE + TRANSFER raman blocate pana sunt implementate/testate.
    if status == "COMPLETE":
        if usetype == "TRANSFER":
            service.log_info('*** CXCANBC v13.3 - COMPLETE TRANSFER PRECHECK ***')
            # -----------------------------------------------------------------
            # PRECHECK GLOBAL - niciun UPDATE/DELETE nu se executa pana cand
            # TOATE liniile bonului nu sunt validate.
            # -----------------------------------------------------------------
            # Tip locatie sursa, conform aceleiasi reguli folosite in CXINVUSELINE:
            # LOCATIONS.TYPE = STOREROOM / LABOR
            sourceTypeSql = ( "SELECT TYPE FROM LOCATIONS " "WHERE LOCATION = '%s' AND ORGID = '%s' AND SITEID = '%s' " "FETCH FIRST 1 ROW ONLY" % ( fromstoreloc.replace("'", "''"), orgid.replace("'", "''"), siteid.replace("'", "''") ) ); service.log_info('*** SOURCE TYPE SELECT *** ' + sourceTypeSql); rsSourceType = s.executeQuery(sourceTypeSql)
            if not rsSourceType.next():
                rsSourceType.close()
                raise Exception("Nu exista LOCATIONS pentru FROMSTORELOC=%s, SITEID=%s" % (fromstoreloc, siteid))
            source_type = rsSourceType.getString(1); rsSourceType.close()
            if source_type not in ("STOREROOM", "LABOR"): raise Exception( "CXCANBC v13.3: COMPLETE TRANSFER neimplementat pentru sursa TYPE=%s." % source_type )
            transfer_rows = []; detected_case = None; validated_matrectrans_ids = []; validated_assettrans_ids = []; validated_cxfolosinta_ids = []; validated_cxfolosinta_reopen_ids = []; validated_cx_partitions = set(); validated_cx_ids = set(); line = linesSet.moveFirst()
            while line:
                invuselineid = line.getLong("INVUSELINEID"); itemnum      = line.getString("ITEMNUM"); quantity     = line.getDouble("QUANTITY"); rotasset     = line.getString("ROTASSETNUM"); line_fromstoreloc = line.getString("FROMSTORELOC"); tostoreloc   = line.getString("TOSTORELOC"); tositeid     = line.getString("TOSITEID")
                if line_fromstoreloc != fromstoreloc: raise Exception( "INVUSELINEID=%s are FROMSTORELOC diferit de antet: %s / %s" % (str(invuselineid), line_fromstoreloc, fromstoreloc) )
                if not tositeid:
                    tositeid = siteid
                # v13.1 = doar transfer in cadrul aceluiasi site
                if tositeid != siteid: raise Exception( "CXCANBC v13.3: transfer intre site-uri neimplementat. " "INVUSELINEID=%s, SITEID=%s, TOSITEID=%s" % (str(invuselineid), siteid, tositeid) )
                if not tostoreloc:
                    raise Exception("CXCANBC v13.3: TOSTORELOC lipsa pentru INVUSELINEID=%s" % str(invuselineid))
                # Destinatia trebuie sa fie LABOR.
                destTypeSql = ( "SELECT TYPE FROM LOCATIONS " "WHERE LOCATION = '%s' AND ORGID = '%s' AND SITEID = '%s' " "FETCH FIRST 1 ROW ONLY" % ( tostoreloc.replace("'", "''"), orgid.replace("'", "''"), tositeid.replace("'", "''") ) ); service.log_info('*** DEST TYPE SELECT *** ' + destTypeSql); rsDestType = s.executeQuery(destTypeSql)
                if not rsDestType.next():
                    rsDestType.close()
                    raise Exception( "Nu exista LOCATIONS pentru TOSTORELOC=%s, SITEID=%s" % (tostoreloc, tositeid) )
                dest_type = rsDestType.getString(1); rsDestType.close()
                # Clasificam speta implementata. Toate liniile aceluiasi bon trebuie sa
                # apartina aceleiasi spete; nu permitem amestecarea handlerelor.
                current_case = None
                if source_type == "STOREROOM" and dest_type == "LABOR": current_case = "STOREROOM_LABOR"
                elif source_type == "LABOR" and dest_type == "LABOR" and "CASARE" in tostoreloc.upper(): current_case = "LABOR_LABOR_CASARE"
                elif source_type == "LABOR" and dest_type == "LABOR":
                    if fromstoreloc == tostoreloc: raise Exception( "CXCANBC v13.3: LABOR -> LABOR cu aceeasi locatie sursa/destinatie nu este permis. " "INVUSELINEID=%s, LOCATION=%s" % (str(invuselineid), tostoreloc) )
                    current_case = "LABOR_LABOR_NORMAL"
                else: raise Exception( "CXCANBC v13.3: COMPLETE TRANSFER neimplementat pentru %s -> %s, TOSTORELOC=%s. " "Sunt permise STOREROOM -> LABOR, LABOR -> LABOR CASARE si LABOR -> LABOR normal. INVUSELINEID=%s" % (source_type, dest_type, tostoreloc, str(invuselineid)) )
                if detected_case is None: detected_case = current_case
                elif detected_case != current_case:
                    raise Exception( "CXCANBC v13.3: bonul contine spete COMPLETE TRANSFER diferite (%s / %s); anularea este blocata" % (detected_case, current_case) )
                # v13.7 - COMPLETE TRANSFER rotating:
                # - cazul existent: INVUSELINE qty=1 + ROTASSETNUM + 1 MATRECTRANS
                # - INVUSELINE poate avea ROTASSETNUM gol: Maximo poate pune
                #   activul doar pe MATRECTRANS, fie pentru qty=1 (30840),
                #   fie pentru qty>1 cu cate un activ pe tranzactie.
                # Soldurile initiale se citesc o singura data pentru linia/itemul curent.
                sourceBalSql = ( "SELECT CURBAL FROM INVBALANCES " "WHERE ITEMNUM = '%s' AND LOCATION = '%s' AND SITEID = '%s' " "FETCH FIRST 1 ROW ONLY" % ( itemnum.replace("'", "''"), fromstoreloc.replace("'", "''"), siteid.replace("'", "''") ) ); rsSourceBal = s.executeQuery(sourceBalSql)
                if not rsSourceBal.next():
                    rsSourceBal.close()
                    raise Exception("Lipseste INVBALANCES sursa pentru ITEMNUM=%s LOCATION=%s" % (itemnum, fromstoreloc))
                source_curbal_before = rsSourceBal.getDouble(1); rsSourceBal.close(); destBalSql = ( "SELECT CURBAL FROM INVBALANCES " "WHERE ITEMNUM = '%s' AND LOCATION = '%s' AND SITEID = '%s' " "FETCH FIRST 1 ROW ONLY" % ( itemnum.replace("'", "''"), tostoreloc.replace("'", "''"), siteid.replace("'", "''") ) ); rsDestBal = s.executeQuery(destBalSql)
                if not rsDestBal.next():
                    rsDestBal.close()
                    raise Exception("Lipseste INVBALANCES destinatie pentru ITEMNUM=%s LOCATION=%s" % (itemnum, tostoreloc))
                dest_curbal_before = rsDestBal.getDouble(1); rsDestBal.close()
                # Citim TOATE MATRECTRANS TRANSFER ale liniei.
                matrecSql = ( "SELECT MATRECTRANSID, UNITCOST, ACTUALDATE, FROMSTORELOC, TOSTORELOC, QUANTITY, ROTASSETNUM, ITEMNUM, SITEID, FROMSITEID " "FROM MATRECTRANS " "WHERE INVUSEID = %s AND INVUSELINEID = %s AND ISSUETYPE = 'TRANSFER' " "ORDER BY MATRECTRANSID" % (str(invuseid), str(invuselineid)) )
                service.log_info('*** COMPLETE TRANSFER MATRECTRANS SELECT v13.7 *** ' + matrecSql); rsMat = s.executeQuery(matrecSql); mat_rows = []
                while rsMat.next(): mat_rows.append(( rsMat.getLong(1), rsMat.getDouble(2), rsMat.getTimestamp(3), rsMat.getString(4), rsMat.getString(5), rsMat.getDouble(6), rsMat.getString(7), rsMat.getString(8), rsMat.getString(9), rsMat.getString(10) ))
                rsMat.close()
                if len(mat_rows) == 0: raise Exception("Nu exista MATRECTRANS ISSUETYPE=TRANSFER pentru INVUSELINEID=%s" % str(invuselineid))
                mat_qty_total = 0.0
                for mat_row in mat_rows: mat_qty_total += mat_row[5]
                if abs(mat_qty_total - quantity) > 0.000001:
                    raise Exception( "CXCANBC v13.7: suma MATRECTRANS nu corespunde INVUSELINE. " "INVUSELINEID=%s LINE_QTY=%s MAT_QTY_TOTAL=%s" % (str(invuselineid), str(quantity), str(mat_qty_total)) )
                # Compatibilitate cu toate cazurile v13.6:
                # daca INVUSELINE are ROTASSETNUM, ramane obligatoriu qty=1 + un singur MATRECTRANS.
                if rotasset:
                    if quantity != 1.0 or len(mat_rows) != 1: raise Exception( "CXCANBC v13.7: linia cu ROTASSETNUM trebuie sa aiba QTY=1 si exact 1 MATRECTRANS. " "INVUSELINEID=%s QTY=%s NR_MAT=%s" % (str(invuselineid), str(quantity), str(len(mat_rows))) )
                    if mat_rows[0][6] != rotasset: raise Exception( "CXCANBC v13.7: ROTASSETNUM MATRECTRANS diferit de INVUSELINE. INVUSELINEID=%s" % str(invuselineid) )
                else:
                    # Sursa adevarului pentru activ este tranzactia generata.
                    # O linie qty=1 fara activ pe linie este acceptata doar
                    # daca are exact o tranzactie rotating qty=1. Altfel,
                    # ramura non-rotating ramane neimplementata.
                    if quantity == 1.0 and (len(mat_rows) != 1 or mat_rows[0][5] != 1.0 or not mat_rows[0][6]): raise Exception( "CXCANBC v14: linie fara ROTASSETNUM, fara o singura tranzactie rotating qty=1. " "INVUSELINEID=%s ITEMNUM=%s" % (str(invuselineid), itemnum) )
                    if quantity < 1.0:
                        raise Exception( "CXCANBC v14: cantitate nepermisa pentru linie fara ROTASSETNUM. " "INVUSELINEID=%s QTY=%s" % (str(invuselineid), str(quantity)) )
                # Fiecare MATRECTRANS devine o unitate separata in transfer_rows.
                for mat_row in mat_rows:
                    matrectransid = mat_row[0]; transfer_unitcost = mat_row[1]; transfer_date = mat_row[2]; mat_from = mat_row[3]; mat_to = mat_row[4]; mat_qty = mat_row[5]; mat_rotasset = mat_row[6]
                    if mat_row[7] != itemnum or mat_row[8] != siteid or mat_row[9] != siteid: raise Exception( "MATRECTRANS are ITEMNUM/SITEID/FROMSITEID diferite pentru INVUSELINEID=%s, MATRECTRANSID=%s" % (str(invuselineid), str(matrectransid)) )
                    if mat_from != fromstoreloc or mat_to != tostoreloc: raise Exception( "MATRECTRANS nu corespunde locatiei liniei. INVUSELINEID=%s MATRECTRANSID=%s" % (str(invuselineid), str(matrectransid)) )
                    if mat_qty != 1.0 or not mat_rotasset:
                        raise Exception( "CXCANBC v13.7: MATRECTRANS split trebuie sa fie rotating QTY=1. " "MATRECTRANSID=%s QTY=%s ROTASSETNUM=%s" % (str(matrectransid), str(mat_qty), str(mat_rotasset)) )
                    # Assetul trebuie sa fie in destinatie.
                    assetSql = ( "SELECT LOCATION FROM ASSET " "WHERE ASSETNUM = '%s' AND SITEID = '%s' FETCH FIRST 1 ROW ONLY" % (mat_rotasset.replace("'", "''"), siteid.replace("'", "''")) ); rsAsset = s.executeQuery(assetSql)
                    if not rsAsset.next():
                        rsAsset.close()
                        raise Exception("Nu exista ASSET=%s SITEID=%s" % (mat_rotasset, siteid))
                    asset_location = rsAsset.getString(1); rsAsset.close()
                    if asset_location != tostoreloc:
                        raise Exception( "Assetul %s nu este in destinatia %s (este in %s). Anularea este blocata." % (mat_rotasset, tostoreloc, asset_location) )
                    # FIFO exact, qty=1, creat de MATRECTRANS.
                    destFifoSql = ( "SELECT INVLIFOFIFOCOSTID, QUANTITY, UNITCOST " "FROM INVLIFOFIFOCOST " "WHERE ITEMNUM = '%s' AND LOCATION = '%s' AND SITEID = '%s' " "AND REFOBJECT = 'MATRECTRANS' AND REFOBJECTID = %s " "ORDER BY INVLIFOFIFOCOSTID" % ( itemnum.replace("'", "''"), tostoreloc.replace("'", "''"), siteid.replace("'", "''"), str(matrectransid) ) )
                    rsFifo = s.executeQuery(destFifoSql)
                    if not rsFifo.next():
                        rsFifo.close()
                        raise Exception( "Nu exista FIFO destinatie pentru MATRECTRANSID=%s ITEMNUM=%s LOCATION=%s" % (str(matrectransid), itemnum, tostoreloc) )
                    dest_fifo_id = rsFifo.getLong(1); dest_fifo_qty = rsFifo.getDouble(2); dest_fifo_cost = rsFifo.getDouble(3)
                    if rsFifo.next():
                        rsFifo.close()
                        raise Exception("Exista mai multe FIFO-uri destinatie pentru MATRECTRANSID=%s" % str(matrectransid))
                    rsFifo.close()
                    if dest_fifo_qty != 1.0: raise Exception( "FIFO rotating destinatie trebuie sa aiba QUANTITY=1. MATRECTRANSID=%s QTY=%s" % (str(matrectransid), str(dest_fifo_qty)) )
                    if abs(dest_fifo_cost - transfer_unitcost) > 0.000001:
                        raise Exception( "FIFO destinatie are cost diferit de MATRECTRANSID=%s" % str(matrectransid) )
                    # Refacem stratul exact al activului, nu un strat nou fara provenienta.
                    # Daca exista mai multe intrari posibile sau data stratului nu poate fi sustinuta, blocam bonul in PRECHECK.
                    originSql = ( "SELECT MATRECTRANSID, ISSUETYPE, ACTUALDATE FROM MATRECTRANS " "WHERE ROTASSETNUM='%s' AND ITEMNUM='%s' AND SITEID='%s' AND TOSTORELOC='%s' " "AND QUANTITY=1 AND ABS(UNITCOST-%s)<0.000001 AND MATRECTRANSID<>%s " "AND TRANSDATE<(SELECT TRANSDATE FROM MATRECTRANS WHERE MATRECTRANSID=%s) " "ORDER BY TRANSDATE DESC, MATRECTRANSID DESC" % (mat_rotasset.replace("'", "''"), itemnum.replace("'", "''"), siteid.replace("'", "''"), fromstoreloc.replace("'", "''"), str(transfer_unitcost), str(matrectransid), str(matrectransid)) ); rsOrigin = s.executeQuery(originSql); origins = []
                    while rsOrigin.next(): origins.append((rsOrigin.getLong(1), rsOrigin.getString(2), rsOrigin.getTimestamp(3)))
                    rsOrigin.close()
                    if len(origins) != 1 or origins[0][2] is None: raise Exception("FIFO: provenienta sursa neidentificata unic pentru activul %s" % mat_rotasset)
                    origin_id, origin_issuetype, origin_actualdate = origins[0]
                    originExistingSql = ("SELECT COUNT(*) FROM INVLIFOFIFOCOST WHERE ITEMNUM='%s' AND SITEID='%s' AND LOCATION='%s' AND REFOBJECT='MATRECTRANS' AND REFOBJECTID=%s" % (itemnum.replace("'", "''"), siteid.replace("'", "''"), fromstoreloc.replace("'", "''"), str(origin_id)))
                    rsOriginExisting = s.executeQuery(originExistingSql); rsOriginExisting.next(); origin_existing = rsOriginExisting.getInt(1); rsOriginExisting.close()
                    if origin_existing != 0: raise Exception("FIFO: stratul original %s exista deja in sursa" % str(origin_id))
                    # Scriptul CXINVLIFOFIFO seteaza COSTDATE din MATRECTRANS.ACTUALDATE,
                    # cu exceptia ISSUETYPE=ISSUE; folosim aceeasi regula la restaurare.
                    if origin_issuetype == 'ISSUE' or origin_actualdate is None: raise Exception("FIFO: MATRECTRANS origine nu poate furniza COSTDATE pentru activul %s" % mat_rotasset)
                    origin_costdate = origin_actualdate
                    # CXSTOCURI exact -1 sursa / +1 destinatie.
                    cxSql = ( "SELECT ITEMNUM, SITEID, LOCATION, CXREF, CXQTY, UNITCOST, COMMODITYGROUP, CXSTOCURIID FROM CXSTOCURI " "WHERE CXREFMBO='MATRECTRANS' AND CXREFID=%s ORDER BY CXSTOCURIID" % str(matrectransid) ); rsCx = s.executeQuery(cxSql); cx_rows = []
                    while rsCx.next():
                        cx_cost_decimal = rsCx.getBigDecimal(6)
                        if cx_cost_decimal is None:
                            rsCx.close()
                            raise Exception("CXSTOCURI UNITCOST lipsa pentru MATRECTRANSID=%s" % str(matrectransid))
                        cx_rows.append((rsCx.getString(1), rsCx.getString(2), rsCx.getString(3), rsCx.getString(4), rsCx.getDouble(5), cx_cost_decimal, rsCx.getString(7), rsCx.getLong(8)))
                    rsCx.close(); source_cx_ok = False; dest_cx_ok = False
                    for (cx_item, cx_site, cx_location, cx_ref, cx_qty, cx_cost, cx_group, cx_id) in cx_rows:
                        if cx_item != itemnum or cx_site != siteid or cx_ref != "TRANSFER" or abs(cx_cost.doubleValue() - transfer_unitcost) > 0.000001: raise Exception( "CXSTOCURI nu corespunde articolului/site-ului/tipului/costului pentru MATRECTRANSID=%s" % str(matrectransid) )
                        if not cx_group: raise Exception("CXSTOCURI COMMODITYGROUP lipsa pentru MATRECTRANSID=%s" % str(matrectransid))
                        if cx_location == fromstoreloc and cx_qty == -1.0: source_cx_ok = True
                        if cx_location == tostoreloc and cx_qty == 1.0: dest_cx_ok = True
                    if len(cx_rows) != 2 or not source_cx_ok or not dest_cx_ok: raise Exception( "CXSTOCURI nu are pattern-ul asteptat pentru MATRECTRANSID=%s" % str(matrectransid) )
                    for (cx_item, cx_site, cx_location, cx_ref, cx_qty, cx_cost, cx_group, cx_id) in cx_rows:
                        validated_cx_partitions.add((cx_item, cx_location, cx_site, cx_group, str(cx_cost)))
                        if cx_id in validated_cx_ids: raise Exception("CXSTOCURIID duplicat in bon=%s" % str(cx_id))
                        validated_cx_ids.add(cx_id)
                    # Stergerea tranzactiei trebuie sa elimine si efectele secundare
                    # legate exact de acest MATRECTRANSID; altfel rapoartele de
                    # miscare si folosinta continua sa afiseze bonul anulat.
                    assetTransSql = ( "SELECT ASSETTRANSID, ASSETNUM, FROMLOC, TOLOC, TRANSTYPE, SITEID, TOSITEID, ORGID " "FROM ASSETTRANS WHERE MATRECTRANSID=%s ORDER BY ASSETTRANSID" % str(matrectransid) ); rsAssetTrans = s.executeQuery(assetTransSql); assettrans_rows = []
                    while rsAssetTrans.next(): assettrans_rows.append((rsAssetTrans.getLong(1), rsAssetTrans.getString(2), rsAssetTrans.getString(3), rsAssetTrans.getString(4), rsAssetTrans.getString(5), rsAssetTrans.getString(6), rsAssetTrans.getString(7), rsAssetTrans.getString(8)))
                    rsAssetTrans.close()
                    if len(assettrans_rows) > 1: raise Exception( "Mai multe ASSETTRANS pentru MATRECTRANSID=%s" % str(matrectransid) )
                    if len(assettrans_rows) == 1:
                        at = assettrans_rows[0]
                        if at[1] != mat_rotasset or at[2] != fromstoreloc or at[3] != tostoreloc or at[4] != "MOVED" or at[5] != siteid or (at[6] and at[6] != siteid) or (at[7] and at[7] != orgid): raise Exception( "ASSETTRANS nu corespunde transferului MATRECTRANSID=%s" % str(matrectransid) )
                        laterAssetSql = ( "SELECT COUNT(*) FROM ASSETTRANS WHERE ASSETNUM='%s' AND SITEID='%s' AND ASSETTRANSID>%s" % (mat_rotasset.replace("'", "''"), siteid.replace("'", "''"), str(at[0])) ); rsLaterAsset = s.executeQuery(laterAssetSql)
                        if not rsLaterAsset.next():
                            rsLaterAsset.close()
                            raise Exception( "Nu s-au putut verifica miscarile ulterioare ale activului %s" % mat_rotasset )
                        later_asset_count = rsLaterAsset.getInt(1); rsLaterAsset.close()
                        if later_asset_count != 0: raise Exception( "Activul %s are %s miscari ASSETTRANS dupa acest bon; anularea trebuie tratata in ordinea miscarilor" % (mat_rotasset, str(later_asset_count)) )
                        if at[0] in validated_assettrans_ids: raise Exception( "ASSETTRANSID duplicat=%s" % str(at[0]) )
                        validated_assettrans_ids.append(at[0])
                    # CXFOLOSINTA dest creat de transfer (CXREFMBO=MATRECTRANS).
                    # Reguli CXADDTOCXFOLOSINTA: mutarile ulterioare inchid dest-ul
                    # (CXLADATA/CXREFMBOTO/CXREFIDTO) si creeaza copil CXREFMBO=CXFOLOSINTA.
                    # Anularea e permisa doar daca dest e varful lantului.
                    cxFolosintaSql = ( "SELECT CXFOLOSINTAID, ITEMNUM, LOCATION, QUANTITY, ROTASSETNUM, SITEID, ORGID, " "CXLADATA, CXREFMBOTO, CXREFIDTO " "FROM CXFOLOSINTA WHERE CXREFMBO='MATRECTRANS' AND CXREFID=%s ORDER BY CXFOLOSINTAID" % str(matrectransid) ); rsCxFolosinta = s.executeQuery(cxFolosintaSql); cxfol_rows = []
                    while rsCxFolosinta.next():
                        cxf_refidto = rsCxFolosinta.getLong(10)
                        if rsCxFolosinta.wasNull(): cxf_refidto = None
                        cxfol_rows.append((rsCxFolosinta.getLong(1), rsCxFolosinta.getString(2), rsCxFolosinta.getString(3), rsCxFolosinta.getDouble(4), rsCxFolosinta.getString(5), rsCxFolosinta.getString(6), rsCxFolosinta.getString(7), rsCxFolosinta.getTimestamp(8), rsCxFolosinta.getString(9), cxf_refidto))
                    rsCxFolosinta.close()
                    if len(cxfol_rows) > 1: raise Exception( "Mai multe CXFOLOSINTA pentru rotating MATRECTRANSID=%s" % str(matrectransid) )
                    if len(cxfol_rows) == 1:
                        cxf = cxfol_rows[0]; dest_cxfolosintaid = cxf[0]
                        if cxf[1] != itemnum or cxf[2] != tostoreloc or abs(cxf[3] - 1.0) > 0.000001 or cxf[4] != mat_rotasset or cxf[5] != siteid or (cxf[6] and cxf[6] != orgid): raise Exception( "CXFOLOSINTA nu corespunde transferului MATRECTRANSID=%s" % str(matrectransid) )
                        if cxf[7] is not None or (cxf[8] and str(cxf[8]).strip() != "") or cxf[9] is not None:
                            raise Exception( "CXFOLOSINTA dest ID=%s a fost deja inchisa/mutata (CXLADATA/CXREFMBOTO/CXREFIDTO); anulare blocata (regula CXADDTOCXFOLOSINTA)" % str(dest_cxfolosintaid) )
                        childFolosintaSql = ( "SELECT COUNT(*) FROM CXFOLOSINTA WHERE CXREFMBO='CXFOLOSINTA' AND CXREFID=%s" % str(dest_cxfolosintaid) ); rsChildFol = s.executeQuery(childFolosintaSql)
                        if not rsChildFol.next():
                            rsChildFol.close()
                            raise Exception("Nu s-au putut verifica copiii CXFOLOSINTA pentru ID=%s" % str(dest_cxfolosintaid))
                        child_fol_count = rsChildFol.getInt(1); rsChildFol.close()
                        if child_fol_count != 0: raise Exception( "CXFOLOSINTA dest ID=%s are %s mutari CXADDTOCXFOLOSINTA; anulare blocata" % (str(dest_cxfolosintaid), str(child_fol_count)) )
                        laterFolosintaSql = ( "SELECT COUNT(*) FROM CXFOLOSINTA WHERE ROTASSETNUM='%s' AND SITEID='%s' AND CXFOLOSINTAID>%s" % (mat_rotasset.replace("'", "''"), siteid.replace("'", "''"), str(dest_cxfolosintaid)) ); rsLaterFolosinta = s.executeQuery(laterFolosintaSql)
                        if not rsLaterFolosinta.next():
                            rsLaterFolosinta.close()
                            raise Exception( "Nu s-a putut verifica folosinta ulterioara a activului %s" % mat_rotasset )
                        later_folosinta_count = rsLaterFolosinta.getInt(1); rsLaterFolosinta.close()
                        if later_folosinta_count != 0: raise Exception( "Activul %s are %s inregistrari CXFOLOSINTA dupa acest bon" % (mat_rotasset, str(later_folosinta_count)) )
                        if dest_cxfolosintaid in validated_cxfolosinta_ids: raise Exception( "CXFOLOSINTAID duplicat=%s" % str(dest_cxfolosintaid) )
                        validated_cxfolosinta_ids.append(dest_cxfolosintaid)
                        # Sursa inchisa de acest transfer: redeschidem la anulare.
                        # a) CXREFMBOTO=MATRECTRANS + CXREFIDTO=matrectransid
                        # b) CXREFMBOTO=CXFOLOSINTA + CXREFIDTO=dest_cxfolosintaid (pattern CXADDTO)
                        sourceFolSql = ( "SELECT CXFOLOSINTAID FROM CXFOLOSINTA " "WHERE ROTASSETNUM='%s' AND SITEID='%s' AND CXFOLOSINTAID<>%s AND (" " (CXREFMBOTO='MATRECTRANS' AND CXREFIDTO=%s) OR " " (CXREFMBOTO='CXFOLOSINTA' AND CXREFIDTO=%s) " ") ORDER BY CXFOLOSINTAID" % (mat_rotasset.replace("'", "''"), siteid.replace("'", "''"), str(dest_cxfolosintaid), str(matrectransid), str(dest_cxfolosintaid)) )
                        rsSourceFol = s.executeQuery(sourceFolSql); source_fol_ids = []
                        while rsSourceFol.next(): source_fol_ids.append(rsSourceFol.getLong(1))
                        rsSourceFol.close()
                        if len(source_fol_ids) > 1: raise Exception( "Mai multe CXFOLOSINTA sursa inchise pe MATRECTRANSID=%s / dest=%s" % (str(matrectransid), str(dest_cxfolosintaid)) )
                        if len(source_fol_ids) == 1:
                            src_fol_id = source_fol_ids[0]
                            if src_fol_id in validated_cxfolosinta_reopen_ids: raise Exception("CXFOLOSINTA reopen ID duplicat=%s" % str(src_fol_id))
                            validated_cxfolosinta_reopen_ids.append(src_fol_id)
                    transfer_rows.append(( invuselineid, itemnum, 1.0, mat_rotasset, tostoreloc, matrectransid, transfer_unitcost, transfer_date, dest_fifo_id, source_curbal_before, dest_curbal_before, origin_id, origin_costdate )); validated_matrectrans_ids.append(matrectransid)
                line = linesSet.moveNext()
            if len(transfer_rows) == 0:
                raise Exception("CXCANBC v13.7: nu exista tranzactii validate pentru COMPLETE TRANSFER")
            # Nu readucem antetul in ENTERED daca exista tranzactii ale
            # aceluiasi bon pe care aceasta ramura nu le-a validat.
            matCountSql = ( "SELECT COUNT(*) FROM MATRECTRANS WHERE INVUSEID=%s" % str(invuseid) ); rsMatCount = s.executeQuery(matCountSql)
            if not rsMatCount.next():
                rsMatCount.close()
                raise Exception("Nu s-au putut numara MATRECTRANS ale bonului")
            total_matrectrans = rsMatCount.getInt(1); rsMatCount.close()
            if total_matrectrans != len(validated_matrectrans_ids): raise Exception( "Bonul are MATRECTRANS suplimentare: TOTAL=%s VALIDATE=%s" % (str(total_matrectrans), str(len(validated_matrectrans_ids))) )
            validated_line_ids = set([row[0] for row in transfer_rows]); line_ids_csv = ",".join([str(x) for x in sorted(validated_line_ids)]); splitCountSql = ( "SELECT COUNT(*) FROM INVUSELINESPLIT WHERE INVUSELINEID IN (%s)" % line_ids_csv ); rsSplitCount = s.executeQuery(splitCountSql)
            if not rsSplitCount.next():
                rsSplitCount.close()
                raise Exception("Nu s-au putut numara INVUSELINESPLIT ale bonului")
            split_count_expected = rsSplitCount.getInt(1); rsSplitCount.close()
            # v13.6 MULTI-LINE PRECHECK:
            # pentru acelasi ITEMNUM / aceeasi destinatie validam soldul destinatie
            # fata de cantitatea TOTALA a tuturor liniilor, nu doar fata de fiecare linie separat.
            required_dest_qty = {}; dest_initial_bal = {}
            for pre_row in transfer_rows:
                pre_itemnum = pre_row[1]; pre_qty = pre_row[2]; pre_tostoreloc = pre_row[4]; pre_dest_before = pre_row[10]; pre_dest_key = (pre_itemnum, pre_tostoreloc)
                if pre_dest_key not in required_dest_qty: required_dest_qty[pre_dest_key] = 0.0; dest_initial_bal[pre_dest_key] = pre_dest_before
                required_dest_qty[pre_dest_key] += pre_qty
            for pre_dest_key, pre_total_qty in required_dest_qty.items():
                if dest_initial_bal[pre_dest_key] < pre_total_qty: raise Exception( "CXCANBC v13.7: sold destinatie insuficient pentru anulare multi-line / qty>1. " "ITEMNUM=%s LOCATION=%s CURBAL=%s QTY_TOTAL=%s" % (pre_dest_key[0], pre_dest_key[1], str(dest_initial_bal[pre_dest_key]), str(pre_total_qty)) )
            # v17: fara rebase CXCURBAL / fara UPDATE INVBALANCES — CHECK FIFO manual dupa.
            service.log_info( '*** CXCANBC v17 - PRECHECK OK pentru %s linii, speta=%s, rotating ***' % (str(len(transfer_rows)), str(detected_case)) )
            # -----------------------------------------------------------------
            # EXECUTIE v17 rotating=1 — cronologie:
            #   1) UPDATE ASSET.LOCATION -> FROMSTORELOC
            #   2) UPDATE INVLIFOFIFOCOST (acelasi ID destinatie): LOCATION->FROMSTORELOC
            #      + REFOBJECTID/COSTDATE origine (fara DELETE, fara INSERT FIFO)
            #   3a) UPDATE CXFOLOSINTA sursa: REOPEN (NULL CXLADATA/CXREFMBOTO/CXREFIDTO)
            #   3b) DELETE CXFOLOSINTA dest (CXREFMBO=MATRECTRANS)
            #   3c) DELETE ASSETTRANS / CXSTOCURI(x2 pe CXREFID) / MATRECTRANS
            #   4) DELETE INVUSELINESPLIT (INVUSELINE ramane)
            #   5) INSERT INVUSESTATUS CANCELLED + UPDATE INVUSE.STATUS=CANCELLED
            # -----------------------------------------------------------------
            phase = "execution"
            for row in transfer_rows:
                invuselineid = row[0]; itemnum = row[1]; quantity = row[2]; rotasset = row[3]; tostoreloc = row[4]; matrectransid = row[5]; transfer_unitcost = row[6]; transfer_date = row[7]; dest_fifo_id = row[8]; origin_id = row[11]; origin_costdate = row[12]
                # 1) Asset inapoi in sursa.
                assetUpdate = ( "UPDATE ASSET SET LOCATION = '%s' " "WHERE ASSETNUM = '%s' AND SITEID = '%s' AND LOCATION = '%s'" % ( fromstoreloc.replace("'", "''"), rotasset.replace("'", "''"), siteid.replace("'", "''"), tostoreloc.replace("'", "''") ) ); service.log_info('*** V17 ASSET UPDATE *** ' + assetUpdate)
                if s.executeUpdate(assetUpdate) != 1:
                    raise Exception("ASSET UPDATE nu a modificat exact 1 rand pentru ASSET=%s" % rotasset)
                # 2) FIFO: mutam stratul destinatie inapoi pe FROMSTORELOC (UPDATE, nu DELETE+INSERT).
                fifoUpdate = ( "UPDATE INVLIFOFIFOCOST SET LOCATION='%s', REFOBJECT='MATRECTRANS', REFOBJECTID=%s, COSTDATE=TIMESTAMP('%s') " "WHERE INVLIFOFIFOCOSTID=%s AND LOCATION='%s' AND QUANTITY=1 AND SITEID='%s' AND ITEMNUM='%s'" % ( fromstoreloc.replace("'", "''"), str(origin_id), str(origin_costdate), str(dest_fifo_id), tostoreloc.replace("'", "''"), siteid.replace("'", "''"), itemnum.replace("'", "''") ) )
                service.log_info('*** V17 FIFO UPDATE LOCATION->FROMSTORELOC *** ' + fifoUpdate)
                if s.executeUpdate(fifoUpdate) != 1:
                    raise Exception("FIFO UPDATE nu a modificat exact 1 rand, ID=%s ASSET=%s" % (str(dest_fifo_id), rotasset))
                # Postcheck: asset + FIFO pe sursa (fara INVBALANCES).
                postAssetSql = ( "SELECT LOCATION FROM ASSET WHERE ASSETNUM='%s' AND SITEID='%s' FETCH FIRST 1 ROW ONLY" % (rotasset.replace("'", "''"), siteid.replace("'", "''")) ); rsPostAsset = s.executeQuery(postAssetSql)
                if not rsPostAsset.next() or rsPostAsset.getString(1) != fromstoreloc:
                    rsPostAsset.close()
                    raise Exception("POSTCHECK ASSET esuat pentru ASSET=%s" % rotasset)
                rsPostAsset.close()
                postFifoSql = ( "SELECT LOCATION, QUANTITY, REFOBJECT, REFOBJECTID, COSTDATE FROM INVLIFOFIFOCOST WHERE INVLIFOFIFOCOSTID=%s" % str(dest_fifo_id) ); rsPostFifo = s.executeQuery(postFifoSql)
                if not rsPostFifo.next() or rsPostFifo.getString(1) != fromstoreloc or rsPostFifo.getDouble(2) != 1.0 or rsPostFifo.getString(3) != 'MATRECTRANS' or rsPostFifo.getLong(4) != origin_id or not rsPostFifo.getTimestamp(5).equals(origin_costdate):
                    rsPostFifo.close()
                    raise Exception("POSTCHECK FIFO UPDATE esuat pentru ASSET=%s ID=%s" % (rotasset, str(dest_fifo_id)))
                rsPostFifo.close()
            # 3) Curatare istoric (fara INVLIFOFIFOCOST DELETE, fara CXCURBAL).
            ids_csv = ",".join([str(x) for x in validated_matrectrans_ids])
            # 3a) REOPEN CXFOLOSINTA sursa inchisa de transfer / CXADDTO (inversul close).
            if len(validated_cxfolosinta_reopen_ids) > 0:
                reopen_ids_csv = ",".join([str(x) for x in validated_cxfolosinta_reopen_ids])
                cxfolosintaReopen = ( "UPDATE CXFOLOSINTA SET CXLADATA=NULL, CXREFMBOTO=NULL, CXREFIDTO=NULL " "WHERE CXFOLOSINTAID IN (%s) AND (CXREFMBOTO='MATRECTRANS' OR CXREFMBOTO='CXFOLOSINTA')" % reopen_ids_csv )
                service.log_info('*** V17 CXFOLOSINTA REOPEN (clear CXLADATA/CXREFMBOTO/CXREFIDTO) *** ' + cxfolosintaReopen)
                if s.executeUpdate(cxfolosintaReopen) != len(validated_cxfolosinta_reopen_ids):
                    raise Exception("CXFOLOSINTA REOPEN nu a modificat toate randurile sursa validate")
            # 3b) DELETE CXFOLOSINTA dest (doar varful lantului, CXREFMBO=MATRECTRANS).
            if len(validated_cxfolosinta_ids) > 0:
                cxfolosinta_ids_csv = ",".join([str(x) for x in validated_cxfolosinta_ids]); cxfolosintaDelete = ( "DELETE FROM CXFOLOSINTA WHERE CXFOLOSINTAID IN (%s) AND CXREFMBO='MATRECTRANS' AND CXREFID IN (%s) " "AND CXLADATA IS NULL AND CXREFMBOTO IS NULL AND CXREFIDTO IS NULL" % (cxfolosinta_ids_csv, ids_csv) )
                service.log_info('*** V17 CXFOLOSINTA DEST DELETE *** ' + cxfolosintaDelete)
                if s.executeUpdate(cxfolosintaDelete) != len(validated_cxfolosinta_ids): raise Exception("CXFOLOSINTA DELETE nu a sters toate randurile dest validate")
            # 3c) ASSETTRANS + CXSTOCURI x2 + MATRECTRANS.
            if len(validated_assettrans_ids) > 0:
                assettrans_ids_csv = ",".join([str(x) for x in validated_assettrans_ids]); assettransDelete = ( "DELETE FROM ASSETTRANS WHERE ASSETTRANSID IN (%s) AND MATRECTRANSID IN (%s)" % (assettrans_ids_csv, ids_csv) )
                if s.executeUpdate(assettransDelete) != len(validated_assettrans_ids): raise Exception("ASSETTRANS DELETE nu a sters toate randurile validate")
            cxstocuriDelete = ( "DELETE FROM CXSTOCURI " "WHERE CXREFMBO = 'MATRECTRANS' AND CXREFID IN (%s)" % ids_csv ); service.log_info('*** V17 CXSTOCURI DELETE (2 pe CXREFID) *** ' + cxstocuriDelete)
            if s.executeUpdate(cxstocuriDelete) != 2 * len(validated_matrectrans_ids):
                raise Exception("CXSTOCURI DELETE nu a sters cele doua randuri validate pentru fiecare transfer")
            matrectransDelete = ( "DELETE FROM MATRECTRANS WHERE MATRECTRANSID IN (%s)" % ids_csv ); service.log_info('*** V17 MATRECTRANS DELETE *** ' + matrectransDelete); deleted_matrec = s.executeUpdate(matrectransDelete)
            if deleted_matrec != len(validated_matrectrans_ids): raise Exception( "MATRECTRANS DELETE a sters %s randuri, asteptat %s" % (str(deleted_matrec), str(len(validated_matrectrans_ids))) )
            # 4) Stergem spliturile; INVUSELINE ramane pe bonul CANCELLED.
            if split_count_expected > 0:
                invuselinesplitDelete = ( "DELETE FROM INVUSELINESPLIT WHERE INVUSELINEID IN (%s)" % line_ids_csv ); service.log_info('*** V17 INVUSELINESPLIT DELETE *** ' + invuselinesplitDelete)
                if s.executeUpdate(invuselinesplitDelete) != split_count_expected: raise Exception("INVUSELINESPLIT DELETE nu a sters toate randurile bonului")
            service.log_info('*** V17 KEEP INVUSELINE (count=%s) ***' % str(len(validated_line_ids)))
            # 5) Status CANCELLED.
            invusestatusInsert = ( "INSERT INTO INVUSESTATUS (INVUSESTATUSID, INVUSENUM, SITEID, ORGID, STATUS, CHANGEDATE, CHANGEBY) " "VALUES (NEXT VALUE FOR INVUSESTATUSSEQ, '%s', '%s', '%s', 'CANCELLED', CURRENT TIMESTAMP, '%s')" % (invusenum.replace("'", "''"), siteid.replace("'", "''"), orgid.replace("'", "''"), userInfo.getUserName().replace("'", "''")) )
            service.log_info('*** V17 INVUSESTATUS CANCELLED INSERT *** ' + invusestatusInsert)
            if s.executeUpdate(invusestatusInsert) != 1: raise Exception("INVUSESTATUS INSERT CANCELLED a esuat pentru INVUSENUM=%s" % invusenum)
            invuseUpdate = ( "UPDATE INVUSE SET STATUS = 'CANCELLED', STATUSDATE = CURRENT TIMESTAMP " "WHERE INVUSEID = %s" % str(invuseid) ); service.log_info('*** V17 INVUSE COMPLETE TRANSFER -> CANCELLED *** ' + invuseUpdate)
            if s.executeUpdate(invuseUpdate) != 1: raise Exception("INVUSE UPDATE nu a modificat exact 1 rand pentru INVUSEID=%s" % str(invuseid))
            service.log_info( '*** CXCANBC v17 - COMPLETE TRANSFER rotating finished OK, speta=%s ***' % str(detected_case) )
        else:
            # Ramura v12 de mai jos nu clasifica tranzactiile reale. Pe TEST exista
            # bonuri COMPLETE/MIXED cu MATUSETRANS ISSUE, iar USETYPE nu este un
            # discriminator sigur pentru efectele de inversat. Nu o executam pana
            # cand preflight-ul pe tranzactii si refacerea CXCURBAL sunt complete.
            raise Exception( "CXCANBC v14 draft: COMPLETE/%s nu este inca validat pentru anulare; " "nu s-a modificat bonul %s" % (usetype, invusenum) )
            # NON-TRANSFER COMPLETE: logica v12 ramane neschimbata.
            # dictionar itemnum -> cantitate totala de stornat
            qty_map = {}; line = linesSet.moveFirst()
            while line:
                itemnum  = line.getString("ITEMNUM"); quantity = line.getDouble("QUANTITY"); rotasset = line.getString("ROTASSETNUM")
                if itemnum not in qty_map: qty_map[itemnum] = 0.0
                qty_map[itemnum] += quantity
                # daca exista ROTASSETNUM -> actualizam ASSET.LOCATION inapoi in FROMSTORELOC
                if rotasset: assetUpdate = ( "UPDATE ASSET " "SET LOCATION = '%s' " "WHERE ASSETNUM = '%s' AND SITEID = '%s'" % ( fromstoreloc.replace("'", "''"), rotasset.replace("'", "''"), siteid.replace("'", "''") ) ); service.log_info('*** ASSET UPDATE *** ' + assetUpdate); s.execute(assetUpdate)
                line = linesSet.moveNext()
            # 3.1 Actualizam stocul (INVBALANCES) si ISSUEYTD (INVENTORY) + LIFO/FIFO
            for itemnum, qty in qty_map.items():
                invbalUpdate = ( "UPDATE INVBALANCES " "SET CURBAL = CURBAL + %s " "WHERE ITEMNUM = '%s' AND LOCATION = '%s' AND SITEID = '%s'" % ( str(qty), itemnum.replace("'", "''"), fromstoreloc.replace("'", "''"), siteid.replace("'", "''") ) ); service.log_info('*** INVBALANCES UPDATE *** ' + invbalUpdate); s.execute(invbalUpdate)
                inventoryUpdate = ( "UPDATE INVENTORY " "SET ISSUEYTD = ISSUEYTD - %s " "WHERE ITEMNUM = '%s' AND LOCATION = '%s' AND SITEID = '%s'" % ( str(qty), itemnum.replace("'", "''"), fromstoreloc.replace("'", "''"), siteid.replace("'", "''") ) ); service.log_info('*** INVENTORY UPDATE *** ' + inventoryUpdate); s.execute(inventoryUpdate)
                # 3.2 Verificam daca exista tranz in INVLIFOFIFOCOST pentru item/location/org
                checkSql = ( "SELECT 1 FROM INVLIFOFIFOCOST " "WHERE ITEMNUM = '%s' AND LOCATION = '%s' AND ORGID = '%s'" % ( itemnum.replace("'", "''"), fromstoreloc.replace("'", "''"), orgid.replace("'", "''") ) ); service.log_info('*** INVLIFOFIFOCOST CHECK *** ' + checkSql); rsCheck = s.executeQuery(checkSql); hasLayer = rsCheck.next(); rsCheck.close()
                if not hasLayer:
                    # 3.3 Nu exista nicio tranz -> incercam sa reconstruim din CXSTOCURI
                    service.log_info('*** No INVLIFOFIFOCOST tranz, try rebuild from CXSTOCURI ***')
                    cxSql = ( "SELECT C.ORGID, C.ITEMNUM, C.CXDOCUMENTDATE, C.UNITCOST, C.CXQTY, " "       C.SITEID, C.LOCATION " "FROM CXSTOCURI C " "WHERE C.CXREFMBO = 'MATUSETRANS' " "  AND C.CXREFID IN ( " "        SELECT M.MATUSETRANSID " "        FROM MATUSETRANS M " "        WHERE M.INVUSEID = %s " "          AND M.ITEMNUM = '%s' " "          AND M.STORELOC = '%s' )" % ( str(invuseid), itemnum.replace("'", "''"), fromstoreloc.replace("'", "''") ) )
                    service.log_info('*** CXSTOCURI SELECT FOR REBUILD *** ' + cxSql); rsCx = s.executeQuery(cxSql)
                    if rsCx.next():
                        orgid_cx    = rsCx.getString(1); itemnum_cx  = rsCx.getString(2); costdate_cx = rsCx.getTimestamp(3); unitcost_cx = rsCx.getDouble(4); qty_cx      = rsCx.getDouble(5); siteid_cx   = rsCx.getString(6); location_cx = rsCx.getString(7); rsCx.close(); itemsetid_cx = "SET1"; costtype_cx  = "FIFO"; qty_layer    = abs(qty_cx)
                        insertSql = ( "INSERT INTO INVLIFOFIFOCOST " "(ORGID, ITEMNUM, ITEMSETID, CONDITIONCODE, COSTTYPE, COSTDATE, " " UNITCOST, QUANTITY, REFOBJECT, CONDRATE, SITEID, LOCATION, " " REFOBJECTID, CONTENTUID, CXNRFISAVECHI, INVLIFOFIFOCOSTID) " "VALUES (" "'%s','%s','%s',NULL,'%s',TIMESTAMP('%s'),%s,%s,NULL,NULL,'%s','%s'," "NULL,HEX(GENERATE_UNIQUE()),NULL,NEXT VALUE FOR INVLIFOFIFOCOSTSEQ)" % ( orgid_cx.replace("'", "''"), itemnum_cx.replace("'", "''"), itemsetid_cx, costtype_cx, str(costdate_cx), str(unitcost_cx), str(qty_layer), siteid_cx.replace("'", "''"), location_cx.replace("'", "''") ) )
                        service.log_info('*** INVLIFOFIFOCOST INSERT REBUILD *** ' + insertSql); s.execute(insertSql)
                    else: rsCx.close(); service.log_info('*** No CXSTOCURI row found to rebuild INVLIFOFIFOCOST ***')
                else:
                    # 3.4 Exista deja tranz -> refacem cantitatea prin UPDATE pe tranz FIFO
                    service.log_info('*** INVLIFOFIFOCOST tranz exists, updating quantities ***'); qty_to_restore = qty; fifoSelect = ( "SELECT INVLIFOFIFOCOSTID, QUANTITY " "FROM INVLIFOFIFOCOST " "WHERE ITEMNUM = '%s' AND LOCATION = '%s' " "ORDER BY COSTDATE ASC" % ( itemnum.replace("'", "''"), fromstoreloc.replace("'", "''") ) )
                    service.log_info('*** INVLIFOFIFOCOST FIFO SELECT *** ' + fifoSelect); rs = s.executeQuery(fifoSelect); fifo_rows = []
                    while rs.next(): lifocostid = rs.getLong(1); layer_qty  = rs.getDouble(2); fifo_rows.append((lifocostid, layer_qty))
                    rs.close()
                    for (lifocostid, layer_qty) in fifo_rows:
                        if qty_to_restore <= 0: break
                        inc = qty_to_restore; lifoUpdate = ( "UPDATE INVLIFOFIFOCOST " "SET QUANTITY = QUANTITY + %s " "WHERE INVLIFOFIFOCOSTID = %s" % (str(inc), str(lifocostid)) ); service.log_info('*** INVLIFOFIFOCOST UPDATE *** ' + lifoUpdate); s.execute(lifoUpdate); qty_to_restore = qty_to_restore - inc
            # 3.5 Stergeri / update-uri COMPLETE (v16: pastram linii; STATUS=CANCELLED)
            # Notă: ramura e inca dead-code (raise deasupra); aliniata deja la v16.
            cxstocuriDelete = ( "DELETE FROM CXSTOCURI " "WHERE CXREFMBO = 'MATUSETRANS' " "AND CXREFID IN (" "    SELECT M.MATUSETRANSID " "    FROM MATUSETRANS M " "    WHERE M.INVUSEID = %s)" % str(invuseid) ); service.log_info('*** CXSTOCURI DELETE *** ' + cxstocuriDelete); s.execute(cxstocuriDelete)
            matusetransDelete = ( "DELETE FROM MATUSETRANS " "WHERE INVUSEID = %s" % str(invuseid) ); service.log_info('*** MATUSETRANS DELETE *** ' + matusetransDelete); s.execute(matusetransDelete)
            service.log_info('*** V16 KEEP INVUSELINESPLIT + INVUSELINE pe bon CANCELLED ***')
            invusestatusInsert = ( "INSERT INTO INVUSESTATUS (INVUSESTATUSID, INVUSENUM, SITEID, ORGID, STATUS, CHANGEDATE, CHANGEBY) " "VALUES (NEXT VALUE FOR INVUSESTATUSSEQ, '%s', '%s', '%s', 'CANCELLED', CURRENT TIMESTAMP, '%s')" % (invusenum.replace("'", "''"), siteid.replace("'", "''"), orgid.replace("'", "''"), userInfo.getUserName().replace("'", "''")) ); service.log_info('*** V16 INVUSESTATUS CANCELLED INSERT *** ' + invusestatusInsert); s.execute(invusestatusInsert)
            invuseUpdate = ( "UPDATE INVUSE " "SET STATUS = 'CANCELLED', STATUSDATE = CURRENT TIMESTAMP " "WHERE INVUSEID = %s" % str(invuseid) ); service.log_info('*** V16 INVUSE UPDATE -> CANCELLED *** ' + invuseUpdate); s.execute(invuseUpdate)
    # 4. Anulare Transfer - status SHIPPED
    elif status == "SHIPPED" and usetype == "TRANSFER":
        service.log_info('*** CXCANBC v13.9.1 - SHIPPED TRANSFER ***')
        # v13.9.1:
        # - PRECHECK GLOBAL inainte de orice UPDATE/DELETE.
        # - blocheaza anularea daca stocul receptionat nu mai este disponibil in destinatie.
        # - suporta INVUSELINE QTY>1 splitata in mai multe SHIPTRANSFER/SHIPRECEIPT rotating.
        # - fiecare SHIPRECEIPT se leaga de SHIPTRANSFER exclusiv prin RECEIPTREF.
        # - MATRECTRANS este sursa de adevar pentru ROTASSETNUM si INVUSELINESPLITID.
        receipts_state = invuse_mbo.getString("RECEIPTS")
        if receipts_state not in ("NONE", "COMPLETE"): raise Exception( "CXCANBC v13.9.1: SHIPPED RECEIPTS=%s neimplementat; sunt permise NONE sau COMPLETE." % receipts_state )
        if not fromstoreloc:
            raise Exception("CXCANBC v13.9.1: FROMSTORELOC lipsa pe INVUSE")
        # -----------------------------------------------------------------
        # PRECHECK A - solduri globale si structura liniilor.
        # Acest pas ruleaza inaintea validarilor FIFO/CXSTOCURI astfel incat
        # un transfer deja consumat sa fie blocat imediat, fara modificari.
        # -----------------------------------------------------------------
        required_source_qty = {}; source_initial_bal = {}; required_dest_qty = {}; dest_initial_bal = {}; line_count_expected = 0; shipped_line_ids = []; line = linesSet.moveFirst()
        while line:
            invuselineid = line.getLong("INVUSELINEID"); itemnum = line.getString("ITEMNUM"); line_quantity = line.getDouble("QUANTITY"); tostoreloc = line.getString("TOSTORELOC"); tositeid = line.getString("TOSITEID"); line_count_expected += 1
            if invuselineid <= 0 or invuselineid in shipped_line_ids: raise Exception("CXCANBC v14: INVUSELINEID invalid sau duplicat=%s" % str(invuselineid))
            shipped_line_ids.append(invuselineid)
            if not itemnum: raise Exception( "CXCANBC v13.9.1: ITEMNUM lipsa pentru INVUSELINEID=%s" % str(invuselineid) )
            if line_quantity <= 0: raise Exception( "CXCANBC v13.9.1: QUANTITY trebuie sa fie > 0 pentru INVUSELINEID=%s" % str(invuselineid) )
            if not tostoreloc: raise Exception( "CXCANBC v13.9.1: TOSTORELOC lipsa pentru INVUSELINEID=%s" % str(invuselineid) )
            if not tositeid: tositeid = siteid
            if tositeid != siteid: raise Exception( "CXCANBC v13.9.1: SHIPPED transfer intre site-uri neimplementat. " "INVUSELINEID=%s SITEID=%s TOSITEID=%s" % (str(invuselineid), siteid, tositeid) )
            source_key = (itemnum, fromstoreloc)
            if source_key not in source_initial_bal:
                sourceBalSql = ( "SELECT CURBAL FROM INVBALANCES " "WHERE ITEMNUM='%s' AND LOCATION='%s' AND SITEID='%s' " "FETCH FIRST 1 ROW ONLY" % ( itemnum.replace("'", "''"), fromstoreloc.replace("'", "''"), siteid.replace("'", "''") ) ); rsSourceBal = s.executeQuery(sourceBalSql)
                if not rsSourceBal.next():
                    rsSourceBal.close()
                    raise Exception( "CXCANBC v13.9.1: lipseste INVBALANCES sursa pentru ITEMNUM=%s LOCATION=%s" % (itemnum, fromstoreloc) )
                source_initial_bal[source_key] = rsSourceBal.getDouble(1); rsSourceBal.close(); required_source_qty[source_key] = 0.0
            required_source_qty[source_key] += line_quantity
            if receipts_state == "COMPLETE":
                dest_key = (itemnum, tostoreloc)
                if dest_key not in dest_initial_bal:
                    destBalSql = ( "SELECT CURBAL FROM INVBALANCES " "WHERE ITEMNUM='%s' AND LOCATION='%s' AND SITEID='%s' " "FETCH FIRST 1 ROW ONLY" % ( itemnum.replace("'", "''"), tostoreloc.replace("'", "''"), siteid.replace("'", "''") ) ); rsDestBal = s.executeQuery(destBalSql)
                    if not rsDestBal.next():
                        rsDestBal.close()
                        raise Exception( "CXCANBC v13.9.1: lipseste INVBALANCES destinatie pentru ITEMNUM=%s LOCATION=%s" % (itemnum, tostoreloc) )
                    dest_initial_bal[dest_key] = rsDestBal.getDouble(1); rsDestBal.close(); required_dest_qty[dest_key] = 0.0
                required_dest_qty[dest_key] += line_quantity
            line = linesSet.moveNext()
        if line_count_expected == 0:
            raise Exception("CXCANBC v13.9.1: bonul nu contine INVUSELINE")
        # Protectia principala pentru transferurile receptionate si consumate ulterior.
        for dest_key, required_qty in required_dest_qty.items():
            current_dest_qty = dest_initial_bal[dest_key]
            if current_dest_qty < required_qty: raise Exception( "CXCANBC v13.9.1: sold destinatie insuficient pentru anulare. " "ITEMNUM=%s LOCATION=%s CURBAL=%s QTY_NECESAR=%s" % ( dest_key[0], dest_key[1], str(current_dest_qty), str(required_qty) ) )
        service.log_info('*** CXCANBC v13.9.1 - SHIPPED PRECHECK SOLDURI OK ***')
        # -----------------------------------------------------------------
        # PRECHECK B - validare completa MATRECTRANS / split / asset / FIFO / CXSTOCURI.
        # Nici aici nu executam UPDATE/DELETE.
        # -----------------------------------------------------------------
        shipped_rows = []; validated_matrectrans_ids = []; validated_split_ids = set(); validated_cx_partitions = set(); validated_cx_ids = set(); validated_rotassets = set()
        # v13.9.1 - istorice secundare legate de SHIPRECEIPT.
        # Se valideaza in PRECHECK si se sterg abia dupa POSTCHECK-ul de stoc/FIFO/asset.
        validated_assettrans_ids = []; validated_cxfolosinta_ids = []; line = linesSet.moveFirst()
        while line:
            invuselineid = line.getLong("INVUSELINEID"); invuselinum = line.getInt("INVUSELINENUM"); itemnum = line.getString("ITEMNUM"); line_quantity = line.getDouble("QUANTITY"); line_unitcost = line.getDouble("UNITCOST"); line_rotasset = line.getString("ROTASSETNUM"); tostoreloc = line.getString("TOSTORELOC"); line_actualdate = line.getDate("ACTUALDATE")
            transferSql = ( "SELECT MATRECTRANSID, ITEMNUM, UNITCOST, ACTUALDATE, ROTASSETNUM, QUANTITY, " "       FROMSTORELOC, TOSTORELOC, INVUSELINESPLITID " "FROM MATRECTRANS " "WHERE INVUSEID=%s AND INVUSELINEID=%s AND ISSUETYPE='SHIPTRANSFER' " "ORDER BY MATRECTRANSID" % (str(invuseid), str(invuselineid)) )
            service.log_info('*** V13.9.1 SHIPTRANSFER SELECT *** ' + transferSql); rsTransfer = s.executeQuery(transferSql); transfer_rows = []
            while rsTransfer.next(): transfer_rows.append(( rsTransfer.getLong(1), rsTransfer.getString(2), rsTransfer.getDouble(3), rsTransfer.getTimestamp(4), rsTransfer.getString(5), rsTransfer.getDouble(6), rsTransfer.getString(7), rsTransfer.getString(8), rsTransfer.getLong(9) ))
            rsTransfer.close()
            if len(transfer_rows) == 0: raise Exception( "CXCANBC v13.9.1: nu exista SHIPTRANSFER pentru INVUSELINEID=%s" % str(invuselineid) )
            transfer_qty_total = 0.0
            for transfer_row in transfer_rows: transfer_qty_total += transfer_row[5]
            if abs(transfer_qty_total - line_quantity) > 0.000001: raise Exception( "CXCANBC v13.9.1: suma SHIPTRANSFER nu corespunde INVUSELINE. " "INVUSELINEID=%s LINE_QTY=%s TRANSFER_QTY=%s" % (str(invuselineid), str(line_quantity), str(transfer_qty_total)) )
            if line_rotasset:
                if abs(line_quantity - 1.0) > 0.000001 or len(transfer_rows) != 1: raise Exception( "CXCANBC v13.9.1: INVUSELINE cu ROTASSETNUM trebuie sa aiba QTY=1 " "si exact 1 SHIPTRANSFER. INVUSELINEID=%s" % str(invuselineid) )
            line_rotating_mode = None
            for transfer_row in transfer_rows:
                shiptransferid = transfer_row[0]; transfer_itemnum = transfer_row[1]; transfer_unitcost = transfer_row[2]; transfer_date = transfer_row[3]; shiptransfer_rotasset = transfer_row[4]; transfer_qty = transfer_row[5]; mat_fromstoreloc = transfer_row[6]; mat_tostoreloc = transfer_row[7]; transfer_splitid = transfer_row[8]
                if transfer_qty <= 0: raise Exception( "CXCANBC v13.9.1: SHIPTRANSFER QTY trebuie sa fie >0. MATRECTRANSID=%s" % str(shiptransferid) )
                if transfer_itemnum != itemnum: raise Exception( "CXCANBC v13.9.1: ITEMNUM SHIPTRANSFER diferit de INVUSELINE. " "MATRECTRANSID=%s" % str(shiptransferid) )
                if mat_fromstoreloc != fromstoreloc or mat_tostoreloc != tostoreloc: raise Exception( "CXCANBC v13.9.1: SHIPTRANSFER nu corespunde locatiei bonului. " "MATRECTRANSID=%s FROM=%s TO=%s" % (str(shiptransferid), str(mat_fromstoreloc), str(mat_tostoreloc)) )
                if transfer_splitid <= 0:
                    raise Exception( "CXCANBC v13.9.1: INVUSELINESPLITID lipsa pe SHIPTRANSFER=%s" % str(shiptransferid) )
                # Splitul trebuie sa existe si sa corespunda exact transferului.
                splitSql = ( "SELECT INVUSELINEID, INVUSELINENUM, ITEMNUM, QUANTITY, FROMSTORELOC, UNITCOST " "FROM INVUSELINESPLIT WHERE INVUSELINESPLITID=%s" % str(transfer_splitid) ); rsSplit = s.executeQuery(splitSql)
                if not rsSplit.next():
                    rsSplit.close()
                    raise Exception( "CXCANBC v13.9.1: lipseste INVUSELINESPLITID=%s" % str(transfer_splitid) )
                split_lineid = rsSplit.getLong(1); split_linenum = rsSplit.getInt(2); split_itemnum = rsSplit.getString(3); split_qty = rsSplit.getDouble(4); split_fromstoreloc = rsSplit.getString(5); split_unitcost = rsSplit.getDouble(6)
                if rsSplit.next():
                    rsSplit.close()
                    raise Exception( "CXCANBC v13.9.1: INVUSELINESPLITID duplicat=%s" % str(transfer_splitid) )
                rsSplit.close()
                if split_lineid != invuselineid or split_linenum != invuselinum: raise Exception( "CXCANBC v13.9.1: splitul %s nu apartine INVUSELINEID=%s" % (str(transfer_splitid), str(invuselineid)) )
                if split_itemnum != itemnum or split_fromstoreloc != fromstoreloc: raise Exception( "CXCANBC v13.9.1: splitul %s nu corespunde ITEMNUM/FROMSTORELOC" % str(transfer_splitid) )
                if abs(split_qty - transfer_qty) > 0.000001: raise Exception( "CXCANBC v13.9.1: QTY split diferit de SHIPTRANSFER. SPLIT=%s" % str(transfer_splitid) )
                if abs(split_unitcost - transfer_unitcost) > 0.000001: raise Exception( "CXCANBC v13.9.1: UNITCOST split diferit de SHIPTRANSFER. SPLIT=%s" % str(transfer_splitid) )
                if transfer_splitid in validated_split_ids: raise Exception( "CXCANBC v13.9.1: acelasi INVUSELINESPLITID este folosit de mai multe SHIPTRANSFER: %s" % str(transfer_splitid) )
                validated_split_ids.add(transfer_splitid)
                # Receipt-ul se identifica exclusiv prin RECEIPTREF.
                receiptSql = ( "SELECT MATRECTRANSID, ITEMNUM, UNITCOST, ACTUALDATE, ROTASSETNUM, QUANTITY, " "       FROMSTORELOC, TOSTORELOC, INVUSELINESPLITID, INVUSELINEID " "FROM MATRECTRANS " "WHERE INVUSEID=%s AND ISSUETYPE='SHIPRECEIPT' AND RECEIPTREF=%s " "ORDER BY MATRECTRANSID" % (str(invuseid), str(shiptransferid)) )
                rsReceipt = s.executeQuery(receiptSql); receipt_rows = []
                while rsReceipt.next(): receipt_rows.append(( rsReceipt.getLong(1), rsReceipt.getString(2), rsReceipt.getDouble(3), rsReceipt.getTimestamp(4), rsReceipt.getString(5), rsReceipt.getDouble(6), rsReceipt.getString(7), rsReceipt.getString(8), rsReceipt.getLong(9), rsReceipt.getLong(10) ))
                rsReceipt.close()
                if len(receipt_rows) > 1: raise Exception( "CXCANBC v13.9.1: mai multe SHIPRECEIPT pentru SHIPTRANSFER=%s" % str(shiptransferid) )
                has_shipreceipt = (len(receipt_rows) == 1)
                if receipts_state == "COMPLETE" and not has_shipreceipt: raise Exception( "CXCANBC v13.9.1: RECEIPTS=COMPLETE dar lipseste SHIPRECEIPT pentru SHIPTRANSFER=%s" % str(shiptransferid) )
                if receipts_state == "NONE" and has_shipreceipt: raise Exception( "CXCANBC v13.9.1: RECEIPTS=NONE dar exista SHIPRECEIPT pentru SHIPTRANSFER=%s" % str(shiptransferid) )
                shipreceiptid = 0; shipreceipt_rotasset = None
                if has_shipreceipt:
                    receipt_row = receipt_rows[0]; shipreceiptid = receipt_row[0]; receipt_itemnum = receipt_row[1]; receipt_unitcost = receipt_row[2]; shipreceipt_rotasset = receipt_row[4]; receipt_qty = receipt_row[5]; receipt_from = receipt_row[6]; receipt_to = receipt_row[7]; receipt_splitid = receipt_row[8]; receipt_lineid = receipt_row[9]
                    if receipt_itemnum != itemnum: raise Exception( "CXCANBC v13.9.1: ITEMNUM SHIPRECEIPT diferit de SHIPTRANSFER=%s" % str(shiptransferid) )
                    if receipt_lineid != invuselineid or receipt_splitid != transfer_splitid: raise Exception( "CXCANBC v13.9.1: SHIPRECEIPT nu corespunde INVUSELINE/SPLIT pentru SHIPTRANSFER=%s" % str(shiptransferid) )
                    if receipt_from != fromstoreloc or receipt_to != tostoreloc: raise Exception( "CXCANBC v13.9.1: SHIPRECEIPT nu corespunde locatiei bonului. " "MATRECTRANSID=%s" % str(shipreceiptid) )
                    if abs(receipt_qty - transfer_qty) > 0.000001: raise Exception( "CXCANBC v13.9.1: QTY SHIPRECEIPT diferit de SHIPTRANSFER. " "TRANSFER=%s RECEIPT=%s" % (str(shiptransferid), str(shipreceiptid)) )
                    if abs(receipt_unitcost - transfer_unitcost) > 0.000001: raise Exception( "CXCANBC v13.9.1: UNITCOST SHIPRECEIPT diferit de SHIPTRANSFER. " "TRANSFER=%s RECEIPT=%s" % (str(shiptransferid), str(shipreceiptid)) )
                    if bool(shiptransfer_rotasset) != bool(shipreceipt_rotasset): raise Exception( "CXCANBC v13.9.1: ROTASSETNUM prezent doar pe una dintre perechile " "SHIPTRANSFER/SHIPRECEIPT. TRANSFER=%s RECEIPT=%s" % (str(shiptransferid), str(shipreceiptid)) )
                    if shiptransfer_rotasset and shiptransfer_rotasset != shipreceipt_rotasset: raise Exception( "CXCANBC v13.9.1: ROTASSETNUM diferit intre SHIPTRANSFER=%s si SHIPRECEIPT=%s" % (str(shiptransferid), str(shipreceiptid)) )
                matrec_rotasset = shiptransfer_rotasset or shipreceipt_rotasset
                if line_rotasset:
                    if not matrec_rotasset or line_rotasset != matrec_rotasset: raise Exception( "CXCANBC v13.9.1: ROTASSETNUM INVUSELINE diferit de MATRECTRANS pentru INVUSELINEID=%s" % str(invuselineid) )
                current_rotating_mode = bool(matrec_rotasset)
                if line_rotating_mode is None: line_rotating_mode = current_rotating_mode
                elif line_rotating_mode != current_rotating_mode: raise Exception( "CXCANBC v13.9.1: aceeasi INVUSELINE contine tranzactii rotating si non-rotating. " "INVUSELINEID=%s" % str(invuselineid) )
                asset_location_before = None
                if matrec_rotasset:
                    if matrec_rotasset in validated_rotassets: raise Exception( "CXCANBC v13.9.1: acelasi ROTASSETNUM apare in mai multe SHIPTRANSFER: %s" % matrec_rotasset )
                    validated_rotassets.add(matrec_rotasset)
                    if abs(transfer_qty - 1.0) > 0.000001: raise Exception( "CXCANBC v13.9.1: SHIPTRANSFER rotating trebuie sa aiba QTY=1. " "MATRECTRANSID=%s QTY=%s ASSET=%s" % (str(shiptransferid), str(transfer_qty), matrec_rotasset) )
                    assetSql = ( "SELECT LOCATION FROM ASSET " "WHERE ASSETNUM='%s' AND SITEID='%s' FETCH FIRST 1 ROW ONLY" % ( matrec_rotasset.replace("'", "''"), siteid.replace("'", "''") ) ); rsAsset = s.executeQuery(assetSql)
                    if not rsAsset.next():
                        rsAsset.close()
                        raise Exception( "CXCANBC v13.9.1: nu exista ASSET=%s SITEID=%s" % (matrec_rotasset, siteid) )
                    asset_location_before = rsAsset.getString(1); rsAsset.close()
                    if has_shipreceipt:
                        if asset_location_before != tostoreloc: raise Exception( "CXCANBC v13.9.1: assetul %s nu mai este in destinatia %s (este in %s). " "Anularea este blocata." % (matrec_rotasset, tostoreloc, asset_location_before) )
                    else:
                        if asset_location_before not in (fromstoreloc, tostoreloc):
                            raise Exception( "CXCANBC v13.9.1: assetul %s este in locatia %s, diferita de sursa/destinatie. " "Anularea este blocata." % (matrec_rotasset, asset_location_before) )
                # FIFO destinatie: pentru receipt trebuie sa existe integral.
                dest_fifo_ids = []
                if has_shipreceipt:
                    destFifoSql = ( "SELECT INVLIFOFIFOCOSTID, QUANTITY, UNITCOST " "FROM INVLIFOFIFOCOST " "WHERE ITEMNUM='%s' AND LOCATION='%s' AND SITEID='%s' " "  AND REFOBJECT='MATRECTRANS' AND REFOBJECTID=%s " "ORDER BY INVLIFOFIFOCOSTID" % ( itemnum.replace("'", "''"), tostoreloc.replace("'", "''"), siteid.replace("'", "''"), str(shipreceiptid) ) )
                    rsDestFifo = s.executeQuery(destFifoSql); dest_fifo_qty = 0.0
                    while rsDestFifo.next():
                        dest_fifo_id = rsDestFifo.getLong(1); dest_fifo_row_qty = rsDestFifo.getDouble(2); dest_fifo_unitcost = rsDestFifo.getDouble(3)
                        if abs(dest_fifo_unitcost - transfer_unitcost) > 0.000001:
                            rsDestFifo.close()
                            raise Exception( "CXCANBC v13.9.1: UNITCOST FIFO destinatie diferit pentru SHIPRECEIPT=%s" % str(shipreceiptid) )
                        dest_fifo_ids.append(dest_fifo_id); dest_fifo_qty += dest_fifo_row_qty
                    rsDestFifo.close()
                    if len(dest_fifo_ids) == 0: raise Exception( "CXCANBC v13.9.1: lipseste FIFO destinatie pentru SHIPRECEIPT=%s. " "Stocul receptionat a fost probabil consumat ulterior." % str(shipreceiptid) )
                    if abs(dest_fifo_qty - transfer_qty) > 0.000001: raise Exception( "CXCANBC v13.9.1: FIFO destinatie nu mai contine intreaga cantitate receptionata. " "SHIPRECEIPT=%s FIFO_QTY=%s TRANSFER_QTY=%s" % (str(shipreceiptid), str(dest_fifo_qty), str(transfer_qty)) )
                    if matrec_rotasset and (len(dest_fifo_ids) != 1 or abs(dest_fifo_qty - 1.0) > 0.000001):
                        raise Exception( "CXCANBC v13.9.1: rotating trebuie sa aiba exact un FIFO qty=1 pentru SHIPRECEIPT=%s" % str(shipreceiptid) )
                # CXSTOCURI sursa trebuie sa existe exact o data si sa corespunda transferului.
                cxSourceSql = ( "SELECT CXSTOCURIID, ORGID, ITEMNUM, CXDOCUMENTDATE, UNITCOST, SITEID, LOCATION, CXREF, CXQTY, COMMODITYGROUP " "FROM CXSTOCURI " "WHERE CXREFMBO='MATRECTRANS' AND CXREFID=%s " "ORDER BY CXSTOCURIID" % str(shiptransferid) ); rsCxSource = s.executeQuery(cxSourceSql); cx_source_rows = []
                while rsCxSource.next(): cx_source_rows.append(( rsCxSource.getLong(1), rsCxSource.getString(2), rsCxSource.getString(3), rsCxSource.getTimestamp(4), rsCxSource.getDouble(5), rsCxSource.getString(6), rsCxSource.getString(7), rsCxSource.getString(8), rsCxSource.getDouble(9), rsCxSource.getString(10), rsCxSource.getBigDecimal(5) ))
                rsCxSource.close()
                if len(cx_source_rows) != 1: raise Exception( "CXCANBC v13.9.1: CXSTOCURI SHIPTRANSFER trebuie sa aiba exact 1 rand. " "MATRECTRANSID=%s NR=%s" % (str(shiptransferid), str(len(cx_source_rows))) )
                cx_source = cx_source_rows[0]
                if cx_source[2] != itemnum or cx_source[6] != fromstoreloc or cx_source[7] != "SHIPTRANSFER": raise Exception( "CXCANBC v13.9.1: CXSTOCURI SHIPTRANSFER nu corespunde ITEM/LOCATION/CXREF. " "MATRECTRANSID=%s" % str(shiptransferid) )
                if cx_source[5] != siteid: raise Exception( "CXCANBC v13.9.1: SITEID CXSTOCURI SHIPTRANSFER diferit. MATRECTRANSID=%s" % str(shiptransferid) )
                if abs(cx_source[4] - transfer_unitcost) > 0.000001: raise Exception( "CXCANBC v13.9.1: UNITCOST CXSTOCURI SHIPTRANSFER diferit. MATRECTRANSID=%s" % str(shiptransferid) )
                if abs(cx_source[8] + transfer_qty) > 0.000001: raise Exception( "CXCANBC v13.9.1: CXQTY SHIPTRANSFER invalid. MATRECTRANSID=%s CXQTY=%s QTY=%s" % (str(shiptransferid), str(cx_source[8]), str(transfer_qty)) )
                if not cx_source[9] or cx_source[10] is None: raise Exception("CXCANBC v14: CXSTOCURI sursa fara COMMODITYGROUP/UNITCOST pentru SHIPTRANSFER=%s" % str(shiptransferid))
                validated_cx_partitions.add((cx_source[2], cx_source[6], cx_source[5], cx_source[9], str(cx_source[10])))
                if cx_source[0] in validated_cx_ids: raise Exception("CXCANBC v14: CXSTOCURIID duplicat=%s" % str(cx_source[0]))
                validated_cx_ids.add(cx_source[0]); fifo_orgid = cx_source[1] or orgid; fifo_itemnum = cx_source[2]; fifo_costdate = cx_source[3] or transfer_date or line_actualdate; fifo_unitcost = cx_source[4]; fifo_siteid = cx_source[5] or siteid; fifo_location = cx_source[6]
                # CXSTOCURI destinatie trebuie sa existe exact o data pentru receipt.
                if has_shipreceipt:
                    cxDestSql = ( "SELECT CXSTOCURIID, ITEMNUM, UNITCOST, SITEID, LOCATION, CXREF, CXQTY, COMMODITYGROUP " "FROM CXSTOCURI " "WHERE CXREFMBO='MATRECTRANS' AND CXREFID=%s " "ORDER BY CXSTOCURIID" % str(shipreceiptid) ); rsCxDest = s.executeQuery(cxDestSql); cx_dest_rows = []
                    while rsCxDest.next(): cx_dest_rows.append(( rsCxDest.getLong(1), rsCxDest.getString(2), rsCxDest.getDouble(3), rsCxDest.getString(4), rsCxDest.getString(5), rsCxDest.getString(6), rsCxDest.getDouble(7), rsCxDest.getString(8), rsCxDest.getBigDecimal(3) ))
                    rsCxDest.close()
                    if len(cx_dest_rows) != 1: raise Exception( "CXCANBC v13.9.1: CXSTOCURI SHIPRECEIPT trebuie sa aiba exact 1 rand. " "MATRECTRANSID=%s NR=%s" % (str(shipreceiptid), str(len(cx_dest_rows))) )
                    cx_dest = cx_dest_rows[0]
                    if cx_dest[1] != itemnum or cx_dest[4] != tostoreloc or cx_dest[5] != "SHIPRECEIPT": raise Exception( "CXCANBC v13.9.1: CXSTOCURI SHIPRECEIPT nu corespunde ITEM/LOCATION/CXREF. " "MATRECTRANSID=%s" % str(shipreceiptid) )
                    if cx_dest[3] != siteid: raise Exception( "CXCANBC v13.9.1: SITEID CXSTOCURI SHIPRECEIPT diferit. MATRECTRANSID=%s" % str(shipreceiptid) )
                    if abs(cx_dest[2] - transfer_unitcost) > 0.000001: raise Exception( "CXCANBC v13.9.1: UNITCOST CXSTOCURI SHIPRECEIPT diferit. MATRECTRANSID=%s" % str(shipreceiptid) )
                    if abs(cx_dest[6] - transfer_qty) > 0.000001: raise Exception( "CXCANBC v13.9.1: CXQTY SHIPRECEIPT invalid. MATRECTRANSID=%s CXQTY=%s QTY=%s" % (str(shipreceiptid), str(cx_dest[6]), str(transfer_qty)) )
                    if not cx_dest[7] or cx_dest[8] is None: raise Exception("CXCANBC v14: CXSTOCURI destinatie fara COMMODITYGROUP/UNITCOST pentru SHIPRECEIPT=%s" % str(shipreceiptid))
                    validated_cx_partitions.add((cx_dest[1], cx_dest[4], cx_dest[3], cx_dest[7], str(cx_dest[8])))
                    if cx_dest[0] in validated_cx_ids: raise Exception("CXCANBC v14: CXSTOCURIID duplicat=%s" % str(cx_dest[0]))
                    validated_cx_ids.add(cx_dest[0])
                    # ---------------------------------------------------------
                    # v13.9.1 - PRECHECK istorice secundare ale SHIPRECEIPT.
                    # Nu conditionam de tipul locatiei (LABOR/STOREROOM).
                    # Curatarea este determinata exclusiv de legatura exacta
                    # cu MATRECTRANSID-ul receipt-ului pe care il anulam.
                    # ---------------------------------------------------------
                    # ASSETTRANS: poate sa nu existe. Daca exista, acceptam
                    # exact un singur MOVED care corespunde assetului si traseului.
                    assetTransSql = ( "SELECT ASSETTRANSID, ASSETNUM, FROMLOC, TOLOC, TRANSTYPE, SITEID, TOSITEID, ORGID " "FROM ASSETTRANS WHERE MATRECTRANSID=%s ORDER BY ASSETTRANSID" % str(shipreceiptid) ); service.log_info('*** V13.9.1 ASSETTRANS PRECHECK *** ' + assetTransSql); rsAssetTrans = s.executeQuery(assetTransSql); assettrans_rows = []
                    while rsAssetTrans.next(): assettrans_rows.append(( rsAssetTrans.getLong(1), rsAssetTrans.getString(2), rsAssetTrans.getString(3), rsAssetTrans.getString(4), rsAssetTrans.getString(5), rsAssetTrans.getString(6), rsAssetTrans.getString(7), rsAssetTrans.getString(8) ))
                    rsAssetTrans.close()
                    if len(assettrans_rows) > 1: raise Exception( "CXCANBC v13.9.1: mai multe ASSETTRANS pentru SHIPRECEIPT=%s NR=%s" % (str(shipreceiptid), str(len(assettrans_rows))) )
                    if len(assettrans_rows) == 1:
                        at = assettrans_rows[0]
                        if not matrec_rotasset: raise Exception( "CXCANBC v13.9.1: exista ASSETTRANS pentru un SHIPRECEIPT non-rotating=%s" % str(shipreceiptid) )
                        if at[1] != matrec_rotasset: raise Exception( "CXCANBC v13.9.1: ASSETNUM ASSETTRANS diferit pentru SHIPRECEIPT=%s" % str(shipreceiptid) )
                        if at[2] != fromstoreloc or at[3] != tostoreloc or at[4] != "MOVED": raise Exception( "CXCANBC v13.9.1: ASSETTRANS nu corespunde FROMLOC/TOLOC/TRANSTYPE pentru SHIPRECEIPT=%s" % str(shipreceiptid) )
                        if at[5] != siteid: raise Exception( "CXCANBC v13.9.1: SITEID ASSETTRANS diferit pentru SHIPRECEIPT=%s" % str(shipreceiptid) )
                        if at[6] and at[6] != siteid: raise Exception( "CXCANBC v13.9.1: TOSITEID ASSETTRANS diferit pentru SHIPRECEIPT=%s" % str(shipreceiptid) )
                        if at[7] and at[7] != orgid: raise Exception( "CXCANBC v13.9.1: ORGID ASSETTRANS diferit pentru SHIPRECEIPT=%s" % str(shipreceiptid) )
                        if at[0] in validated_assettrans_ids: raise Exception( "CXCANBC v13.9.1: ASSETTRANSID duplicat in precheck=%s" % str(at[0]) )
                        validated_assettrans_ids.append(at[0])
                    # CXFOLOSINTA: poate sa nu existe. Daca exista, toate
                    # randurile trebuie sa fie legate exact de receipt si sa
                    # corespunda articolului, destinatiei, site-ului si cantitatii.
                    cxFolosintaSql = ( "SELECT CXFOLOSINTAID, ITEMNUM, LOCATION, PERSONID, QUANTITY, ROTASSETNUM, SITEID, ORGID " "FROM CXFOLOSINTA " "WHERE CXREFMBO='MATRECTRANS' AND CXREFID=%s " "ORDER BY CXFOLOSINTAID" % str(shipreceiptid) ); service.log_info('*** V13.9.1 CXFOLOSINTA PRECHECK *** ' + cxFolosintaSql)
                    rsCxFolosinta = s.executeQuery(cxFolosintaSql); cxfol_rows = []
                    while rsCxFolosinta.next(): cxfol_rows.append(( rsCxFolosinta.getLong(1), rsCxFolosinta.getString(2), rsCxFolosinta.getString(3), rsCxFolosinta.getString(4), rsCxFolosinta.getDouble(5), rsCxFolosinta.getString(6), rsCxFolosinta.getString(7), rsCxFolosinta.getString(8) ))
                    rsCxFolosinta.close()
                    if len(cxfol_rows) > 0:
                        cxfol_qty_total = 0.0
                        for cxf in cxfol_rows:
                            if cxf[1] != itemnum or cxf[2] != tostoreloc: raise Exception( "CXCANBC v13.9.1: CXFOLOSINTA nu corespunde ITEMNUM/LOCATION pentru SHIPRECEIPT=%s" % str(shipreceiptid) )
                            if cxf[4] <= 0: raise Exception( "CXCANBC v13.9.1: QUANTITY CXFOLOSINTA trebuie sa fie >0 pentru SHIPRECEIPT=%s" % str(shipreceiptid) )
                            if cxf[6] != siteid: raise Exception( "CXCANBC v13.9.1: SITEID CXFOLOSINTA diferit pentru SHIPRECEIPT=%s" % str(shipreceiptid) )
                            if cxf[7] and cxf[7] != orgid: raise Exception( "CXCANBC v13.9.1: ORGID CXFOLOSINTA diferit pentru SHIPRECEIPT=%s" % str(shipreceiptid) )
                            if matrec_rotasset:
                                if len(cxfol_rows) != 1 or cxf[5] != matrec_rotasset: raise Exception( "CXCANBC v13.9.1: CXFOLOSINTA rotating invalid pentru SHIPRECEIPT=%s" % str(shipreceiptid) )
                            else:
                                if cxf[5]: raise Exception( "CXCANBC v13.9.1: CXFOLOSINTA are ROTASSETNUM pentru SHIPRECEIPT non-rotating=%s" % str(shipreceiptid) )
                            if cxf[0] in validated_cxfolosinta_ids: raise Exception( "CXCANBC v13.9.1: CXFOLOSINTAID duplicat in precheck=%s" % str(cxf[0]) )
                            validated_cxfolosinta_ids.append(cxf[0]); cxfol_qty_total += cxf[4]
                        if abs(cxfol_qty_total - transfer_qty) > 0.000001: raise Exception( "CXCANBC v13.9.1: suma CXFOLOSINTA nu corespunde SHIPRECEIPT=%s CX_QTY=%s QTY=%s" % (str(shipreceiptid), str(cxfol_qty_total), str(transfer_qty)) )
                shipped_rows.append({ "invuselineid": invuselineid, "itemnum": itemnum, "quantity": transfer_qty, "rotasset": matrec_rotasset, "asset_location_before": asset_location_before, "tostoreloc": tostoreloc, "shiptransferid": shiptransferid, "shipreceiptid": shipreceiptid, "has_shipreceipt": has_shipreceipt, "dest_fifo_ids": dest_fifo_ids, "fifo_orgid": fifo_orgid, "fifo_itemnum": fifo_itemnum, "fifo_costdate": fifo_costdate, "fifo_unitcost": fifo_unitcost, "fifo_siteid": fifo_siteid, "fifo_location": fifo_location })
                validated_matrectrans_ids.append(shiptransferid)
                if has_shipreceipt: validated_matrectrans_ids.append(shipreceiptid)
            line = linesSet.moveNext()
        if len(shipped_rows) == 0:
            raise Exception("CXCANBC v13.9.1: nu exista SHIPTRANSFER validate")
        # Nu permitem MATRECTRANS suplimentare/orfane pe acelasi INVUSEID.
        matCountSql = ( "SELECT COUNT(*) FROM MATRECTRANS WHERE INVUSEID=%s" % str(invuseid) ); rsMatCount = s.executeQuery(matCountSql)
        if not rsMatCount.next():
            rsMatCount.close()
            raise Exception("CXCANBC v13.9.1: nu s-a putut numara MATRECTRANS")
        total_matrectrans = rsMatCount.getInt(1); rsMatCount.close()
        if total_matrectrans != len(validated_matrectrans_ids):
            raise Exception( "CXCANBC v13.9.1: exista MATRECTRANS suplimentare/orfane. TOTAL=%s VALIDATE=%s" % (str(total_matrectrans), str(len(validated_matrectrans_ids))) )
        # Toate spliturile bonului trebuie sa fie cele referite de SHIPTRANSFER.
        shipped_line_ids_csv = ",".join([str(x) for x in shipped_line_ids]); splitCountSql = ( "SELECT COUNT(*) FROM INVUSELINESPLIT WHERE INVUSELINEID IN (%s)" % shipped_line_ids_csv ); rsSplitCount = s.executeQuery(splitCountSql)
        if not rsSplitCount.next():
            rsSplitCount.close()
            raise Exception("CXCANBC v13.9.1: nu s-au putut numara INVUSELINESPLIT")
        split_count_expected = rsSplitCount.getInt(1); rsSplitCount.close()
        if split_count_expected != len(validated_split_ids): raise Exception( "CXCANBC v13.9.1: exista splituri nereferite de SHIPTRANSFER. TOTAL=%s VALIDATE=%s" % (str(split_count_expected), str(len(validated_split_ids))) )
        cxcurbal_rebase_plan = build_cxcurbal_rebase_plan(validated_cx_partitions, validated_cx_ids); service.log_info( '*** CXCANBC v13.9.1 - SHIPPED PRECHECK COMPLET OK: %s tranzactii validate ***' % str(len(validated_matrectrans_ids)) )
        # -----------------------------------------------------------------
        # EXECUTIE - doar dupa PRECHECK COMPLET.
        # -----------------------------------------------------------------
        phase = "execution"; source_fifo_expected = {}
        for shipped_row in shipped_rows:
            itemnum = shipped_row["itemnum"]; quantity = shipped_row["quantity"]; rotasset = shipped_row["rotasset"]; asset_location_before = shipped_row["asset_location_before"]; tostoreloc = shipped_row["tostoreloc"]; shipreceiptid = shipped_row["shipreceiptid"]; has_shipreceipt = shipped_row["has_shipreceipt"]; dest_fifo_ids = shipped_row["dest_fifo_ids"]
            fifo_orgid = shipped_row["fifo_orgid"]; fifo_itemnum = shipped_row["fifo_itemnum"]; fifo_costdate = shipped_row["fifo_costdate"]; fifo_unitcost = shipped_row["fifo_unitcost"]; fifo_siteid = shipped_row["fifo_siteid"]; fifo_location = shipped_row["fifo_location"]
            # 4.2 Rotating: readucem assetul in sursa numai daca nu este deja acolo.
            if rotasset and asset_location_before != fromstoreloc:
                assetUpdate = ( "UPDATE ASSET SET LOCATION='%s' " "WHERE ASSETNUM='%s' AND SITEID='%s' AND LOCATION='%s'" % ( fromstoreloc.replace("'", "''"), rotasset.replace("'", "''"), siteid.replace("'", "''"), asset_location_before.replace("'", "''") ) ); service.log_info('*** V13.9.1 ASSET UPDATE *** ' + assetUpdate)
                if s.executeUpdate(assetUpdate) != 1:
                    raise Exception( "CXCANBC v13.9.1: ASSET UPDATE nu a modificat exact 1 rand pentru ASSET=%s" % rotasset )
            # 4.3 Refacem stocul in sursa pentru cantitatea exacta a tranzactiei.
            sourceBalanceUpdate = ( "UPDATE INVBALANCES SET CURBAL=CURBAL+%s " "WHERE ITEMNUM='%s' AND LOCATION='%s' AND SITEID='%s'" % ( str(quantity), itemnum.replace("'", "''"), fromstoreloc.replace("'", "''"), siteid.replace("'", "''") ) ); service.log_info('*** V13.9.1 SOURCE INVBALANCES UPDATE *** ' + sourceBalanceUpdate)
            if s.executeUpdate(sourceBalanceUpdate) != 1:
                raise Exception( "CXCANBC v13.9.1: SOURCE INVBALANCES UPDATE nu a modificat exact 1 rand pentru ITEMNUM=%s" % itemnum )
            # 4.4 Pentru receipt scadem din destinatie. Conditia CURBAL>=QTY
            # protejeaza si fata de o modificare concurenta dupa PRECHECK.
            if has_shipreceipt:
                destinationBalanceUpdate = ( "UPDATE INVBALANCES SET CURBAL=CURBAL-%s " "WHERE ITEMNUM='%s' AND LOCATION='%s' AND SITEID='%s' AND CURBAL>=%s" % ( str(quantity), itemnum.replace("'", "''"), tostoreloc.replace("'", "''"), siteid.replace("'", "''"), str(quantity) ) )
                service.log_info('*** V13.9.1 DESTINATION INVBALANCES UPDATE *** ' + destinationBalanceUpdate)
                if s.executeUpdate(destinationBalanceUpdate) != 1:
                    raise Exception( "CXCANBC v13.9.1: DESTINATION INVBALANCES UPDATE blocat/esuat pentru ITEMNUM=%s LOCATION=%s" % (itemnum, tostoreloc) )
                # 4.5 Stergem FIFO-urile exacte ale SHIPRECEIPT-ului.
                fifo_ids_csv = ",".join([str(x) for x in dest_fifo_ids]); destFifoDelete = ( "DELETE FROM INVLIFOFIFOCOST WHERE INVLIFOFIFOCOSTID IN (%s)" % fifo_ids_csv ); service.log_info('*** V13.9.1 DESTINATION FIFO DELETE *** ' + destFifoDelete); deleted_fifo = s.executeUpdate(destFifoDelete)
                if deleted_fifo != len(dest_fifo_ids):
                    raise Exception( "CXCANBC v13.9.1: FIFO DELETE a sters %s randuri, asteptat %s pentru SHIPRECEIPT=%s" % (str(deleted_fifo), str(len(dest_fifo_ids)), str(shipreceiptid)) )
            # 4.6 / 4.7 Refacem FIFO in sursa.
            if rotasset:
                rsSeq = s.executeQuery("SELECT NEXT VALUE FOR INVLIFOFIFOCOSTSEQ FROM SYSIBM.SYSDUMMY1")
                if not rsSeq.next():
                    rsSeq.close()
                    raise Exception("CXCANBC v13.9.1: nu s-a putut obtine INVLIFOFIFOCOSTSEQ")
                restored_fifo_id = rsSeq.getLong(1); rsSeq.close()
                fifoInsert = ( "INSERT INTO INVLIFOFIFOCOST " "(ORGID, ITEMNUM, ITEMSETID, CONDITIONCODE, COSTTYPE, COSTDATE, " " UNITCOST, QUANTITY, REFOBJECT, CONDRATE, SITEID, LOCATION, " " REFOBJECTID, CONTENTUID, CXNRFISAVECHI, INVLIFOFIFOCOSTID) " "VALUES ('%s','%s','SET1',NULL,'FIFO',TIMESTAMP('%s'),%s,%s,NULL,NULL,'%s','%s'," "NULL,HEX(GENERATE_UNIQUE()),NULL,%s)" % ( fifo_orgid.replace("'", "''"), fifo_itemnum.replace("'", "''"), str(fifo_costdate), str(fifo_unitcost), str(quantity), fifo_siteid.replace("'", "''"), fifo_location.replace("'", "''"), str(restored_fifo_id) ) )
                service.log_info('*** V13.9.1 ROTATING FIFO INSERT *** ' + fifoInsert)
                if s.executeUpdate(fifoInsert) != 1: raise Exception( "CXCANBC v13.9.1: FIFO INSERT nu a inserat exact 1 rand pentru ASSET=%s" % rotasset )
                source_fifo_expected[restored_fifo_id] = quantity
            else:
                fifoExistingSql = ( "SELECT INVLIFOFIFOCOSTID, QUANTITY FROM INVLIFOFIFOCOST " "WHERE ITEMNUM='%s' AND LOCATION='%s' AND SITEID='%s' AND UNITCOST=%s " "ORDER BY COSTDATE ASC FETCH FIRST 1 ROW ONLY" % ( fifo_itemnum.replace("'", "''"), fifo_location.replace("'", "''"), fifo_siteid.replace("'", "''"), str(fifo_unitcost) ) )
                rsFifo = s.executeQuery(fifoExistingSql)
                if rsFifo.next():
                    fifo_id = rsFifo.getLong(1); fifo_qty_before = rsFifo.getDouble(2); rsFifo.close(); fifoUpdate = ( "UPDATE INVLIFOFIFOCOST SET QUANTITY=QUANTITY+%s " "WHERE INVLIFOFIFOCOSTID=%s" % (str(quantity), str(fifo_id)) ); service.log_info('*** V13.9.1 NONROT FIFO UPDATE *** ' + fifoUpdate)
                    if s.executeUpdate(fifoUpdate) != 1: raise Exception("CXCANBC v13.9.1: NONROT FIFO UPDATE esuat")
                    source_fifo_expected[fifo_id] = fifo_qty_before + quantity
                else:
                    rsFifo.close(); rsSeq = s.executeQuery("SELECT NEXT VALUE FOR INVLIFOFIFOCOSTSEQ FROM SYSIBM.SYSDUMMY1")
                    if not rsSeq.next():
                        rsSeq.close()
                        raise Exception("CXCANBC v13.9.1: nu s-a putut obtine INVLIFOFIFOCOSTSEQ")
                    restored_fifo_id = rsSeq.getLong(1); rsSeq.close()
                    fifoInsert = ( "INSERT INTO INVLIFOFIFOCOST " "(ORGID, ITEMNUM, ITEMSETID, CONDITIONCODE, COSTTYPE, COSTDATE, " " UNITCOST, QUANTITY, REFOBJECT, CONDRATE, SITEID, LOCATION, " " REFOBJECTID, CONTENTUID, CXNRFISAVECHI, INVLIFOFIFOCOSTID) " "VALUES ('%s','%s','SET1',NULL,'FIFO',TIMESTAMP('%s'),%s,%s,NULL,NULL,'%s','%s'," "NULL,HEX(GENERATE_UNIQUE()),NULL,%s)" % ( fifo_orgid.replace("'", "''"), fifo_itemnum.replace("'", "''"), str(fifo_costdate), str(fifo_unitcost), str(quantity), fifo_siteid.replace("'", "''"), fifo_location.replace("'", "''"), str(restored_fifo_id) ) )
                    service.log_info('*** V13.9.1 NONROT FIFO INSERT *** ' + fifoInsert)
                    if s.executeUpdate(fifoInsert) != 1: raise Exception("CXCANBC v13.9.1: NONROT FIFO INSERT esuat")
                    source_fifo_expected[restored_fifo_id] = quantity
        # -----------------------------------------------------------------
        # POSTCHECK inainte de stergerea istoricului MATRECTRANS/CXSTOCURI.
        # -----------------------------------------------------------------
        for shipped_row in shipped_rows:
            rotasset = shipped_row["rotasset"]
            if rotasset:
                postAssetSql = ( "SELECT LOCATION FROM ASSET WHERE ASSETNUM='%s' AND SITEID='%s' FETCH FIRST 1 ROW ONLY" % (rotasset.replace("'", "''"), siteid.replace("'", "''")) ); rsPostAsset = s.executeQuery(postAssetSql)
                if not rsPostAsset.next() or rsPostAsset.getString(1) != fromstoreloc:
                    rsPostAsset.close()
                    raise Exception( "CXCANBC v13.9.1: POSTCHECK ASSET esuat pentru ASSET=%s" % rotasset )
                rsPostAsset.close()
        for source_key, qty_to_restore in required_source_qty.items():
            postSourceSql = ( "SELECT CURBAL FROM INVBALANCES WHERE ITEMNUM='%s' AND LOCATION='%s' AND SITEID='%s'" % ( source_key[0].replace("'", "''"), source_key[1].replace("'", "''"), siteid.replace("'", "''") ) ); rsPostSource = s.executeQuery(postSourceSql)
            if not rsPostSource.next():
                rsPostSource.close()
                raise Exception( "CXCANBC v13.9.1: POSTCHECK sold sursa lipsa pentru ITEMNUM=%s" % source_key[0] )
            source_after = rsPostSource.getDouble(1); rsPostSource.close(); expected_source_after = source_initial_bal[source_key] + qty_to_restore
            if abs(source_after - expected_source_after) > 0.000001: raise Exception( "CXCANBC v13.9.1: POSTCHECK sold sursa esuat. ITEMNUM=%s ACTUAL=%s EXPECTED=%s" % (source_key[0], str(source_after), str(expected_source_after)) )
        for dest_key, qty_to_remove in required_dest_qty.items():
            postDestSql = ( "SELECT CURBAL FROM INVBALANCES WHERE ITEMNUM='%s' AND LOCATION='%s' AND SITEID='%s'" % ( dest_key[0].replace("'", "''"), dest_key[1].replace("'", "''"), siteid.replace("'", "''") ) ); rsPostDest = s.executeQuery(postDestSql)
            if not rsPostDest.next():
                rsPostDest.close()
                raise Exception( "CXCANBC v13.9.1: POSTCHECK sold destinatie lipsa pentru ITEMNUM=%s LOCATION=%s" % (dest_key[0], dest_key[1]) )
            dest_after = rsPostDest.getDouble(1); rsPostDest.close(); expected_dest_after = dest_initial_bal[dest_key] - qty_to_remove
            if abs(dest_after - expected_dest_after) > 0.000001: raise Exception( "CXCANBC v13.9.1: POSTCHECK sold destinatie esuat. ITEMNUM=%s LOCATION=%s ACTUAL=%s EXPECTED=%s" % (dest_key[0], dest_key[1], str(dest_after), str(expected_dest_after)) )
        for fifo_id, expected_fifo_qty in source_fifo_expected.items():
            postFifoSql = ( "SELECT QUANTITY FROM INVLIFOFIFOCOST WHERE INVLIFOFIFOCOSTID=%s" % str(fifo_id) ); rsPostFifo = s.executeQuery(postFifoSql)
            if not rsPostFifo.next():
                rsPostFifo.close()
                raise Exception( "CXCANBC v13.9.1: POSTCHECK FIFO sursa lipsa ID=%s" % str(fifo_id) )
            fifo_qty_after = rsPostFifo.getDouble(1); rsPostFifo.close()
            if abs(fifo_qty_after - expected_fifo_qty) > 0.000001:
                raise Exception( "CXCANBC v13.9.1: POSTCHECK FIFO sursa esuat ID=%s ACTUAL=%s EXPECTED=%s" % (str(fifo_id), str(fifo_qty_after), str(expected_fifo_qty)) )
        # 4.8 Stergem ASSETTRANS validate, legate exact de SHIPRECEIPT.
        if len(validated_assettrans_ids) > 0:
            assettrans_ids_csv = ",".join([str(x) for x in validated_assettrans_ids]); assettransDelete = ( "DELETE FROM ASSETTRANS WHERE ASSETTRANSID IN (%s)" % assettrans_ids_csv ); service.log_info('*** V13.9.1 ASSETTRANS DELETE VALIDATED *** ' + assettransDelete); deleted_assettrans = s.executeUpdate(assettransDelete)
            if deleted_assettrans != len(validated_assettrans_ids):
                raise Exception( "CXCANBC v13.9.1: ASSETTRANS DELETE a sters %s randuri, asteptat %s" % (str(deleted_assettrans), str(len(validated_assettrans_ids))) )
        # 4.9 Stergem CXFOLOSINTA validate, legate exact de SHIPRECEIPT.
        if len(validated_cxfolosinta_ids) > 0:
            cxfolosinta_ids_csv = ",".join([str(x) for x in validated_cxfolosinta_ids]); cxfolosintaDelete = ( "DELETE FROM CXFOLOSINTA WHERE CXFOLOSINTAID IN (%s)" % cxfolosinta_ids_csv ); service.log_info('*** V13.9.1 CXFOLOSINTA DELETE VALIDATED *** ' + cxfolosintaDelete); deleted_cxfolosinta = s.executeUpdate(cxfolosintaDelete)
            if deleted_cxfolosinta != len(validated_cxfolosinta_ids):
                raise Exception( "CXCANBC v13.9.1: CXFOLOSINTA DELETE a sters %s randuri, asteptat %s" % (str(deleted_cxfolosinta), str(len(validated_cxfolosinta_ids))) )
        # 4.10 Stergem doar CXSTOCURI aferente tranzactiilor validate.
        ids_csv = ",".join([str(x) for x in validated_matrectrans_ids]); cxstocuriDelete = ( "DELETE FROM CXSTOCURI WHERE CXREFMBO='MATRECTRANS' AND CXREFID IN (%s)" % ids_csv ); service.log_info('*** V13.9.1 CXSTOCURI DELETE VALIDATED *** ' + cxstocuriDelete); deleted_cx = s.executeUpdate(cxstocuriDelete)
        if deleted_cx != len(validated_matrectrans_ids): raise Exception( "CXCANBC v13.9.1: CXSTOCURI DELETE a sters %s randuri, asteptat %s" % (str(deleted_cx), str(len(validated_matrectrans_ids))) )
        apply_cxcurbal_rebase_plan(cxcurbal_rebase_plan)
        # 4.11 Stergem doar MATRECTRANS validate.
        matrectransDelete = ( "DELETE FROM MATRECTRANS WHERE MATRECTRANSID IN (%s)" % ids_csv ); service.log_info('*** V13.9.1 MATRECTRANS DELETE VALIDATED *** ' + matrectransDelete); deleted_matrec = s.executeUpdate(matrectransDelete)
        if deleted_matrec != len(validated_matrectrans_ids):
            raise Exception( "CXCANBC v13.9.1: MATRECTRANS DELETE a sters %s randuri, asteptat %s" % (str(deleted_matrec), str(len(validated_matrectrans_ids))) )
        # 4.12/4.13 v16: pastram INVUSELINESPLIT + INVUSELINE pe bonul CANCELLED.
        service.log_info('*** V16 KEEP INVUSELINESPLIT (count=%s) INVUSELINE (count=%s) ***' % (str(split_count_expected), str(line_count_expected)))
        # 4.14 Adaugam CANCELLED in istoric (nu stergem SHIPPED).
        invusestatusInsert = ( "INSERT INTO INVUSESTATUS (INVUSESTATUSID, INVUSENUM, SITEID, ORGID, STATUS, CHANGEDATE, CHANGEBY) " "VALUES (NEXT VALUE FOR INVUSESTATUSSEQ, '%s', '%s', '%s', 'CANCELLED', CURRENT TIMESTAMP, '%s')" % (invusenum.replace("'", "''"), siteid.replace("'", "''"), orgid.replace("'", "''"), userInfo.getUserName().replace("'", "''")) )
        service.log_info('*** V16 INVUSESTATUS CANCELLED INSERT *** ' + invusestatusInsert)
        if s.executeUpdate(invusestatusInsert) != 1: raise Exception("INVUSESTATUS INSERT CANCELLED a esuat pentru INVUSENUM=%s" % invusenum)
        # 4.15 Bonul trece in CANCELLED (pastram RECEIPTS/SHIPMENTDATE/CXTOTALCOST pentru audit).
        invuseUpdate = ( "UPDATE INVUSE SET STATUS='CANCELLED', STATUSDATE=CURRENT TIMESTAMP " "WHERE INVUSEID=%s" % str(invuseid) ); service.log_info('*** V16 INVUSE UPDATE SHIPPED -> CANCELLED *** ' + invuseUpdate)
        if s.executeUpdate(invuseUpdate) != 1: raise Exception( "CXCANBC v16: INVUSE UPDATE nu a modificat exact 1 rand pentru INVUSEID=%s" % str(invuseid) )
        service.log_info('*** CXCANBC v16 - SHIPPED TRANSFER finished OK ***')
    con.commit(); committed = True; service.log_info('*** CXCANBC - INVUSE finished OK - Bon: %s ***' % invusenum)
except Exception, e:
    service.log_info('*** ERROR in CXCANBC - INVUSE: %s ***' % str(e)); rollback_ok = False
    if not committed:
        try: con.rollback(); rollback_ok = True
        except Exception, rollback_error: service.log_info('*** CXCANBC ROLLBACK FAILED: %s ***' % str(rollback_error))
    if phase == "preflight" and rollback_ok: service.error("CXANULARE", "NECESITASUPORT", [invusenum, preflight_reason(e)])
    raise e
finally:
    try: s.close()
    except Exception, close_error: service.log_info('*** CXCANBC STATEMENT CLOSE FAILED: %s ***' % str(close_error))
    try: con.close()
    except Exception, close_error:
        service.log_info('*** CXCANBC CONNECTION CLOSE FAILED: %s ***' % str(close_error))