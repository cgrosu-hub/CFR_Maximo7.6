# SCRIPT: CXFIFOFIXEXEC
# AUTOR: Cristian Grosu
# VERSIUNE: 3.46-JOURNAL-SPLIT
# Partea 2 a CXFIFOFIXISSUE. Fara launch point. Nu se ruleaza singur.
# RECEIPT multi-pret: fara linii noi in MATRECTRANS; split doar in CXSTOCURI.
# Jython: sub 100000 caractere, altfel BMXAA7836E Mark invalid.

def execute(context):
    check_matrectrans_exit_cost()
    message=None
    if context is None or context.getName().upper()!="CXSTOCURI":
        fail("Butonul 2 trebuie sa transmita randul CXSTOCURI")
    if not context.getProfile().hasAppOption(APP,OPTION):
        fail("Lipseste dreptul "+APP+"/"+OPTION)
    if context.toBeAdded() or context.isModified() or context.toBeDeleted() or context.getThisMboSet().toBeSaved():
        fail("Exista modificari nesalvate in jurnal")
    parent=context.getOwner()
    if parent is not None and (parent.toBeAdded() or parent.isModified()):
        fail("Inregistrarea parinte are modificari nesalvate")
    kind=context.getString("CXREF")
    refmbo=context.getString("CXREFMBO")
    if refmbo=="MATUSETRANS":
        if kind not in ("ISSUE","RETURN"):
            fail("Selecteaza o iesire ISSUE sau un retur RETURN din MATUSETRANS")
        if (kind=="ISSUE" and number(context,"CXQTY")>=ZERO) or (kind=="RETURN" and number(context,"CXQTY")<=ZERO):
            fail("Directie neconforma pentru "+kind)
    elif refmbo=="MATRECTRANS":
        if kind not in MATREC_EXITS:
            fail("MATRECTRANS: SHIPTRANSFER/TRANSFER sau RECEIPT/SHIPRECEIPT (qty<0)")
        if number(context,"CXQTY")>=ZERO:
            fail("Selecteaza randul de iesire (cantitate negativa) din jurnal")
    else:
        fail("Selecteaza iesire MATUSETRANS/MATRECTRANS")
    if context.isNull("CXREFID"):
        fail("CXREFID lipsa")
    if "MOTIV=ORDINE_DATE" in long_text(context):
        fail("ORDINE_DATE: trateaza data separat, nu prin corectia de pret")
    user=context.getUserInfo()
    opened=[]
    def query(name,where,limit=MAX_ROWS):
        ms=open_readonly(user,name,where)
        opened.append(ms)
        return ms,readrows(ms,limit)
    tx=None
    committed=False
    commit_started=False
    try:
        pm,protection=query("AUTOSCRIPT","AUTOSCRIPT='CXADDTOCXSTOCURI'",2)
        if len(protection)!=1:
            fail("Nu pot verifica protectia CXADDTOCXSTOCURI")
        content=protection[0].getString("SOURCE")
        if "def shouldCreateMatUseJournal" not in content or "and shouldCreateMatUseJournal()" not in content:
            fail("Instaleaza protectia CXADDTOCXSTOCURI")
        if refmbo=="MATRECTRANS":
            receipt_exit=kind in MATREC_RECEIPT_EXITS
            rmset,receipts=query("MATRECTRANS","MATRECTRANSID=%s" % context.getLong("CXREFID"),2)
            if len(receipts)!=1:
                fail("MATRECTRANS tinta lipsa/neunic")
            rm=receipts[0]
            if rm.getString("ISSUETYPE")!=kind:
                fail("ISSUETYPE pe MATRECTRANS difera de CXREF")
            qty_doc=number(rm,"QUANTITY")
            if receipt_exit:
                if qty_doc>=ZERO:
                    fail("RECEIPT iesire: QUANTITY trebuie negativa")
                qty_journal=qty_doc
            else:
                if qty_doc<=ZERO:
                    fail("MATRECTRANS %s: QUANTITY trebuie pozitiva" % rm.getLong("MATRECTRANSID"))
                qty_journal=-qty_doc
            if number(rm,"CONVERSION")!=ONE or number(rm,"EXCHANGERATE")!=ONE:
                fail("Conversie unitati/valuta diferita de 1")
            rate2=number(rm,"EXCHANGERATE2",True)
            if (rate2 is not None and rate2!=ONE) or (not rm.isNull("LINECOST2") and rate2!=ONE):
                fail("Conversie moneda secundara netratata")
            if rm.isNull("ACTUALDATE") or rm.isNull("TRANSDATE"):
                fail("Data sursa lipsa")
            if rm.getString("ITEMNUM")!=context.getString("ITEMNUM"):
                fail("Articol diferit fata de randul apasat")
            loc=context.getString("LOCATION")
            site=context.getString("SITEID")
            if receipt_exit:
                if rm.getString("SITEID")!=site:
                    fail("Site receptie neconform")
            else:
                if rm.getString("FROMSITEID")!=site:
                    fail("Site sursa neconform")
                if rm.isNull("FROMSTORELOC") or rm.getString("FROMSTORELOC")!=loc:
                    fail("Gestiune sursa neconforma")
            cxwhere=scope_where(context,"CXSTOCURI")
            cxset,raw=query("CXSTOCURI",cxwhere)
            all_journal=[journal_row(m) for m in raw]
            bind_screen_journal(context,all_journal)
            if any(m.getString("CURRENCYCODE")!=rm.getString("CURRENCYCODE") for m in raw if not m.isNull("CURRENCYCODE")):
                fail("Monede diferite intre jurnal si MATRECTRANS")
            journal=sorted(all_journal,key=order)
            positions=[i for i,r in enumerate(journal)
                       if r["refmbo"]=="MATRECTRANS" and r["ref"]==rm.getLong("MATRECTRANSID")
                       and r["kind"]==kind and r["qty"] is not None and r["qty"]<ZERO]
            if len(positions)!=1:
                fail("MATRECTRANS %s are %s randuri negative in CXSTOCURI. Splitul de jurnal se face o singura data, de pe randul intreg." % (
                    rm.getLong("MATRECTRANSID"),len(positions)))
            pos=positions[0]
            ij=journal[pos]
            if ij["id"]!=context.getLong("CXSTOCURIID") or text(ij["mbo"].getRowStamp())!=text(context.getRowStamp()):
                fail("Rand apasat schimbat; refresh necesar")
            if ij["date"]!=datekey(rm.getDate("ACTUALDATE")) or different(ij["qty"],qty_journal):
                fail("Cantitate/data jurnal != MATRECTRANS")
            layers=replay(journal[:pos],issue_of_returns(journal[:pos],query))
            allocation,short=consume(layers,-ij["qty"])
            if short>EPS:
                fail("Stoc anterior insuficient")
            segments=layer_segments(allocation)
            costs=[]
            for a in allocation:
                if not any(not different(a["cost"],c,PRICE_EPS) for c in costs):
                    costs.append(a["cost"])
            if len(costs)>1 and not receipt_exit:
                fail("Multi-pret pe TRANSFER/SHIPTRANSFER: split refuzat")
            if len(costs)>1 and len(segments)<2:
                fail("RECEIPT multi-pret colapsat gresit")
            plans=[]
            def plan_number(m,field,value):
                old=number(m,field,True)
                if old is None or old!=value:
                    plans.append((m,field,"NUMBER",value,text(old)))
            def plan_matrec_costs(mbo,doc_qty,cost):
                value=money(doc_qty*cost)
                for f in ("UNITCOST","ACTUALCOST","CURRENCYUNITCOST"):
                    plan_number(mbo,f,cost)
                for f in ("LINECOST","CURRENCYLINECOST"):
                    plan_number(mbo,f,value)
                if not mbo.isNull("LINECOST2"):
                    plan_number(mbo,"LINECOST2",value)
                return value
            if len(segments)==1:
                cost=segments[0]["cost"]
                if cost<ZERO or ExactNumber(cost.fixed(3))!=cost:
                    fail("Pretul FIFO nu poate fi scris")
                value=plan_matrec_costs(rm,qty_doc,cost)
                changes={ij["id"]:{"qty":qty_journal,"cost":cost}}
                after=ledger(journal,changes)
                plan_number(ij["mbo"],"UNITCOST",cost)
                for r in journal:
                    plan_number(r["mbo"],"CXCURBAL",after[r["id"]])
                if not plans:
                    message="Iesirea MATRECTRANS %s este deja la pretul FIFO %s; nimic modificat." % (
                        rm.getLong("MATRECTRANSID"),fmt(cost))
                else:
                    planned_tables=set(m.getName().upper() for m,f,k,v,old in plans)
                    select_write_sets(planned_tables,{"MATRECTRANS":rmset,"CXSTOCURI":cxset})
                    write_sets=owns(plans)
                    tx=MXServer.getMXServer().createMXTransaction()
                    for name,ms in write_sets:
                        ms.setFlag(MboConstants.NOSAVE,False)
                        ms.setMXTransaction(tx)
                        tx.add(ms)
                    for m,f,k,value,old in plans:
                        writable(m)
                        put_number(m,f,value)
                    tx.save()
                    for m,f,k,value,old in plans:
                        if different(number(m,f),value):
                            fail("Logica de salvare a suprascris planul pe %s.%s; rollback" % (m.getName(),f))
                    commit_started=True
                    tx.commit()
                    committed=True
                    receipt=segments[0].get("receipt")
                    message="SALVAT %s MATRECTRANS %s la %s, valoare %s; sursa FIFO %s." % (
                        kind,rm.getLong("MATRECTRANSID"),fmt(cost),fmt(value),
                        "INITIAL" if segments[0].get("initial") or receipt is None else text(receipt))
                    message+="\nFara modificare receptie/destinatie."
                    message+="\nRuleaza Check FIFO."
            else:
                # Split doar in CXSTOCURI. MATRECTRANS pastreaza cantitatea si pretul.
                first=segments[0]
                first_qty=-first["qty"]
                if ExactNumber(first_qty.fixed(3))!=first_qty or first["qty"]<STEP:
                    fail("Cantitate strat RECEIPT nereprezentabila")
                slice_sum=first["qty"]
                for seg in segments[1:]:
                    if seg["qty"]<STEP or ExactNumber((-seg["qty"]).fixed(3))!=-seg["qty"] or ExactNumber(seg["cost"].fixed(3))!=seg["cost"] or seg["cost"]<ZERO:
                        fail("Strat RECEIPT nereprezentabil")
                    slice_sum+=seg["qty"]
                if different(slice_sum,-qty_journal):
                    fail("Suma straturilor difera de cantitatea din MATRECTRANS")
                base_date=ij["mbo"].getDate("CXDOCUMENTDATE")
                cxset.setFlag(MboConstants.NOSAVE,False)
                extra_rows=[]
                for idx,seg in enumerate(segments[1:]):
                    doc_qty=-seg["qty"]
                    jm=cxset.addAtEnd(FLAGS)
                    for f in ("ITEMNUM","LOCATION","ORGID","SITEID","COMMODITYGROUP","CURRENCYCODE",
                              "DESCRIPTION","GLCREDITACCT","GLDEBITACCT","ISSUETO","ROTASSETNUM"):
                        copy_value(ij["mbo"],jm,f)
                    put_number(jm,"CXQTY",doc_qty)
                    put_number(jm,"UNITCOST",seg["cost"])
                    jm.setValue("CXDOCUMENTDATE",add_minutes(base_date,idx+1),FLAGS)
                    jm.setValue("CXREF",kind,FLAGS)
                    jm.setValue("CXREFMBO","MATRECTRANS",FLAGS)
                    jm.setValue("CXREFID",rm.getLong("MATRECTRANSID"),FLAGS)
                    jm.setValue("HASLD",1,FLAGS)
                    set_info(jm,"CORECTAT: CXFIFOFIX jurnal MATRECTRANS %s strat %s" % (rm.getLong("MATRECTRANSID"),idx+2))
                    extra_rows.append(journal_row(jm))
                changes={ij["id"]:{"qty":first_qty,"cost":first["cost"]}}
                for er in extra_rows:
                    changes[er["id"]]={"qty":er["qty"],"cost":er["cost"]}
                after=ledger(journal+extra_rows,changes)
                plan_number(ij["mbo"],"CXQTY",first_qty)
                plan_number(ij["mbo"],"UNITCOST",first["cost"])
                for r in journal+extra_rows:
                    if r["id"] in changes and r["id"]!=ij["id"]:
                        plan_number(r["mbo"],"UNITCOST",changes[r["id"]]["cost"])
                    plan_number(r["mbo"],"CXCURBAL",after[r["id"]])
                info=set_info(ij["mbo"],"CORECTAT: CXFIFOFIX jurnal split MATRECTRANS %s; cantitate document neschimbata" % rm.getLong("MATRECTRANSID"))
                plans.append((ij["mbo"],"DESCRIPTION_LONGDESCRIPTION","TEXT",info,""))
                tx=MXServer.getMXServer().createMXTransaction()
                cxset.setFlag(MboConstants.NOSAVE,False)
                cxset.setMXTransaction(tx)
                tx.add(cxset)
                for m,f,k,value,old in plans:
                    writable(m)
                    if k=="TEXT":
                        m.setValue(f,value,FLAGS)
                    else:
                        put_number(m,f,value)
                tx.save()
                commit_started=True
                tx.commit()
                committed=True
                parts=[fmt(first_qty)+"@"+fmt(first["cost"])]
                for seg in segments[1:]:
                    parts.append(fmt(-seg["qty"])+"@"+fmt(seg["cost"]))
                message="JURNAL SPLIT MATRECTRANS %s. Cantitatea ramane %s. CXSTOCURI: %s." % (
                    rm.getLong("MATRECTRANSID"),fmt(qty_doc),", ".join(parts))
                message+="\nNu s-a creat niciun MATRECTRANS. Ruleaza Check FIFO."
            try:
                if not refresh_table(context):
                    message+="\nRedeschide articolul pentru refresh."
            except Exception:
                message+="\nRefresh nereusit; redeschide articolul."
            return message
        if kind=="RETURN":
            rmset,returns=query("MATUSETRANS","MATUSETRANSID=%s" % context.getLong("CXREFID"),2)
            if len(returns)!=1:
                fail("MATUSETRANS tinta lipsa/neunic")
            rm=returns[0]
            if rm.getString("ISSUETYPE")!="RETURN" or number(rm,"QUANTITY")<=ZERO:
                fail("Randul apasat nu este un retur pozitiv")
            if rm.isNull("ISSUEID"):
                fail("Returul nu are ISSUEID; nu exista consumul de urmat")
            if number(rm,"CONVERSION")!=ONE or number(rm,"EXCHANGERATE")!=ONE:
                fail("Conversie unitati/valuta diferita de 1")
            if rm.isNull("ACTUALDATE") or rm.isNull("TRANSDATE"):
                fail("Data sursa lipsa")
            for f in ("ITEMNUM","SITEID"):
                if rm.getString(f)!=context.getString(f):
                    fail("Articol/site diferit fata de randul apasat")
            if rm.getString("STORELOC")!=context.getString("LOCATION"):
                fail("Gestiune neconforma")
            issue_id=rm.getLong("ISSUEID")
            iset,issues=query("MATUSETRANS","MATUSETRANSID=%s" % issue_id,2)
            if len(issues)!=1 or issues[0].getString("ISSUETYPE")!="ISSUE" or number(issues[0],"QUANTITY")>=ZERO:
                fail("Consumul %s legat prin ISSUEID lipseste sau nu este ISSUE" % issue_id)
            issue=issues[0]
            for f in ("ITEMNUM","SITEID","STORELOC","CURRENCYCODE"):
                if rm.getString(f)!=issue.getString(f):
                    fail("Returul difera la %s fata de consumul %s" % (f,issue_id))
            qty=number(rm,"QUANTITY")
            cxwhere=scope_where(context,"CXSTOCURI")
            cxset,raw=query("CXSTOCURI",cxwhere)
            all_journal=[journal_row(m) for m in raw]
            bind_screen_journal(context,all_journal)
            journal=sorted(all_journal,key=order)
            rows=[r for r in journal if r["id"]==context.getLong("CXSTOCURIID")]
            if len(rows)!=1 or rows[0]["ref"]!=rm.getLong("MATUSETRANSID") or rows[0]["kind"]!="RETURN":
                fail("Randul de jurnal al returului lipseste")
            rj=rows[0]
            if text(rj["mbo"].getRowStamp())!=text(context.getRowStamp()) or rj["date"]!=datekey(rm.getDate("ACTUALDATE")):
                fail("Rand apasat schimbat sau data de jurnal diferita; refresh necesar")
            if rj["qty"] is None or different(rj["qty"],qty):
                fail("Cantitatea din jurnal difera de retur; nu o modificam in acest pas")
            positions=[i for i,r in enumerate(journal) if r["refmbo"]=="MATUSETRANS" and r["ref"]==issue_id and r["kind"]=="ISSUE"]
            if len(positions)!=1:
                fail("Consumul %s nu are un singur rand ISSUE in jurnal" % issue_id)
            pos=positions[0]
            ij=journal[pos]
            if order(ij)>=order(rj):
                fail("Returul este inaintea consumului %s in jurnal" % issue_id)
            if ij["qty"] is None or ij["qty"]>=ZERO:
                fail("Consumul %s nu are cantitate negativa in jurnal" % issue_id)
            layers=replay(journal[:pos],issue_of_returns(journal[:pos],query))
            allocation,short=consume(layers,-ij["qty"])
            if short>EPS:
                fail("Stoc anterior insuficient pentru consumul %s" % issue_id)
            costs=set(a["cost"] for a in allocation)
            if len(costs)!=1:
                fail("Consumul %s are mai multe preturi FIFO; returul nu se corecteaza automat" % issue_id)
            cost=allocation[0]["cost"]
            if cost<ZERO or ExactNumber(cost.fixed(3))!=cost:
                fail("Pretul FIFO al consumului %s nu poate fi scris" % issue_id)
            if different(ij["cost"],cost,PRICE_EPS):
                fail("Consumul %s este in jurnal la %s, iar FIFO cere %s. Corecteaza intai consumul." % (issue_id,fmt(ij["cost"]),fmt(cost)))
            value=money(qty*cost)
            changes={rj["id"]:{"qty":qty,"cost":cost}}
            after=ledger(journal,changes)
            plans=[]
            def plan_number(m,field,value):
                old=number(m,field,True)
                if old is None or old!=value:
                    plans.append((m,field,"NUMBER",value,text(old)))
            for f in ("UNITCOST","ACTUALCOST","CURRENCYUNITCOST"):
                plan_number(rm,f,cost)
            for f in ("LINECOST","CURRENCYLINECOST"):
                plan_number(rm,f,-value)
            if not rm.isNull("LINECOST2"):
                plan_number(rm,"LINECOST2",-value)
            for r in journal:
                if r["id"] in changes:
                    plan_number(r["mbo"],"CXQTY",changes[r["id"]]["qty"])
                    plan_number(r["mbo"],"UNITCOST",changes[r["id"]]["cost"])
                plan_number(r["mbo"],"CXCURBAL",after[r["id"]])
            if not plans:
                message="Returul %s este deja la pretul FIFO %s al consumului %s; nimic modificat." % (rm.getLong("MATUSETRANSID"),fmt(cost),issue_id)
            else:
                planned_tables=set(m.getName().upper() for m,f,k,v,old in plans)
                select_write_sets(planned_tables,{"MATUSETRANS":rmset,"CXSTOCURI":cxset})
                write_sets=owns(plans)
                tx=MXServer.getMXServer().createMXTransaction()
                for name,ms in write_sets:
                    ms.setFlag(MboConstants.NOSAVE,False)
                    ms.setMXTransaction(tx)
                    tx.add(ms)
                for m,f,k,value,old in plans:
                    writable(m)
                    put_number(m,f,value)
                tx.save()
                for m,f,k,value,old in plans:
                    if different(number(m,f),value):
                        fail("Logica de salvare a suprascris planul pe %s.%s; rollback" % (m.getName(),f))
                commit_started=True
                tx.commit()
                committed=True
                message="SALVAT retur %s la %s, pretul FIFO al consumului %s." % (
                    rm.getLong("MATUSETRANSID"),fmt(cost),issue_id)
            try:
                if not refresh_table(context):
                    message+="\nRedeschide articolul pentru refresh."
            except Exception:
                message+="\nRefresh nereusit; redeschide articolul."
            return message
        fm,firstrows=query("MATUSETRANS","MATUSETRANSID=%s" % context.getLong("CXREFID"),2)
        if len(firstrows)!=1:
            fail("MATUSETRANS tinta lipsa/neunic")
        first=firstrows[0]
        if first.isNull("ITEMSETID"):
            fail("Sursa fara ITEMSETID")
        itemset=first.getString("ITEMSETID")
        if first.isNull("INVUSELINEID"):
            lines=[]
        else:
            lineset,lines=query("INVUSELINE","INVUSELINEID=%s" % first.getLong("INVUSELINEID"),2)
        if len(lines)>1:
            fail("Linie de utilizare neunica")
        if not lines:
            if first.getString("ISSUETYPE")!="ISSUE" or number(first,"QUANTITY")>=ZERO:
                fail("Randul apasat nu este un consum negativ")
            if not first.isNull("REFWO") or first.getBoolean("ROLLUP"):
                fail("Destinatie/rollup netratata de acest handler")
            if not first.isNull("ISSUEID"):
                fail("ISSUEID completat pe consumul %s; corectie automata refuzata" % first.getLong("MATUSETRANSID"))
            qty_returned=number(first,"QTYRETURNED",True)
            if qty_returned is not None and qty_returned<ZERO:
                fail("QTYRETURNED negativ pe MATUSETRANSID=%s" % first.getLong("MATUSETRANSID"))
            if number(first,"CONVERSION")!=ONE or number(first,"EXCHANGERATE")!=ONE:
                fail("Conversie unitati/valuta diferita de 1")
            rate2=number(first,"EXCHANGERATE2",True)
            if (rate2 is not None and rate2!=ONE) or (not first.isNull("LINECOST2") and rate2!=ONE):
                fail("Conversie moneda secundara netratata")
            if first.isNull("ACTUALDATE") or first.isNull("TRANSDATE"):
                fail("Data sursa lipsa")
            for f in ("ITEMNUM","SITEID"):
                if first.getString(f)!=context.getString(f):
                    fail("Articol/site diferit fata de randul apasat")
            if first.getString("STORELOC")!=context.getString("LOCATION"):
                fail("Gestiune neconforma")
            qty=number(first,"QUANTITY")
            cxwhere=scope_where(context,"CXSTOCURI")
            cxset,raw=query("CXSTOCURI",cxwhere)
            all_journal=[journal_row(m) for m in raw]
            bind_screen_journal(context,all_journal)
            if any(m.getString("CURRENCYCODE")!=first.getString("CURRENCYCODE") for m in raw):
                fail("Monede diferite intre jurnal si consum")
            journal=sorted(all_journal,key=order)
            positions=[i for i,r in enumerate(journal) if r["refmbo"]=="MATUSETRANS" and r["ref"]==first.getLong("MATUSETRANSID") and r["kind"]=="ISSUE"]
            if len(positions)!=1:
                fail("Consumul %s nu are un singur rand ISSUE in jurnal" % first.getLong("MATUSETRANSID"))
            pos=positions[0]
            ij=journal[pos]
            if ij["id"]!=context.getLong("CXSTOCURIID") or text(ij["mbo"].getRowStamp())!=text(context.getRowStamp()):
                fail("Rand apasat schimbat; refresh necesar")
            if ij["date"]!=datekey(first.getDate("ACTUALDATE")) or ij["qty"] is None or different(ij["qty"],qty):
                fail("Cantitatea sau data din jurnal difera de consum; nu le modificam in acest pas")
            prior=journal[:pos]
            layers=replay(prior,issue_of_returns(prior,query))
            allocation,short=consume(layers,-ij["qty"])
            if short>EPS:
                fail("Stoc anterior insuficient")
            costs=set(a["cost"] for a in allocation)
            if len(costs)!=1:
                fail("Consumul %s are mai multe preturi FIFO; corectia fara linie nu se face automat" % first.getLong("MATUSETRANSID"))
            cost=allocation[0]["cost"]
            if cost<ZERO or ExactNumber(cost.fixed(3))!=cost:
                fail("Pretul FIFO nu poate fi scris")
            value=money((-qty)*cost)
            changes={ij["id"]:{"qty":qty,"cost":cost}}
            cascade_fixed,cascade_stop,cascade_planned=cascade_following_issues(
                journal,pos,ij["group"],changes,query)
            after=ledger(journal,changes)
            plans=[]
            def plan_number(m,field,value):
                old=number(m,field,True)
                if old is None or old!=value:
                    plans.append((m,field,"NUMBER",value,text(old)))
            def plan_receipt_local(m,receipt):
                if receipt is None:
                    if not m.isNull("MATRECTRANSID"):
                        plans.append((m,"MATRECTRANSID","NULL",None,m.getString("MATRECTRANSID")))
                elif m.isNull("MATRECTRANSID") or m.getLong("MATRECTRANSID")!=long(receipt):
                    plans.append((m,"MATRECTRANSID","ID",long(receipt),m.getString("MATRECTRANSID")))
            for f in ("UNITCOST","ACTUALCOST","CURRENCYUNITCOST"):
                plan_number(first,f,cost)
            for f in ("LINECOST","CURRENCYLINECOST"):
                plan_number(first,f,value)
            if not first.isNull("LINECOST2"):
                plan_number(first,"LINECOST2",value)
            first_alloc=allocation[0]
            if first_alloc.get("refmbo")=="MATRECTRANS" and first_alloc.get("ref") is not None:
                plan_receipt_local(first,first_alloc["ref"])
            elif first_alloc.get("initial"):
                plan_receipt_local(first,None)
            for c in cascade_planned:
                for f in ("UNITCOST","ACTUALCOST","CURRENCYUNITCOST"):
                    plan_number(c["mbo"],f,c["cost"])
                for f in ("LINECOST","CURRENCYLINECOST"):
                    plan_number(c["mbo"],f,c["value"])
                if not c["mbo"].isNull("LINECOST2"):
                    plan_number(c["mbo"],"LINECOST2",c["value"])
                plan_receipt_local(c["mbo"],c["receipt"])
            for r in journal:
                if r["id"] in changes:
                    plan_number(r["mbo"],"UNITCOST",changes[r["id"]]["cost"])
                plan_number(r["mbo"],"CXCURBAL",after[r["id"]])
            if not plans:
                message="Consumul %s este deja la pretul FIFO %s; nimic modificat. Linia de utilizare lipseste." % (first.getLong("MATUSETRANSID"),fmt(cost))
                if cascade_stop:
                    message+=" Cascada oprita: %s." % cascade_stop
            else:
                mset=fm
                planned_tables=set(m.getName().upper() for m,f,k,v,old in plans)
                select_write_sets(planned_tables,{"MATUSETRANS":mset,"CXSTOCURI":cxset})
                write_sets=owns(plans)
                tx=MXServer.getMXServer().createMXTransaction()
                for name,ms in write_sets:
                    ms.setFlag(MboConstants.NOSAVE,False)
                    ms.setMXTransaction(tx)
                    tx.add(ms)
                for m,f,k,value,old in plans:
                    writable(m)
                    if k=="NULL":
                        m.setValueNull(f,FLAGS)
                    elif k=="ID":
                        m.setValue(f,long(value),FLAGS)
                    else:
                        put_number(m,f,value)
                tx.save()
                for m,f,k,value,old in plans:
                    if k=="NUMBER" and different(number(m,f),value):
                        fail("Logica de salvare a suprascris planul pe %s.%s; rollback" % (m.getName(),f))
                    if k=="ID" and m.getLong(f)!=long(value):
                        fail("Logica de salvare a suprascris planul pe %s.%s; rollback" % (m.getName(),f))
                    if k=="NULL" and not m.isNull(f):
                        fail("Logica de salvare a suprascris planul pe %s.%s; rollback" % (m.getName(),f))
                commit_started=True
                tx.commit()
                committed=True
                message="SALVAT consum %s la %s, valoare %s. Linia de utilizare lipseste si nu a fost recreata." % (first.getLong("MATUSETRANSID"),fmt(cost),fmt(value))
                if cascade_fixed:
                    message+=" Cascada ISSUE: %s." % ",".join(text(i) for i in cascade_fixed)
                if cascade_stop:
                    message+=" Cascada oprita: %s." % cascade_stop
            try:
                if not refresh_table(context):
                    message+="\nRedeschide articolul pentru refresh."
            except Exception:
                message+="\nRefresh nereusit; redeschide articolul."
            return message
        if first.isNull("INVUSEID"):
            fail("Sursa fara INVUSEID")
        invuseid,lineid=first.getLong("INVUSEID"),first.getLong("INVUSELINEID")
        docset,documents=query("INVUSE","INVUSEID=%s" % invuseid,2)
        if len(documents)!=1:
            fail("Document lipsa sau neunic")
        doc,line=documents[0],lines[0]
        if doc.getString("STATUS")!="COMPLETE":
            fail("Documentul trebuie sa aiba STATUS=COMPLETE")
        if line.getString("INVUSENUM")!=doc.getString("INVUSENUM") or line.getString("SITEID")!=doc.getString("SITEID"):
            fail("Legatura INVUSENUM/SITEID neconforma")
        if line.getString("USETYPE")!="ISSUE" or number(line,"CONVERSION")!=ONE:
            fail("Tip/conversie de linie netratat")
        for f in ("ITEMNUM","SITEID"):
            if first.getString(f)!=context.getString(f) or line.getString(f)!=context.getString(f):
                fail("Articol/site diferit fata de randul apasat")
        if first.getString("STORELOC")!=context.getString("LOCATION") or line.getString("FROMSTORELOC")!=context.getString("LOCATION") or line.getString("ITEMSETID")!=itemset:
            fail("Gestiune/item set neconform")
        im,invs=query("INVENTORY",scope_where(context,"INVENTORY",itemset),2)
        if len(invs)!=1 or invs[0].getString("COSTTYPE")!="FIFO":
            fail("Configuratie INVENTORY FIFO neidentificata unic")
        sql=SqlFormat("ITEMNUM=:1 AND ITEMSETID=:2")
        sql.setObject(1,"ITEM","ITEMNUM",context.getString("ITEMNUM"))
        sql.setObject(2,"ITEM","ITEMSETID",itemset)
        it,items=query("ITEM",sql.format(),2)
        if len(items)!=1 or items[0].getBoolean("ROTATING") or items[0].getBoolean("CONDITIONENABLED") or items[0].getString("LOTTYPE")!="NOLOT":
            fail("Handler pentru articole non-rotating, NOLOT, fara condition code")
        mwhere="INVUSEID=%s AND INVUSELINEID=%s" % (invuseid,lineid)
        mset,mts=query("MATUSETRANS",mwhere,MAX_SPLITS)
        if not mts:
            fail("Nu exista consumuri pe linia selectata")
        members=[]
        total=ZERO
        currency=first.getString("CURRENCYCODE")
        dimensions=("ITEMNUM","SITEID","ORGID","ITEMSETID","STORELOC","ASSETNUM","LOCATION","ISSUETO",
                    "BINNUM","LOTNUM","CONDITIONCODE","ROTASSETNUM","GLDEBITACCT","GLCREDITACCT","CURRENCYCODE")
        for m in mts:
            if m.getString("ISSUETYPE")!="ISSUE" or number(m,"QUANTITY")>=ZERO:
                fail("Grup cu retur/anulare sau alt tip decat ISSUE negativ")
            for f in dimensions:
                if m.getString(f)!=first.getString(f):
                    fail("Splituri MATUSETRANS cu dimensiuni diferite: "+f)
            if not m.isNull("REFWO") or m.getBoolean("ROLLUP"):
                fail("Destinatie/rollup netratata de acest handler")
            mid=m.getLong("MATUSETRANSID")
            if not m.isNull("ISSUEID"):
                fail("ISSUEID completat pe consumul MATUSETRANSID=%s; corectie automata refuzata" % mid)
            qty_returned=number(m,"QTYRETURNED",True)
            if qty_returned is not None and qty_returned<ZERO:
                fail("QTYRETURNED negativ pe MATUSETRANSID=%s" % mid)
            if number(m,"CONVERSION")!=ONE or number(m,"EXCHANGERATE")!=ONE:
                fail("Conversie unitati/valuta diferita de 1")
            rate2=number(m,"EXCHANGERATE2",True)
            if (rate2 is not None and rate2!=ONE) or (not m.isNull("LINECOST2") and rate2!=ONE):
                fail("Conversie moneda secundara netratata")
            if m.isNull("ACTUALDATE") or m.isNull("TRANSDATE"):
                fail("Data sursa lipsa")
            qty,cost=-number(m,"QUANTITY"),number(m,"UNITCOST")
            if cost<ZERO:
                fail("Pret sursa negativ")
            members.append({"mbo":m,"id":mid,"old_qty":qty,
                            "old_cost":cost,"date":datekey(m.getDate("ACTUALDATE"))})
            total+=qty
        line_qty=number(line,"QUANTITY")
        line_qty_mismatch=different(total,line_qty)
        if line_qty_mismatch:
            service.log_info("WARN MT sum!=linie %s/%s line=%s" % (
                fmt(total),fmt(line_qty),lineid))
        if currency!=doc.getString("CURRENCYCODE") or number(doc,"EXCHANGERATE")!=ONE:
            fail("Moneda/conversie document neconforma")
        members.sort(key=lambda m:(m["date"],m["id"]))
        cxwhere=scope_where(context,"CXSTOCURI")
        cxset,raw=query("CXSTOCURI",cxwhere)
        all_journal=[journal_row(m) for m in raw]
        bind_screen_journal(context,all_journal)
        if any(m.getString("CURRENCYCODE")!=currency for m in raw):
            fail("Monede diferite intre jurnal si consum")
        journal=sorted(all_journal,key=order)
        mids=set(m["id"] for m in members)
        line_targets=[r for r in journal if r["refmbo"]=="MATUSETRANS" and r["ref"] in mids]
        line_jbyref=dict((r["ref"],r) for r in line_targets)
        clicked_ref=context.getLong("CXREFID")
        clicked_mem=next((m for m in members if m["id"]==clicked_ref),None)
        if clicked_mem is None:
            fail("MATUSETRANS apasat nu face parte din linia de utilizare")
        sset,splitrows=query("INVUSELINESPLIT","INVUSELINEID=%s" % lineid,MAX_SPLITS)
        splits=dict((m.getLong("INVUSELINESPLITID"),m) for m in splitrows)
        line_members=list(members)
        mt_by_split={}
        for mem in line_members:
            if not mem["mbo"].isNull("INVUSELINESPLITID"):
                sid=mem["mbo"].getLong("INVUSELINESPLITID")
                mt_by_split.setdefault(sid,[]).append(mem["mbo"])
        members=[clicked_mem]
        total=clicked_mem["old_qty"]
        clicked_missing=clicked_mem["id"] not in line_jbyref
        missing_journal=[m for m in line_members if m["id"] not in line_jbyref and (
            m["id"]==clicked_ref or not m["mbo"].isNull("INVUSELINESPLITID"))]
        targets=[line_jbyref[clicked_mem["id"]]] if not clicked_missing else []
        jbyref=dict((r["ref"],r) for r in targets)
        clicked=None
        if targets:
            clicked=targets[0]
            if clicked["id"]!=context.getLong("CXSTOCURIID") or text(clicked["mbo"].getRowStamp())!=text(context.getRowStamp()):
                fail("Rand apasat schimbat; refresh necesar")
        elif context.getLong("CXSTOCURIID") not in set(r["id"] for r in line_targets):
            pass
        template=clicked_mem["mbo"]
        template_j=targets[0] if targets else (line_targets[0] if line_targets else None)
        template_split=None if template.isNull("INVUSELINESPLITID") else splits.get(template.getLong("INVUSELINESPLITID"))
        plans=[]
        def plan_number(m,field,value):
            old=number(m,field,True)
            if old is None or old!=value:
                plans.append((m,field,"NUMBER",value,text(old)))
        def plan_id(m,field,value):
            if m.isNull(field) or m.getLong(field)!=long(value):
                plans.append((m,field,"ID",long(value),m.getString(field)))
        def plan_receipt(m,receipt):
            if receipt is None:
                if not m.isNull("MATRECTRANSID"):
                    plans.append((m,"MATRECTRANSID","NULL",None,m.getString("MATRECTRANSID")))
            else:
                plan_id(m,"MATRECTRANSID",receipt)
        def apply_plan(m,f,kind,value):
            writable(m)
            if kind=="NUMBER":
                put_number(m,f,value)
            elif kind=="NULL":
                m.setValueNull(f,FLAGS)
            elif kind=="TEXT":
                m.setValue(f,text(value),FLAGS)
            else:
                m.setValue(f,long(value),FLAGS)
        def receipt_label(receipt):
            return "INITIAL" if receipt is None else text(receipt)
        if missing_journal:
            if template_j is None:
                fail("Nu exista sablon CXSTOCURI pe linie pentru PAS 3")
            parent_cxid=context.getLong("CXSTOCURIID")
            parent_ms,parent_rows=query("CXSTOCURI","CXSTOCURIID=%s" % parent_cxid,2)
            if len(parent_rows)!=1:
                fail("Rand CXSTOCURI apasat lipsa la PAS 3")
            info_row=parent_rows[0]
            new_cx=MXServer.getMXServer().getMboSet("CXSTOCURI",user)
            opened.append(new_cx)
            new_cx.setWhere("1=2")
            new_cx.reset()
            made=[]
            for mem in missing_journal:
                jm=new_cx.addAtEnd(FLAGS)
                for f in ("ITEMNUM","LOCATION","ORGID","SITEID","COMMODITYGROUP","CURRENCYCODE",
                          "DESCRIPTION","GLCREDITACCT","GLDEBITACCT","ISSUETO","ROTASSETNUM"):
                    copy_value(info_row,jm,f)
                put_number(jm,"CXQTY",-mem["old_qty"])
                put_number(jm,"UNITCOST",mem["old_cost"])
                jm.setValue("CXDOCUMENTDATE",mem["mbo"].getDate("ACTUALDATE"),FLAGS)
                jm.setValue("CXREF","ISSUE",FLAGS)
                jm.setValue("CXREFMBO","MATUSETRANS",FLAGS)
                jm.setValue("CXREFID",long(mem["id"]),FLAGS)
                jm.setValue("HASLD",1,FLAGS)
                if mem["mbo"].isNull("MATRECTRANSID"):
                    bal=number(mem["mbo"],"CURBAL",True)
                    if bal is not None:
                        put_number(jm,"CXCURBAL",bal)
                else:
                    receipt=mem["mbo"].getLong("MATRECTRANSID")
                    bal=layer_balance(query,receipt,mem["date"],mem["id"],-mem["old_qty"],[])
                    put_number(jm,"CXCURBAL",bal)
                set_info(jm,"PAS3 CXSTOCURI MATUSETRANS %s. Salveaza; Check FIFO." % mem["id"])
                made.append(mem["id"])
                service.log_info("CXFIFOFIXISSUE PAS3 create CXSTOCURI for MATUSETRANS %s qty=%s cost=%s" % (
                    mem["id"],fmt(-mem["old_qty"]),fmt(mem["old_cost"])))
            info=set_info(info_row,"PAS3 jurnal MATUSETRANS %s. Salveaza; Check FIFO." % ",".join(text(i) for i in made))
            plans.append((info_row,"DESCRIPTION_LONGDESCRIPTION","TEXT",info,""))
            documents_before=document_values(doc,line)
            operation="PAS3 INVUSEID=%s INVUSELINEID=%s MATUSETRANSID=%s" % (invuseid,lineid,clicked_ref)
            service.log_info("CXFIFOFIXISSUE PLAN "+VERSION+" "+operation)
            tx=MXServer.getMXServer().createMXTransaction()
            new_cx.setFlag(MboConstants.NOSAVE,False)
            new_cx.setMXTransaction(tx)
            tx.add(new_cx)
            parent_ms.setFlag(MboConstants.NOSAVE,False)
            parent_ms.setMXTransaction(tx)
            tx.add(parent_ms)
            for m,f,kind,value,old in plans:
                apply_plan(m,f,kind,value)
            tx.save()
            if document_values(doc,line)!=documents_before or doc.isModified() or line.isModified():
                fail("Document/linie modificate in memorie de alta logica; rollback")
            commit_started=True
            tx.commit()
            committed=True
            message="PAS 3/3 SALVAT: CXSTOCURI pentru MATUSETRANS %s.\nSalveaza pe ecran; ruleaza Check FIFO." % ",".join(text(i) for i in made)
            service.log_info("CXFIFOFIXISSUE COMMIT "+VERSION+" "+message.replace("\n"," | "))
            try:
                if not refresh_table(context):
                    message+="\nRedeschide articolul pentru refresh."
            except Exception:
                message+="\nRefresh nereusit; redeschide articolul."
            return message
        positions=[i for i,r in enumerate(journal) if r["id"]==clicked["id"]]
        if len(positions)!=1:
            fail("Consumul apasat nu are un singur rand in jurnal")
        pos=positions[0]
        prior=journal[:pos]
        layers=replay(prior,issue_of_returns(prior,query))
        allocation,short=consume(layers,total)
        if short>EPS:
            fail("Stoc anterior insuficient")
        alloc_costs=[]
        for a in allocation:
            if not any(not different(a["cost"],c,PRICE_EPS) for c in alloc_costs):
                alloc_costs.append(a["cost"])
        segments=layer_segments(allocation)
        if len(alloc_costs)>1 and len(segments)<2:
            fail("Alocare multi-pret colapsata gresit; nu se scrie medie ponderata pe un singur MATUSETRANS")
        recovery=False
        for mem in members:
            r=jbyref[mem["id"]]
            if r["kind"]!="ISSUE" or r["qty"] is None or r["qty"]>=ZERO or r["date"]!=mem["date"]:
                fail("Tip/directie/data neconforme RefID=%s; recuperarea nu schimba date" % mem["id"])
            recovery=recovery or different(r["qty"],-mem["old_qty"]) or different(r["cost"],mem["old_cost"],PRICE_EPS)
        mapped,creates=map_members(segments,members)
        if len(alloc_costs)>1 and not creates and len(mapped)<2:
            fail("Consumul %s cere line split pe %s preturi FIFO; nu se actualizeaza ca un singur pret" % (
                clicked_ref,len(alloc_costs)))
        new_total=sum((a["value"] for a in mapped),ZERO)+sum((c["value"] for c in creates),ZERO)
        if different(sum((a["qty"] for a in mapped),ZERO)+sum((c["qty"] for c in creates),ZERO),total):
            fail("Suma cantitatilor pe straturi difera de consumul original")
        used_splits=set(mt_by_split.keys())
        for mem in members:
            if not mem["mbo"].isNull("INVUSELINESPLITID"):
                used_splits.add(mem["mbo"].getLong("INVUSELINESPLITID"))
        free_splits=sorted([m for m in splitrows if m.getLong("INVUSELINESPLITID") not in used_splits],
                           key=lambda m: m.getLong("INVUSELINESPLITID"),reverse=True)
        if creates:
            for mem in members:
                if mem["mbo"].isNull("INVUSELINESPLITID") or mem["mbo"].getLong("INVUSELINESPLITID") not in splits:
                    fail("INVUSELINESPLIT lipsa pe MATUSETRANS %s" % mem["id"])
            if len(splitrows)+max(0,len(creates)-len(free_splits))>MAX_SPLITS or len(members)+len(creates)>MAX_SPLITS:
                fail("Prea multe linii dupa split FIFO")
            for c in creates:
                if free_splits:
                    sm=free_splits.pop(0)
                    c["new_split"]=False
                    c["split_mbo"]=sm
                    c["split_id"]=sm.getLong("INVUSELINESPLITID")
                else:
                    c["new_split"]=True
            if any(c.get("new_split") for c in creates) and template_split is None:
                fail("Split sablon lipsa pentru PAS 1")
        source_base=number(template,"CURBAL",True)
        running=source_base
        for a in mapped:
            a["source_balance"]=running
            if running is not None:
                running-=a["qty"]
        for c in creates:
            c["source_balance"]=running
            if running is not None:
                running-=c["qty"]
        if creates and any(c.get("new_split") for c in creates):
            for a in mapped:
                m=a["member"]["mbo"]
                if not m.isNull("INVUSELINESPLITID") and m.getLong("INVUSELINESPLITID") in splits:
                    sm=splits[m.getLong("INVUSELINESPLITID")]
                    plan_number(sm,"QUANTITY",a["qty"])
                    plan_number(sm,"UNITCOST",a["cost"])
            for c in creates:
                if not c.get("new_split"):
                    plan_number(c["split_mbo"],"QUANTITY",c["qty"])
                    plan_number(c["split_mbo"],"UNITCOST",c["cost"])
            new_split_idx=0
            created_split_ids=[]
            used_uids=set()
            for sm0 in splitrows:
                if not sm0.isNull("CONTENTUID"):
                    used_uids.add(text(sm0.getString("CONTENTUID")))
            for c in creates:
                if not c.get("new_split"):
                    continue
                sm=sset.addAtEnd(FLAGS)
                for f in SPLIT_COPY:
                    copy_value(template_split,sm,f)
                put_number(sm,"QUANTITY",c["qty"])
                put_number(sm,"UNITCOST",c["cost"])
                sm.setValue("AUTOCREATED",1,FLAGS)
                src_uid="" if template_split.isNull("CONTENTUID") else template_split.getString("CONTENTUID")
                sm.setValue("CONTENTUID",split_contentuid(src_uid,new_split_idx,used_uids),FLAGS)
                new_split_idx+=1
                created_split_ids.append(sm.getLong("INVUSELINESPLITID"))
                service.log_info("CXFIFOFIXISSUE PAS1 create split=%s qty=%s cost=%s uid=%s" % (
                    sm.getLong("INVUSELINESPLITID"),fmt(c["qty"]),fmt(c["cost"]),sm.getString("CONTENTUID")))
            info=set_info(clicked["mbo"],"PAS1 INVUSELINESPLIT +%s. Salveaza; reapeasa." % len(created_split_ids))
            plans.append((clicked["mbo"],"DESCRIPTION_LONGDESCRIPTION","TEXT",info,""))
            documents_before=document_values(doc,line)
            operation="PAS1 INVUSEID=%s INVUSELINEID=%s MATUSETRANSID=%s" % (invuseid,lineid,clicked_ref)
            service.log_info("CXFIFOFIXISSUE PLAN "+VERSION+" "+operation)
            tx=MXServer.getMXServer().createMXTransaction()
            sset.setFlag(MboConstants.NOSAVE,False)
            sset.setMXTransaction(tx)
            tx.add(sset)
            cxset.setFlag(MboConstants.NOSAVE,False)
            cxset.setMXTransaction(tx)
            tx.add(cxset)
            for m,f,kind,value,old in plans:
                apply_plan(m,f,kind,value)
            tx.save()
            if document_values(doc,line)!=documents_before:
                fail("Document/linie modificate in memorie; rollback")
            commit_started=True
            tx.commit()
            committed=True
            message="PAS 1/3 SALVAT: INVUSELINESPLIT. Splituri noi: %s.\nSalveaza pe ecran; reapeasa butonul 2 (PAS 2)." % (
                ",".join(text(i) for i in created_split_ids) if created_split_ids else "-")
            service.log_info("CXFIFOFIXISSUE COMMIT "+VERSION+" "+message.replace("\n"," | "))
            try:
                if not refresh_table(context):
                    message+="\nRedeschide articolul pentru refresh."
            except Exception:
                message+="\nRefresh nereusit; redeschide articolul."
            return message
        if creates:
            for a in mapped:
                m=a["member"]["mbo"]
                plan_number(m,"QUANTITY",-a["qty"])
                plan_number(m,"QTYREQUESTED",a["qty"])
                for f in ("UNITCOST","ACTUALCOST","CURRENCYUNITCOST"):
                    plan_number(m,f,a["cost"])
                for f in ("LINECOST","CURRENCYLINECOST"):
                    plan_number(m,f,a["value"])
                if not m.isNull("LINECOST2"):
                    plan_number(m,"LINECOST2",a["value"])
                plan_receipt(m,a["receipt"])
                if not m.isNull("INVUSELINESPLITID") and m.getLong("INVUSELINESPLITID") in splits:
                    sm=splits[m.getLong("INVUSELINESPLITID")]
                    plan_number(sm,"QUANTITY",a["qty"])
                    plan_number(sm,"UNITCOST",a["cost"])
            for c in creates:
                if not c.get("new_split"):
                    plan_number(c["split_mbo"],"QUANTITY",c["qty"])
                    plan_number(c["split_mbo"],"UNITCOST",c["cost"])
            from java.util import Date
            created_rows=[]
            base_actual=template.getDate("ACTUALDATE")
            new_split_idx=0
            used_uids=set()
            for sm0 in splitrows:
                if not sm0.isNull("CONTENTUID"):
                    used_uids.add(text(sm0.getString("CONTENTUID")))
            for idx,c in enumerate(creates):
                sid=long(c["split_id"]) if c.get("split_id") is not None else None
                prior_mt=mt_by_split.get(sid) if sid is not None else None
                if prior_mt or sid is None or c.get("split_mbo") is None:
                    if template_split is None:
                        fail("PAS 2: split sablon lipsa pentru creare INVUSELINESPLIT")
                    sm=sset.addAtEnd(FLAGS)
                    for f in SPLIT_COPY:
                        copy_value(template_split,sm,f)
                    put_number(sm,"QUANTITY",c["qty"])
                    put_number(sm,"UNITCOST",c["cost"])
                    sm.setValue("AUTOCREATED",1,FLAGS)
                    src_uid="" if template_split.isNull("CONTENTUID") else template_split.getString("CONTENTUID")
                    sm.setValue("CONTENTUID",split_contentuid(src_uid,100+new_split_idx,used_uids),FLAGS)
                    new_split_idx+=1
                    c["split_mbo"]=sm
                    c["split_id"]=sm.getLong("INVUSELINESPLITID")
                    c["new_split"]=True
                    sid=long(c["split_id"])
                    service.log_info("CXFIFOFIXISSUE PAS2 create split=%s uid=%s (inlocuire split ocupat)" % (
                        sid,sm.getString("CONTENTUID")))
                else:
                    sm=c["split_mbo"]
                    plan_number(sm,"QUANTITY",c["qty"])
                    plan_number(sm,"UNITCOST",c["cost"])
                mm=mset.addAtEnd(FLAGS)
                for f in MATUSE_COPY:
                    if f=="ACTUALDATE":
                        continue
                    copy_value(template,mm,f)
                mm.setValue("ACTUALDATE",add_minutes(base_actual,idx+1),FLAGS)
                mm.setValue("TRANSDATE",Date(),FLAGS)
                mm.setValue("ENTERBY",user.getUserName(),FLAGS)
                put_number(mm,"QUANTITY",-c["qty"])
                put_number(mm,"QTYREQUESTED",c["qty"])
                for f in ("UNITCOST","ACTUALCOST","CURRENCYUNITCOST"):
                    put_number(mm,f,c["cost"])
                for f in ("LINECOST","CURRENCYLINECOST"):
                    put_number(mm,f,c["value"])
                if not template.isNull("LINECOST2"):
                    put_number(mm,"LINECOST2",c["value"])
                if c["receipt"] is None:
                    mm.setValueNull("MATRECTRANSID",FLAGS)
                else:
                    mm.setValue("MATRECTRANSID",long(c["receipt"]),FLAGS)
                mm.setValue("INVUSELINESPLITID",sid,FLAGS)
                if not mm.isNull("ISSUEID"):
                    mm.setValueNull("ISSUEID",FLAGS)
                if not mm.isNull("QTYRETURNED"):
                    put_number(mm,"QTYRETURNED",ZERO)
                if not mm.isNull("FINCNTRLID"):
                    mm.setValueNull("FINCNTRLID",FLAGS)
                mm.setValue("CXSENTEBS",0,FLAGS)
                mm.setValue("HASLD",0,FLAGS)
                c["new_id"]=mm.getLong("MATUSETRANSID")
                c["actual_key"]=datekey(mm.getDate("ACTUALDATE"))
                created_rows.append(c)
                mt_by_split.setdefault(sid,[]).append(mm)
                service.log_info("CXFIFOFIXISSUE PAS2 create MATUSETRANS=%s split=%s qty=%s cost=%s actualdate=+%smin" % (
                    c["new_id"],c["split_id"],fmt(-c["qty"]),fmt(c["cost"]),idx+1))
            ids=",".join(text(c["new_id"]) for c in created_rows)
            info=set_info(clicked["mbo"],"PAS2 MATUSETRANS %s (+N min). Salveaza; reapeasa PAS3." % ids)
            plans.append((clicked["mbo"],"DESCRIPTION_LONGDESCRIPTION","TEXT",info,""))
            documents_before=document_values(doc,line)
            operation="PAS2 INVUSEID=%s INVUSELINEID=%s MATUSETRANSID=%s" % (invuseid,lineid,clicked_ref)
            service.log_info("CXFIFOFIXISSUE PLAN "+VERSION+" "+operation)
            tx=MXServer.getMXServer().createMXTransaction()
            for name,ms in (("INVUSELINESPLIT",sset),("MATUSETRANS",mset),("CXSTOCURI",cxset)):
                ms.setFlag(MboConstants.NOSAVE,False)
                ms.setMXTransaction(tx)
                tx.add(ms)
            for m,f,kind,value,old in plans:
                apply_plan(m,f,kind,value)
            tx.save()
            if document_values(doc,line)!=documents_before:
                fail("Document/linie modificate in memorie; rollback")
            commit_started=True
            tx.commit()
            committed=True
            cx_ids=[]
            cx_err=""
            try:
                where="MATUSETRANSID IN (%s)" % ",".join(text(c["new_id"]) for c in created_rows)
                fresh_ms,fresh_rows=query("MATUSETRANS",where,MAX_SPLITS)
                if len(fresh_rows)!=len(created_rows):
                    fail("MATUSETRANS nou lipsa dupa commit")
                new_cx=MXServer.getMXServer().getMboSet("CXSTOCURI",user)
                opened.append(new_cx)
                new_cx.setWhere("1=2")
                new_cx.reset()
                parent_ms,parent_rows=query("CXSTOCURI","CXSTOCURIID=%s" % clicked["id"],2)
                if len(parent_rows)!=1:
                    fail("Rand CXSTOCURI apasat lipsa dupa PAS 2")
                tmpl=parent_rows[0]
                for src in fresh_rows:
                    qty=-number(src,"QUANTITY")
                    cost=number(src,"UNITCOST")
                    jm=new_cx.addAtEnd(FLAGS)
                    for f in ("ITEMNUM","LOCATION","ORGID","SITEID","COMMODITYGROUP","CURRENCYCODE",
                              "DESCRIPTION","GLCREDITACCT","GLDEBITACCT","ISSUETO","ROTASSETNUM"):
                        copy_value(tmpl,jm,f)
                    put_number(jm,"CXQTY",-qty)
                    put_number(jm,"UNITCOST",cost)
                    jm.setValue("CXDOCUMENTDATE",src.getDate("ACTUALDATE"),FLAGS)
                    jm.setValue("CXREF","ISSUE",FLAGS)
                    jm.setValue("CXREFMBO","MATUSETRANS",FLAGS)
                    jm.setValue("CXREFID",src.getLong("MATUSETRANSID"),FLAGS)
                    jm.setValue("HASLD",1,FLAGS)
                    if src.isNull("MATRECTRANSID"):
                        bal=number(src,"CURBAL",True)
                        if bal is not None:
                            put_number(jm,"CXCURBAL",bal)
                    else:
                        rid=src.getLong("MATRECTRANSID")
                        bal=layer_balance(query,rid,datekey(src.getDate("ACTUALDATE")),src.getLong("MATUSETRANSID"),-qty,[])
                        put_number(jm,"CXCURBAL",bal)
                    set_info(jm,"PAS3 CXSTOCURI MATUSETRANS %s. Salveaza; Check FIFO." % src.getLong("MATUSETRANSID"))
                    cx_ids.append(src.getLong("MATUSETRANSID"))
                    service.log_info("CXFIFOFIXISSUE PAS3 dupa PAS2 CXSTOCURI MATUSETRANS %s qty=%s cost=%s" % (
                        src.getLong("MATUSETRANSID"),fmt(-qty),fmt(cost)))
                set_info(tmpl,"PAS3 jurnal MATUSETRANS %s. Salveaza; Check FIFO." % ",".join(text(i) for i in cx_ids))
                tx2=MXServer.getMXServer().createMXTransaction()
                new_cx.setFlag(MboConstants.NOSAVE,False)
                new_cx.setMXTransaction(tx2)
                tx2.add(new_cx)
                parent_ms.setFlag(MboConstants.NOSAVE,False)
                parent_ms.setMXTransaction(tx2)
                tx2.add(parent_ms)
                tx2.save()
                tx2.commit()
            except Exception as exc:
                cx_err=text(exc)
                service.log_info("CXFIFOFIXISSUE PAS3 dupa PAS2 esuat: "+cx_err)
            message="PAS 2/3 SALVAT: MATUSETRANS noi %s.\nACTUALDATE = original + N minute." % ids
            if cx_ids and not cx_err:
                message+="\nPAS3 SALVAT CXSTOCURI MATUSETRANS %s. Salveaza; Check FIFO." % ",".join(text(i) for i in cx_ids)
            else:
                message+="\nCXSTOCURI nescris (%s). Salveaza; reapeasa PAS3." % (cx_err or "necunoscut")
            for c in created_rows:
                message+="\nMATUSETRANS %s: %s la %s; receptie %s; split %s." % (
                    c["new_id"],fmt(-c["qty"]),fmt(c["cost"]),receipt_label(c["receipt"]),c["split_id"])
            service.log_info("CXFIFOFIXISSUE COMMIT "+VERSION+" "+message.replace("\n"," | "))
            try:
                if not refresh_table(context):
                    message+="\nRedeschide articolul pentru refresh."
            except Exception:
                message+="\nRefresh nereusit; redeschide articolul."
            return message
        changes={}
        for a in mapped:
            jr=jbyref[a["member"]["id"]]
            changes[jr["id"]]={"qty":-a["qty"],"cost":a["cost"]}
        cascade_fixed=[]
        cascade_stop=None
        cascade_planned=[]
        if len(alloc_costs)==1:
            cascade_fixed,cascade_stop,cascade_planned=cascade_following_issues(
                journal,pos,clicked["group"],changes,query)
        after=ledger(journal,changes)
        for a in mapped:
            m=a["member"]["mbo"]
            plan_number(m,"QUANTITY",-a["qty"])
            plan_number(m,"QTYREQUESTED",a["qty"])
            for f in ("UNITCOST","ACTUALCOST","CURRENCYUNITCOST"):
                plan_number(m,f,a["cost"])
            for f in ("LINECOST","CURRENCYLINECOST"):
                plan_number(m,f,a["value"])
            if not m.isNull("LINECOST2"):
                plan_number(m,"LINECOST2",a["value"])
            plan_receipt(m,a["receipt"])
        for c in cascade_planned:
            m=c["mbo"]
            for f in ("UNITCOST","ACTUALCOST","CURRENCYUNITCOST"):
                plan_number(m,f,c["cost"])
            for f in ("LINECOST","CURRENCYLINECOST"):
                plan_number(m,f,c["value"])
            if not m.isNull("LINECOST2"):
                plan_number(m,"LINECOST2",c["value"])
            plan_receipt(m,c["receipt"])
        for r in journal:
            if r["id"] in changes:
                plan_number(r["mbo"],"CXQTY",changes[r["id"]]["qty"])
                plan_number(r["mbo"],"UNITCOST",changes[r["id"]]["cost"])
            plan_number(r["mbo"],"CXCURBAL",after[r["id"]])
        if not plans:
            if len(alloc_costs)>1:
                fail("Consumul %s necesita line split pe preturi FIFO diferite; reapeasa butonul dupa refresh" % clicked_ref)
            msg="MATUSETRANS %s si CXSTOCURI sunt deja conforme planului local; nimic modificat." % clicked_ref
            if cascade_stop:
                msg+=" Cascada oprita: %s." % cascade_stop
            return msg
        planned_tables=set(m.getName().upper() for m,f,k,v,old in plans)
        sets_by_name={"MATUSETRANS":mset,"CXSTOCURI":cxset}
        select_write_sets(planned_tables,sets_by_name)
        write_sets=owns(plans)
        watches=[("INVUSE","INVUSEID=%s" % invuseid,signature(docset)),
                 ("INVUSELINE","INVUSELINEID=%s" % lineid,signature(lineset)),
                 ("MATUSETRANS",mwhere,signature(mset)),("CXSTOCURI",cxwhere,signature(cxset))]
        documents_before=document_values(doc,line)
        stock_before=stock_signature(user,context,itemset,opened)
        for name,where,before in watches:
            check=open_readonly(user,name,where)
            try:
                if signature(check)!=before:
                    fail("Date schimbate concurent pe "+name)
            finally:
                close(check)
        operation="INVUSEID=%s INVUSELINEID=%s MATUSETRANSID=%s user=%s" % (
            invuseid,lineid,clicked_ref,user.getUserName())
        service.log_info("CXFIFOFIXISSUE PLAN "+VERSION+" "+operation+" tabele="+",".join(sorted(planned_tables)))
        for m,f,kind,value,old in plans:
            service.log_info("CXFIFOFIXISSUE PLAN %s ID=%s %s: %s -> %s" % (m.getName(),m.getUniqueIDValue(),f,old,text(value)))
        tx=MXServer.getMXServer().createMXTransaction()
        for name,ms in write_sets:
            ms.setFlag(MboConstants.NOSAVE,False)
            ms.setMXTransaction(tx)
            tx.add(ms)
        for m,f,kind,value,old in plans:
            apply_plan(m,f,kind,value)
        tx.save()
        for m,f,kind,value,old in plans:
            if kind=="NUMBER" and different(number(m,f),value):
                fail("Logica de salvare a suprascris planul pe %s.%s; rollback" % (m.getName(),f))
            if kind=="ID" and m.getLong(f)!=long(value):
                fail("Logica de salvare a suprascris planul pe %s.%s; rollback" % (m.getName(),f))
            if kind=="NULL" and not m.isNull(f):
                fail("Logica de salvare a suprascris planul pe %s.%s; rollback" % (m.getName(),f))
        if document_values(doc,line)!=documents_before or doc.isModified() or line.isModified():
            fail("Document/linie modificate in memorie de alta logica; rollback")
        commit_started=True
        tx.commit()
        committed=True
        message="SALVAT: MATUSETRANS %s; INVUSE=%s; linie=%s; cantitate=%s; valoare FIFO=%s; actualizari=%s." % (
            clicked_ref,doc.getString("INVUSENUM"),lineid,fmt(total),fmt(new_total),len(plans))
        if recovery:
            message+="\nSincronizare stare partiala: s-au completat numai diferentele fata de plan."
        for a in mapped:
            message+="\nMATUSETRANS %s: %s la %s; receptie %s." % (a["member"]["id"],fmt(-a["qty"]),fmt(a["cost"]),receipt_label(a["receipt"]))
        if cascade_fixed:
            message+="\nCascada ISSUE (acelasi grup, max %s): %s." % (
                CASCADE_MAX_ISSUES,",".join(text(i) for i in cascade_fixed))
            for c in cascade_planned:
                message+="\n  + MATUSETRANS %s: %s la %s; receptie %s." % (
                    c["ref"],fmt(-c["qty"]),fmt(c["cost"]),receipt_label(c["receipt"]))
        if cascade_stop:
            message+="\nCascada oprita: %s." % cascade_stop
        message+="\nReturul se corecteaza cand selectezi randul lui."
        message+="\nNu Save pe ecran (ROWSTAMP vechi=BMXAA8229W)."
        try:
            service.log_info("CXFIFOFIXISSUE COMMIT "+VERSION+" "+operation+" "+message.replace("\n"," | "))
        except Exception:
            pass
        try:
            if stock_signature(user,context,itemset,opened)!=stock_before:
                message+="\nATENTIE: stoc/straturi oficiale schimbate in timpul operatiei; opriti alte corectii si verificati."
            dm,dr=query("INVUSE","INVUSEID=%s" % invuseid,2)
            lm,lr=query("INVUSELINE","INVUSELINEID=%s" % lineid,2)
            if len(dr)!=1 or len(lr)!=1 or document_values(dr[0],lr[0])!=documents_before:
                message+="\nATENTIE: document/linie schimbate indirect; verificati automatizarile."
        except Exception as exc:
            message+="\nControl post-commit indisponibil: "+text(exc)
        message+="\nINVUSE si INVUSELINE nu sunt reconciliate de acest handler."
        message+="\nRuleaza Check FIFO."
    except Exception as exc:
        if tx is not None and not committed:
            try:
                tx.rollback()
            except Exception:
                pass
        if committed:
            raise FixError("Operatiunea A FOST COMISA; verificare ulterioara esuata: "+text(exc))
        if commit_started:
            raise FixError("Eroare la COMMIT; verifica datele in DB inainte de repetare: "+text(exc))
        raise
    finally:
        for ms in reversed(opened):
            try:
                close(ms)
            except Exception:
                pass
    if message is None:
        fail("Intern: mesaj lipsa dupa executie")
    try:
        if not refresh_table(context):
            message+="\nRedeschide articolul pentru refresh."
    except Exception:
        message+="\nRefresh nereusit; redeschide articolul."
    return message
