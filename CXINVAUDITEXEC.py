# SCRIPT: CXINVAUDITEXEC
# AUTOR: Cristian Grosu
# VERSIUNE: 5.41-ROTATING-ASSET-FIFO
# Partea 2 a CXINVAUDIT. Fara launch point. Nu se ruleaza singur.
# CHRONO_REORDER_ENABLED=False: nu muta CXDOCUMENTDATE/ACTUALDATE/CXCURBAL.
# RETURN inaintea ISSUE (ISSUEID): OK + put_back daca pret/cantitate aliniate.
# CURBAL/INVLIFO sync dupa audit. Sub 100000 caractere.

CHRONO_REORDER_ENABLED=False

def apply_date_order_policy(group_rows,records):
    reserved={}
    entries=[r for r in sorted(group_rows,key=order) if ordinary_entry(r)]
    for out in sorted(group_rows,key=order):
        rec=records[out["id"]]
        if not rec["date_candidate_eligible"] or rec["status"]!="UNVERIFIED":
            continue
        if out.get("ref_id") is None or not out.get("ref_mbo") or not out.get("date"):
            continue
        if out.get("cost") is None or out["cost"]<ZERO:
            continue
        partial=rec["partial_allocations"]
        if any(far(a["cost"],out["cost"],COST_TOLERANCE) for a in partial):
            continue
        remaining=rec["shortfall"]
        proposed=[]
        for entry in entries:
            if (entry.get("ref_id") is None or entry.get("date") is None or entry.get("cost") is None or
                entry.get("ref_mbo")!=out["ref_mbo"] or entry["ref_id"]>=out["ref_id"] or
                entry["date"]<=out["date"] or far(entry["cost"],out["cost"],COST_TOLERANCE)):
                continue
            if entry.get("balance") is None:
                continue
            available=entry["qty"]-reserved.get(entry["id"],ZERO)
            take=min(remaining,max(ZERO,available))
            if take>QTY_TOLERANCE:
                proposed.append({"qty":take,"cost":entry["cost"],"source":entry["id"],
                                 "source_ref_id":entry["ref_id"],"initial":False,
                                 "priority":order(entry),"candidate_date":entry["date"]})
                remaining-=take
            if remaining<=QTY_TOLERANCE:
                break
        if remaining>QTY_TOLERANCE:
            continue
        combined=[dict(a) for a in partial]+proposed
        full=sum((a["qty"] for a in combined),ZERO)
        if far(full,-out["qty"],QTY_TOLERANCE):
            continue
        expected=sum((a["qty"]*a["cost"] for a in combined),ZERO)/full
        if far(expected,out["cost"],COST_TOLERANCE):
            continue
        for a in proposed:
            reserved[a["source"]]=reserved.get(a["source"],ZERO)+a["qty"]
        rec["status"]="DATE_ORDER"
        rec["expected"]=expected
        rec["allocations"]=combined
        rec["reason"]="Pret compatibil cu intrare ulterioara cu RefID anterior; data iesirii trebuie verificata"
        rec["date_candidates"]=proposed

def put_back(layers,qty,cost,priority,source,source_ref,source_ref_mbo=None):
    for layer in layers:
        if not far(layer["cost"],cost,COST_TOLERANCE) and layer.get("priority")==priority:
            layer["qty"]+=qty
            return
    layers.append({"qty":qty,"cost":cost,"source":source,"source_ref_id":source_ref,
                   "source_ref_mbo":source_ref_mbo,"initial":False,"priority":priority})
    layers.sort(key=lambda layer: layer["priority"])

def return_target(row,group_rows,records):
    # Returneaza (expected, link_ref, source_ref, priority, source, before_issue).
    # before_issue=True: ISSUE e dupa RETURN in jurnal; OK doar daca qty+pret aliniate.
    issue_id=row.get("issue_id")
    if issue_id is None:
        return None,"Retur fara ISSUEID",None,None,None,False
    prior=[r for r in group_rows if r.get("ref_mbo")=="MATUSETRANS" and r.get("ref_id")==issue_id
           and r.get("kind")=="ISSUE" and order(r)<order(row)]
    before_issue=False
    if len(prior)==1:
        matches=prior
    elif len(prior)>1:
        return None,"Consumul ISSUEID=%s nu este unic in jurnal, inaintea returului" % issue_id,None,None,None,False
    else:
        candidates=[r for r in group_rows if r.get("ref_mbo")=="MATUSETRANS" and r.get("ref_id")==issue_id
                    and r.get("kind")=="ISSUE"]
        if len(candidates)!=1:
            return None,"Consumul ISSUEID=%s nu este unic in jurnal" % issue_id,None,None,None,False
        issue=candidates[0]
        qty,cost=row.get("qty"),row.get("cost")
        iq,ic=issue.get("qty"),issue.get("cost")
        if qty is None or iq is None or cost is None or ic is None:
            return None,"RETURN inaintea ISSUEID=%s: pret/cantitate lipsa" % issue_id,None,None,None,False
        if iq>=-QTY_TOLERANCE or far(qty,-iq,QTY_TOLERANCE) or far(cost,ic,COST_TOLERANCE):
            return None,"RETURN inaintea ISSUEID=%s: pret/cantitate nealiniate" % issue_id,None,None,None,False
        matches=[issue]
        before_issue=True
    issue=matches[0]
    rec=records[issue["id"]]
    if rec["status"] in ("OK","BAD","DATE_ORDER") and rec["expected"] is not None:
        expected=rec["expected"]
    elif issue.get("cost") is not None:
        expected=issue["cost"]
    else:
        return None,"Consumul %s nu are pret verificabil" % issue_id,None,None,None,False
    allocs=rec.get("allocations") or []
    if allocs:
        source,source_ref,priority=allocs[0].get("source"),allocs[0].get("source_ref_id"),allocs[0].get("priority") or order(issue)
    else:
        source,source_ref,priority=issue["id"],issue.get("ref_id"),order(issue)
    return expected,issue.get("ref_id"),source_ref,priority,source,before_issue

def shipcancel_target(row,group_rows,records,label="SHIPCANCEL"):
    receipt_ref=row.get("receipt_ref")
    matches=[]
    if receipt_ref is not None:
        matches=[r for r in group_rows if r.get("ref_mbo")=="MATRECTRANS" and r.get("ref_id")==receipt_ref
                 and r.get("kind")=="SHIPTRANSFER" and order(r)<order(row)]
    if len(matches)!=1:
        qty,cost=row.get("qty"),row.get("cost")
        matches=[r for r in group_rows if r.get("kind")=="SHIPTRANSFER" and order(r)<order(row)
                 and r.get("qty") is not None and qty is not None and not far(-r["qty"],qty,QTY_TOLERANCE)
                 and r.get("cost") is not None and cost is not None and not far(r["cost"],cost,COST_TOLERANCE)]
    if len(matches)!=1:
        return None,"%s fara SHIPTRANSFER unic anterior (RECEIPTREF/cantitate/pret)" % label,None,None,None
    ship=matches[0]
    rec=records[ship["id"]]
    if rec["status"] in ("OK","BAD","DATE_ORDER") and rec["expected"] is not None:
        expected=rec["expected"]
    elif ship.get("cost") is not None:
        expected=ship["cost"]
    else:
        return None,"SHIPTRANSFER %s nu are pret verificabil" % ship.get("ref_id"),None,None,None
    allocs=rec.get("allocations") or []
    if allocs:
        source,source_ref,priority=allocs[0].get("source"),allocs[0].get("source_ref_id"),allocs[0].get("priority") or order(ship)
    else:
        source,source_ref,priority=ship["id"],ship.get("ref_id"),order(ship)
    return expected,ship.get("ref_id"),source_ref,priority,source

def is_ship_restore(row):
    kind=row.get("kind")
    qty=row.get("qty")
    if kind=="SHIPCANCEL":
        return True
    return kind=="SHIPRETURN" and qty is not None and qty>QTY_TOLERANCE

def audit_rows(rows):
    records=dict((r["id"],new_local_record(r)) for r in rows)
    if len(records)!=len(rows):
        raise ValueError("CXSTOCURIID duplicat")
    normalize_fifo_groups(rows)
    groups,issues,remaining_layers={},[],[]
    for row in rows:
        groups.setdefault(row.get("group") or "",[]).append(row)
    ledger=ZERO
    ledger_known=True
    for group,group_rows in sorted(groups.items()):
        group_rows.sort(key=order)
        book,layers,openings={},[],set()
        initial_dates,counts={},{}
        structural=None
        movement=False
        has_initial=False
        local_started=False
        local_prices=set()
        recovering=False
        had_gap=False
        seen_initial=any(r.get("kind")=="INITIAL" for r in group_rows)
        for row in group_rows:
            if row.get("kind")!="INITIAL":
                key=(row.get("date"),row.get("ref_id") or 0)
                counts[key]=counts.get(key,0)+1
        for row in group_rows:
            rec=records[row["id"]]
            kind,qty,cost,balance=row.get("kind"),row.get("qty"),row.get("cost"),row.get("balance")
            if cost is None:
                ledger_known=False
            elif kind=="INITIAL":
                if balance is None:
                    ledger_known=False
                else:
                    book[cost]=balance
                    rec["balance_expected"]=balance
            elif qty is None:
                ledger_known=False
            else:
                book[cost]=book.get(cost,ZERO)+qty
                rec["balance_expected"]=book[cost]
                rec["balance_bad"]=balance is not None and far(balance,book[cost],QTY_TOLERANCE)
            if not row.get("date"):
                structural="Data lipsa; ordinea nu poate fi stabilita"
            if kind!="INITIAL" and counts.get((row.get("date"),row.get("ref_id") or 0),0)>1:
                structural="Aceeasi data si RefID pe mai multe randuri; ordine ambigua"
            if structural:
                rec["reason"]=structural
                continue
            if kind=="INITIAL":
                if (movement or cost is None or cost<ZERO or balance is None or balance<ZERO or
                    cost in openings):
                    structural="INITIAL incomplet/negativ/duplicat/dupa miscari"
                    rec["reason"]=structural
                    for prior in group_rows:
                        if records[prior["id"]]["status"]=="INITIAL":
                            records[prior["id"]]["status"]="UNVERIFIED"
                            records[prior["id"]]["reason"]=structural
                    continue
                openings.add(cost)
                initial_dates[row["date"]]=cost
                has_initial=True
                if balance>QTY_TOLERANCE:
                    layers.append({"qty":balance,"cost":cost,"source":row["id"],
                                   "source_ref_id":row.get("ref_id"),"source_ref_mbo":row.get("ref_mbo"),
                                   "initial":True,"priority":order(row)})
                rec["status"]="INITIAL"
                continue
            movement=True
            if qty is None or cost is None or cost<ZERO:
                structural="Cantitate/pret lipsa sau pret negativ"
                rec["reason"]=structural
                continue
            if kind=="RETURN":
                if qty<=QTY_TOLERANCE:
                    rec["reason"]="Retur fara cantitate pozitiva"
                    continue
                expected,link_ref,source_ref,priority,source,before_issue=return_target(
                    row,group_rows,records)
                if expected is None:
                    rec["reason"]=link_ref
                    continue
                rec["expected"]=expected
                rec["link_ref"]=link_ref
                rec["return_before_issue"]=bool(before_issue)
                rec["status"]="BAD" if far(cost,expected,COST_TOLERANCE) else "OK"
                rec["allocations"]=[{"qty":qty,"cost":expected,"source":source,"source_ref_id":source_ref,
                                     "initial":False,"priority":priority}]
                origin=records.get(source)
                source_mbo=None if origin is None else origin["row"].get("ref_mbo")
                put_back(layers,qty,expected,priority,source,source_ref,source_mbo)
                local_prices.add(expected)
                local_started=True
                continue
            if kind=="SHIPCANCEL" or (kind=="SHIPRETURN" and qty>QTY_TOLERANCE):
                if qty<=QTY_TOLERANCE:
                    rec["reason"]="%s fara cantitate pozitiva" % kind
                    continue
                expected,link_ref,source_ref,priority,source=shipcancel_target(
                    row,group_rows,records,label=kind)
                if expected is None:
                    expected=cost
                    link_ref=None
                    source_ref=row.get("ref_id")
                    priority=order(row)
                    source=row["id"]
                    source_mbo=row.get("ref_mbo")
                    rec["expected"]=expected
                    rec["status"]="OK"
                    rec["allocations"]=[{"qty":qty,"cost":expected,"source":source,"source_ref_id":source_ref,
                                         "initial":False,"priority":priority}]
                    put_back(layers,qty,expected,priority,source,source_ref,source_mbo)
                    local_prices.add(expected)
                    local_started=True
                    continue
                rec["expected"]=expected
                rec["link_ref"]=link_ref
                rec["status"]="BAD" if far(cost,expected,COST_TOLERANCE) else "OK"
                rec["allocations"]=[{"qty":qty,"cost":expected,"source":source,"source_ref_id":source_ref,
                                     "initial":False,"priority":priority}]
                origin=records.get(source)
                source_mbo=None if origin is None else origin["row"].get("ref_mbo")
                put_back(layers,qty,expected,priority,source,source_ref,source_mbo)
                local_prices.add(expected)
                local_started=True
                continue
            if kind in VOID_TYPES:
                if qty>=-QTY_TOLERANCE:
                    rec["reason"]="%s fara cantitate negativa" % kind
                    continue
                required=-qty
                available=sum((l["qty"] for l in layers if not far(l["cost"],cost,COST_TOLERANCE)),ZERO)
                if available+QTY_TOLERANCE<required:
                    rec["reason"]="Stoc pe pret insuficient pentru %s" % kind
                    continue
                allocations,short=consume_at_cost(layers,required,cost,newest_first=True)
                if short>QTY_TOLERANCE or not allocations:
                    rec["reason"]="%s nu a putut anula stocul pe pret" % kind
                    continue
                rec["allocations"]=allocations
                rec["expected"]=cost
                rec["status"]="OK"
                local_started=True
                continue
            if kind in AMBIGUOUS_TYPES:
                rec["reason"]="Tip %s fara alocare verificabila in jurnal" % kind
                continue
            if abs(qty)<=QTY_TOLERANCE:
                rec["status"]="N/A"
                continue
            if qty>ZERO:
                if kind not in ENTRY_TYPES:
                    structural="Tip de intrare neimplementat: "+txt(kind)
                    rec["reason"]=structural
                    continue
                available=qty
                if (not seen_initial and cost not in local_prices) or recovering:
                    if balance is None:
                        structural="Sold lipsa pe intrarea necesara bazei locale"
                        rec["reason"]=structural
                        continue
                    known=sum((l["qty"] for l in layers if l["cost"]==cost),ZERO)
                    available=min(qty,max(ZERO,balance-known))
                local_prices.add(cost)
                local_started=True
                if available>QTY_TOLERANCE:
                    layers.append({"qty":available,"cost":cost,"source":row["id"],
                                   "source_ref_id":row.get("ref_id"),"source_ref_mbo":row.get("ref_mbo"),
                                   "initial":False,"priority":order(row)})
                    layers.sort(key=lambda l:l["priority"])
                    if balance is not None and balance>=ZERO:
                        recovering=False
                rec["status"]="INPUT"
                continue
            if kind not in EXIT_TYPES and kind not in ENTRY_TYPES:
                structural="Tip de iesire neimplementat: "+txt(kind)
                rec["reason"]=structural
                continue
            rec["local_basis"]=not has_initial or had_gap
            if not has_initial and not local_started:
                recovering=True
                had_gap=True
                mark_shortage(rec,layers,-qty,"Lipseste INITIAL si nu exista intrari anterioare utilizabile")
                continue
            available=sum((l["qty"] for l in layers),ZERO)
            gate=balance is not None and balance>=ZERO
            covered=available+QTY_TOLERANCE>=-qty
            if recovering and not gate and not covered:
                mark_shortage(rec,layers,-qty,"Reluare in asteptare: sold negativ sau lipsa")
                continue
            if available+QTY_TOLERANCE < -qty:
                recovering=True
                had_gap=True
                mark_shortage(rec,layers,-qty,"Stoc anterior insuficient; verificare reluata dar baza incompleta" if gate else "Stoc anterior insuficient; se asteapta o baza locala recuperabila")
                continue
            rec["resumed"]=recovering
            recovering=False
            allocations=consume(layers,-qty)
            rec["allocations"]=allocations
            rec["expected"]=sum((a["qty"]*a["cost"] for a in allocations),ZERO)/(-qty)
            rec["status"]="BAD" if far(cost,rec["expected"],COST_TOLERANCE) else "OK"
        if not structural:
            apply_date_order_policy(group_rows,records)
        ledger+=sum(book.values(),ZERO)
        for layer in layers:
            if layer["qty"]>QTY_TOLERANCE:
                remaining_layers.append(layer)
        if structural:
            issues.append("Grupa %s: %s" % (group or "(gol)",structural))
        elif recovering:
            issues.append("Grupa %s: segment fara baza cronologica recuperata" % (group or "(gol)"))
        if had_gap or not seen_initial:
            issues.append("Grupa %s: istoric local incomplet/reluat; trecutul nu este certificat" % (group or "(gol)"))
    return {"records":records,"issues":issues,"ledger_qty":ledger if ledger_known else None,
            "layers":remaining_layers}
def open_invlifofifocost(inventory):
    ms=inventory.getMboSet("INVLIFOFIFOCOST")
    if ms is None:
        raise ValueError("Relatia INVENTORY.INVLIFOFIFOCOST lipseste")
    ms.reset()
    return ms

def journal_fifo_complete(audit):
    if audit.get("ledger_qty") is None:
        return False,"Sold CXSTOCURI nedeterminabil"
    for rec in audit["records"].values():
        status=rec.get("status")
        if status in ("UNVERIFIED","DATE_ORDER"):
            return False,"Exista tranzactii FIFO necorecte (data/neverificate)"
        row=rec["row"]
        f=flag(rec)
        if f=="Y":
            return False,"Exista BADFIFO=Y (pret sau sold CXCURBAL gresit)"
        if f=="U" and (is_outgoing(row) or row.get("kind") in ("RETURN","SHIPCANCEL") or is_ship_restore(row)):
            return False,"Exista iesiri/retururi/anulari neverificate"
        if row.get("kind")!="INITIAL" and not row.get("date"):
            return False,"Exista tranzactii fara data in CXSTOCURI"
    return True,"OK"

def local_summary(audit,unknown_origins):
    records=list(audit["records"].values())
    exits=[r for r in records if is_outgoing(r["row"])]
    counts=dict((f,sum(1 for r in exits if flag(r)==f)) for f in ("N","Y","U"))
    date_orders=sum(1 for r in exits if r["status"]=="DATE_ORDER")
    structural=sum(1 for r in records if r["status"]=="UNVERIFIED" and not is_outgoing(r["row"]))
    sold_flags=sum(1 for r in records if r.get("balance_bad") or r.get("balance_missing"))
    entry_bad=sum(1 for r in records if ordinary_entry(r["row"]) and flag(r)=="Y")
    verdict="DIFERENTE" if counts["Y"] or entry_bad or sold_flags else (
        "NECONCLUDENT" if counts["U"] or structural else (
            "N CU EXCEPTII ORDINE_DATE" if date_orders else "OK"))
    entries=sum(1 for r in records if ordinary_entry(r["row"]))
    returns=[r for r in records if r["row"].get("kind")=="RETURN"]
    return_counts=dict((f,sum(1 for r in returns if flag(r)==f)) for f in ("N","Y","U"))
    if return_counts["Y"]:
        verdict="DIFERENTE"
    lines=["CHECK FIFO","Verdict: "+verdict,"",
           "IESIRI","  OK: %s" % counts["N"],"  Diferente pret/sold: %s" % counts["Y"],
           "  Neverificate: %s" % counts["U"],
           "  Iesiri cu data de verificat: %s" % date_orders,"",
           "INTRARI","  Informative: %s" % entries,
           "  Sold CXCURBAL gresit (BADFIFO=Y): %s" % sold_flags,
           "  Provenienta necunoscuta: %s" % unknown_origins,
           "  Cantitate ramasa in CXSTOCURI: %s" % fmt_ro(audit["ledger_qty"])]
    if returns:
        lines.extend(["","RETURURI","  OK: %s" % return_counts["N"],
                      "  Diferente pret/sold: %s" % return_counts["Y"],
                      "  Neverificate: %s" % return_counts["U"]])
    return "\n".join(lines)

def sync_invbalances_curbal(inventory,target_qty,audit,script_service):
    from psdi.server import MXServer
    from psdi.mbo import MboConstants,SqlFormat
    from psdi.util import MaxType
    from java.util import Locale,TimeZone
    flags=MboConstants.NOACCESSCHECK | MboConstants.NOVALIDATION_AND_NOACTION
    ok,reason=journal_fifo_complete(audit)
    if not ok:
        msg="\n".join([
            "ACTUALIZARE INVBALANCES.CURBAL: sarita",
            "  Motiv: %s" % reason,
            "  CURBAL se actualizeaza doar cand toate tranzactiile CXSTOCURI sunt OK FIFO (data/pret/cantitate).",
        ])
        script_service.log_info("CXINVAUDIT "+msg.replace("\n"," | "))
        return msg
    layers_qty=sum((layer["qty"] for layer in (audit.get("layers") or [])),ZERO)
    if target_qty is None:
        target_qty=layers_qty
    ms=None
    try:
        ms=MXServer.getMXServer().getMboSet("INVBALANCES",inventory.getUserInfo())
        condition=SqlFormat("ITEMNUM=:1 AND SITEID=:2 AND LOCATION=:3")
        condition.setObject(1,"INVBALANCES","ITEMNUM",inventory.getString("ITEMNUM"))
        condition.setObject(2,"INVBALANCES","SITEID",inventory.getString("SITEID"))
        condition.setObject(3,"INVBALANCES","LOCATION",inventory.getString("LOCATION"))
        ms.setWhere(condition.format())
        ms.reset()
        rows=[]
        m=ms.moveFirst()
        while m is not None:
            if len(rows)>=MAX_ROWS:
                raise ValueError("Limita INVBALANCES depasita")
            qty=numeric_field(m,"CURBAL")
            if qty is None:
                raise ValueError("INVBALANCES.CURBAL lipsa")
            rows.append({"mbo":m,"qty":qty,"id":m.getUniqueIDValue()})
            m=ms.moveNext()
        if not rows:
            raise ValueError("INVBALANCES lipsa pentru articol/gestiune")
        current_total=sum((r["qty"] for r in rows),ZERO)
        if not far(current_total,target_qty,QTY_TOLERANCE):
            msg="\n".join([
                "ACTUALIZARE INVBALANCES.CURBAL: deja aliniat",
                "  CURBAL = CXSTOCURI = %s" % fmt_ro(target_qty),
            ])
            script_service.log_info("CXINVAUDIT "+msg.replace("\n"," | "))
            return msg
        nonzero=[r for r in rows if abs(r["qty"])>QTY_TOLERANCE]
        if len(rows)>1 and len(nonzero)>1:
            msg="\n".join([
                "ACTUALIZARE INVBALANCES.CURBAL: sarita",
                "  Motiv: %s randuri INVBALANCES cu sold; actualizare automata nesigura" % len(nonzero),
                "  CURBAL cumulat %s -> tinta %s" % (fmt_ro(current_total),fmt_ro(target_qty)),
            ])
            script_service.log_info("CXINVAUDIT "+msg.replace("\n"," | "))
            return msg
        target_row=nonzero[0] if nonzero else rows[0]
        old=target_row["qty"]
        mv=target_row["mbo"].getMboValue("CURBAL")
        typed=MaxType.createMaxType(Locale.US,TimeZone.getTimeZone("UTC"),mv.getType())
        typed.setScale(mv.getScale())
        typed.setValue(txt(target_qty))
        target_row["mbo"].setValue("CURBAL",typed,flags)
        written=numeric_field(target_row["mbo"],"CURBAL")
        if written is None or far(written,target_qty,QTY_TOLERANCE):
            raise ValueError("Nu pot scrie CURBAL=%s (citit %s)" % (
                txt(target_qty),"null" if written is None else txt(written)))
        ms.save()
        msg="\n".join([
            "ACTUALIZARE INVBALANCES.CURBAL",
            "  Conditie: CXSTOCURI complet OK FIFO (data/pret/cantitate)",
            "  INVBALANCESID=%s: %s -> %s" % (target_row["id"],fmt_ro(old),fmt_ro(target_qty)),
        ])
        script_service.log_info("CXINVAUDIT "+msg.replace("\n"," | "))
        return msg
    except Exception as exc:
        msg="ACTUALIZARE INVBALANCES.CURBAL ESUATA: %s" % txt(exc)
        script_service.log_info("CXINVAUDIT "+msg)
        return msg
    finally:
        close_set(ms)

def recorded_balances_by_cost(rows):
    last={}
    for row in sorted(rows,key=order):
        if row.get("cost") is None or not row.get("date"):
            raise ValueError("Pret/data lipsa; sold final nedeterminabil")
        last[row["cost"]]=row
    totals={}
    for cost,row in last.items():
        if row.get("balance") is None:
            raise ValueError("Sold final lipsa")
        totals[cost]=totals.get(cost,ZERO)+row["balance"]
    return totals

def normalize_ref_mbo(value):
    text=txt(value).strip()
    if not text or text=="-":
        return None
    return text

def desired_fifo_layers(rows,audit):
    by_id=dict((r["id"],r) for r in rows)
    layers=[]
    for layer in list(audit.get("layers") or []):
        src=by_id.get(layer.get("source"))
        ref_mbo=normalize_ref_mbo(layer.get("source_ref_mbo") or (None if src is None else src.get("ref_mbo")))
        ref_id=layer.get("source_ref_id")
        if ref_id is None and src is not None:
            ref_id=src.get("ref_id")
        layers.append({
            "cost":layer["cost"],"qty":layer["qty"],"ref_mbo":ref_mbo,"ref_id":ref_id,
            "priority":layer.get("priority") or ("",0,0),"source":layer.get("source"),
            "date":None if src is None else src.get("date"),"initial":bool(layer.get("initial")),
        })
    layers.sort(key=lambda layer:(layer["priority"],layer.get("source") or 0))
    return layers

def invlifo_age_key(layer):
    ref_mbo=normalize_ref_mbo(layer.get("ref_mbo"))
    ref_id=layer.get("ref_id")
    if ref_mbo=="MATRECTRANS" and ref_id is not None:
        return (0,long(ref_id),0)
    return (1,txt(layer.get("date") or ""),layer.get("source") or 0)

def collapse_invlifo_desired(layers):
    grouped=[]
    for layer in layers:
        matched=None
        for item in grouped:
            if not far(item["cost"],layer["cost"],COST_TOLERANCE):
                matched=item
                break
        if matched is None:
            grouped.append({
                "cost":layer["cost"],"qty":layer["qty"],
                "ref_mbo":layer.get("ref_mbo"),"ref_id":layer.get("ref_id"),
                "priority":layer.get("priority"),"source":layer.get("source"),
                "date":layer.get("date"),"initial":bool(layer.get("initial")),
            })
            continue
        matched["qty"]=matched["qty"]+layer["qty"]
        if invlifo_age_key(layer)<invlifo_age_key(matched):
            matched["ref_mbo"]=layer.get("ref_mbo")
            matched["ref_id"]=layer.get("ref_id")
            matched["priority"]=layer.get("priority")
            matched["source"]=layer.get("source")
            matched["date"]=layer.get("date")
            matched["initial"]=bool(layer.get("initial"))
            matched["cost"]=layer["cost"]
    grouped.sort(key=lambda layer:(invlifo_age_key(layer),price_label(layer["cost"])))
    return grouped

def fifo_layers_situation(rows,audit,script_service):
    layers=desired_fifo_layers(rows,audit)
    title="SITUATIE STRATURI FIFO (CXSTOCURI)"
    lines=[title,"  UNITCOST | SOLD | CXREFMBO | CXREFID"]
    detail=[]
    total=ZERO
    for layer in layers:
        detail.append("  %s | %s | %s | %s" % (
            price_label(layer["cost"]),fmt_ro(layer["qty"]),
            "-" if layer["ref_mbo"] is None else txt(layer["ref_mbo"]),
            "-" if layer["ref_id"] is None else txt(layer["ref_id"])))
        total+=layer["qty"]
    if not detail:
        detail.append("  (niciun strat ramas)")
    script_service.log_info("CXINVAUDIT LAYERS: "+" | ".join([title]+detail+["TOTAL SOLD %s" % fmt_ro(total)]))
    visible=lines+detail[:MAX_LAYER_LINES]
    if len(detail)>MAX_LAYER_LINES:
        visible.append("  Primele %s straturi; detalii complete in log." % MAX_LAYER_LINES)
    visible.append("  TOTAL SOLD: %s" % fmt_ro(total))
    return "\n".join(visible),total

def same_ref(left_mbo,left_id,right_mbo,right_id):
    return normalize_ref_mbo(left_mbo)==normalize_ref_mbo(right_mbo) and left_id==right_id

def plan_invlifo_alignment(desired,current):
    unused=list(current)
    updates,keeps,missing=[],[],[]
    for layer in desired:
        candidates=[]
        for row in unused:
            if far(row["cost"],layer["cost"],COST_TOLERANCE):
                continue
            if not same_ref(row.get("ref_mbo"),row.get("ref_id"),layer.get("ref_mbo"),layer.get("ref_id")):
                continue
            candidates.append(row)
        if not candidates:
            missing.append(layer)
            continue
        exact=[row for row in candidates if not far(row["qty"],layer["qty"],QTY_TOLERANCE)]
        pool=exact or candidates
        pool.sort(key=lambda row:(0 if not far(row["qty"],layer["qty"],QTY_TOLERANCE) else 1,row["id"]))
        chosen=pool[0]
        unused.remove(chosen)
        same_qty=not far(chosen["qty"],layer["qty"],QTY_TOLERANCE)
        if same_qty:
            keeps.append(chosen)
        else:
            updates.append({"row":chosen,"layer":layer,"reuse":False})
    unused.sort(key=lambda row:row["id"])
    creates=[]
    for layer in missing:
        if unused:
            chosen=unused.pop(0)
            updates.append({"row":chosen,"layer":layer,"reuse":True})
        else:
            creates.append(layer)
    return keeps,updates,unused,creates

def format_missing_invlifo_creates(creates):
    lines=["INVLIFOFIFOCOST CREARI OMISE",
           "  Nu se creeaza randuri noi in INVLIFOFIFOCOST.",
           "  Straturi CXSTOCURI fara rand reutilizabil: %s" % len(creates),
           "  UNITCOST | SOLD | CXREFMBO | CXREFID"]
    for layer in creates[:MAX_LAYER_LINES]:
        lines.append("  %s | %s | %s | %s" % (
            price_label(layer["cost"]),fmt_ro(layer["qty"]),
            "-" if layer.get("ref_mbo") is None else txt(layer.get("ref_mbo")),
            "-" if layer.get("ref_id") is None else txt(layer.get("ref_id"))))
    if len(creates)>MAX_LAYER_LINES:
        lines.append("  Primele %s straturi lipsa; restul in log." % MAX_LAYER_LINES)
    return "\n".join(lines)

def parse_layer_date(value):
    if not value:
        return None
    from java.text import SimpleDateFormat
    from java.util import TimeZone
    f=SimpleDateFormat("yyyy-MM-dd HH:mm:ss")
    f.setTimeZone(TimeZone.getTimeZone("UTC"))
    return f.parse(txt(value)[:19])

def apply_invlifo_layer(mbo,layer,flags,script_service):
    put_invlifo_number(mbo,"UNITCOST",layer["cost"])
    put_invlifo_number(mbo,"QUANTITY",layer["qty"])
    ref_mbo=normalize_ref_mbo(layer.get("ref_mbo"))
    ref_id=layer.get("ref_id")
    current_mbo=None if mbo.isNull("REFOBJECT") else mbo.getString("REFOBJECT")
    current_id=None if mbo.isNull("REFOBJECTID") else mbo.getLong("REFOBJECTID")
    if not same_ref(current_mbo,current_id,ref_mbo,ref_id):
        if ref_mbo is None:
            mbo.setValueNull("REFOBJECT",flags)
        else:
            mbo.setValue("REFOBJECT",ref_mbo,flags)
        if ref_id is None:
            mbo.setValueNull("REFOBJECTID",flags)
        else:
            mbo.setValue("REFOBJECTID",long(ref_id),flags)
        if ref_mbo and ref_id is not None:
            try:
                if mbo.isNull("CONDRATE"):
                    mbo.setValue("CONDRATE",100,flags)
            except Exception:
                pass
    costdate=parse_layer_date(layer.get("date"))
    if costdate is not None:
        try:
            if mbo.isNull("COSTDATE") or (not mbo.isNull("COSTDATE") and mbo.getDate("COSTDATE").getTime()!=costdate.getTime()):
                mbo.setValue("COSTDATE",costdate,flags)
        except Exception as exc:
            script_service.log_info("CXINVAUDIT COSTDATE neschimbat pe INVLIFOFIFOCOSTID=%s: %s" % (
                mbo.getUniqueIDValue(),txt(exc)))

def read_invbalances_curbal(inventory):
    from psdi.server import MXServer
    from psdi.mbo import SqlFormat
    ms=None
    try:
        ms=MXServer.getMXServer().getMboSet("INVBALANCES",inventory.getUserInfo())
        condition=SqlFormat("ITEMNUM=:1 AND SITEID=:2 AND LOCATION=:3")
        condition.setObject(1,"INVBALANCES","ITEMNUM",inventory.getString("ITEMNUM"))
        condition.setObject(2,"INVBALANCES","SITEID",inventory.getString("SITEID"))
        condition.setObject(3,"INVBALANCES","LOCATION",inventory.getString("LOCATION"))
        ms.setWhere(condition.format())
        ms.reset()
        total,count=ZERO,0
        m=ms.moveFirst()
        while m is not None:
            count+=1
            if count>MAX_ROWS:
                raise ValueError("Limita INVBALANCES depasita")
            qty=numeric_field(m,"CURBAL")
            if qty is None:
                raise ValueError("INVBALANCES.CURBAL lipsa")
            total+=qty
            m=ms.moveNext()
        if count==0:
            raise ValueError("INVBALANCES lipsa pentru articol/gestiune")
        return total
    finally:
        close_set(ms)

def put_invlifo_number(mbo,field,value):
    from psdi.mbo import MboConstants
    from psdi.util import MaxType
    from java.util import Locale, TimeZone
    flags=MboConstants.NOACCESSCHECK | MboConstants.NOVALIDATION_AND_NOACTION
    current=numeric_field(mbo,field)
    if current is not None and not far(current,value,QTY_TOLERANCE):
        return False
    mv=mbo.getMboValue(field)
    typed=MaxType.createMaxType(Locale.US,TimeZone.getTimeZone("UTC"),mv.getType())
    typed.setScale(mv.getScale())
    typed.setValue(txt(value))
    if far(dec(typed.asString()),value,QTY_TOLERANCE):
        raise ValueError("Precizia %s nu pastreaza %s pe INVLIFOFIFOCOST" % (field,txt(value)))
    mbo.setValue(field,typed,flags)
    written=numeric_field(mbo,field)
    if written is None or far(written,value,QTY_TOLERANCE):
        raise ValueError("Nu pot scrie %s=%s pe INVLIFOFIFOCOST (citit %s)" % (
            field,txt(value),"null" if written is None else txt(written)))
    return True

def item_is_rotating(inventory):
    from psdi.server import MXServer
    from psdi.mbo import SqlFormat
    ms=None
    try:
        ms=MXServer.getMXServer().getMboSet("ITEM",inventory.getUserInfo())
        if inventory.isNull("ITEMSETID"):
            condition=SqlFormat("ITEMNUM=:1")
            condition.setObject(1,"ITEM","ITEMNUM",inventory.getString("ITEMNUM"))
        else:
            condition=SqlFormat("ITEMNUM=:1 AND ITEMSETID=:2")
            condition.setObject(1,"ITEM","ITEMNUM",inventory.getString("ITEMNUM"))
            condition.setObject(2,"ITEM","ITEMSETID",inventory.getString("ITEMSETID"))
        ms.setWhere(condition.format())
        ms.reset()
        item=ms.moveFirst()
        if item is None:
            return None
        return bool(item.getBoolean("ROTATING"))
    finally:
        close_set(ms)

def rotating_layer_units(qty):
    if qty is None or qty<=QTY_TOLERANCE:
        return 0
    whole=qty.value.setScale(0,RoundingMode.HALF_EVEN)
    if far(ExactNumber(whole),qty,QTY_TOLERANCE):
        raise ValueError("ROTATING: sold strat non-intreg %s" % fmt_ro(qty))
    n=int(whole.longValue())
    if n<0:
        raise ValueError("ROTATING: sold strat negativ")
    return n

def expand_rotating_desired(layers):
    units=[]
    for layer in layers:
        for _ in range(rotating_layer_units(layer["qty"])):
            units.append({"cost":layer["cost"],"qty":ONE,"ref_mbo":layer.get("ref_mbo"),
                          "ref_id":layer.get("ref_id"),"date":layer.get("date"),
                          "source":layer.get("source"),"priority":layer.get("priority"),
                          "initial":bool(layer.get("initial"))})
    return units

def _rotating_row_ok(row,layer):
    return (not far(row["cost"],layer["cost"],COST_TOLERANCE)
            and not far(row["qty"],ONE,QTY_TOLERANCE)
            and same_ref(row.get("ref_mbo"),row.get("ref_id"),layer.get("ref_mbo"),layer.get("ref_id")))

def plan_rotating_invlifo(desired,current):
    unused=list(current)
    updates,keeps,missing=[],[],[]
    for layer in desired:
        cands=[r for r in unused if same_ref(r.get("ref_mbo"),r.get("ref_id"),
                                             layer.get("ref_mbo"),layer.get("ref_id"))]
        if not cands:
            missing.append(layer)
            continue
        cands.sort(key=lambda r:(0 if _rotating_row_ok(r,layer) else 1,r["id"]))
        chosen=cands[0]
        unused.remove(chosen)
        if _rotating_row_ok(chosen,layer):
            keeps.append(chosen)
        else:
            updates.append({"row":chosen,"layer":layer,"reuse":False})
    unused.sort(key=lambda r:r["id"])
    creates=[]
    for layer in missing:
        if unused:
            updates.append({"row":unused.pop(0),"layer":layer,"reuse":True})
        else:
            creates.append(layer)
    return keeps,updates,unused,creates

def _sql_ts(value):
    from java.sql import Timestamp
    if isinstance(value, Timestamp):
        return value
    d=parse_layer_date(value)
    return None if d is None else Timestamp(d.getTime())

def rotating_layers_from_pairs(pairs):
    # pairs: (assetnum, matrectransid, cost, date). Un activ = un strat qty=1.
    layers=[]
    seen_assets,seen_refs=set(),set()
    for asset, ref_id, cost, date in pairs:
        if not asset:
            raise ValueError("ROTATING: ASSETNUM lipsa")
        if asset in seen_assets:
            raise ValueError("ROTATING: ASSETNUM duplicat %s" % asset)
        seen_assets.add(asset)
        if ref_id is None or cost is None or date is None:
            raise ValueError("ROTATING: activ %s fara MATRECTRANS de intrare in gestiune" % asset)
        if ref_id in seen_refs:
            raise ValueError("ROTATING: MATRECTRANSID %s legat de mai multe active" % ref_id)
        seen_refs.add(ref_id)
        layers.append({"cost":cost,"qty":ONE,"ref_mbo":"MATRECTRANS","ref_id":long(ref_id),
                       "date":date,"source":None,"priority":("A",asset,0),"initial":False})
    return layers

def rotating_asset_fifo_layers(inventory):
    # Ultima MATRECTRANS QTY=1 cu TOSTORELOC=gestiunea curenta, per activ ACTIVE.
    from psdi.server import MXServer
    if inventory.isNull("ITEMNUM") or inventory.isNull("SITEID") or inventory.isNull("LOCATION"):
        raise ValueError("ITEMNUM/SITEID/LOCATION lipsa pe INVENTORY")
    itemnum,siteid,location=inventory.getString("ITEMNUM"),inventory.getString("SITEID"),inventory.getString("LOCATION")
    itemset="" if inventory.isNull("ITEMSETID") else inventory.getString("ITEMSETID")
    def q(value):
        return txt(value).replace("'","''")
    itemset_sql=(" AND a.ITEMSETID='%s'" % q(itemset)) if itemset else ""
    sql=("SELECT a.ASSETNUM, m.MATRECTRANSID, m.UNITCOST, m.ACTUALDATE "
         "FROM ASSET a LEFT JOIN MATRECTRANS m ON m.MATRECTRANSID=("
         "SELECT MAX(m2.MATRECTRANSID) FROM MATRECTRANS m2 "
         "WHERE m2.ROTASSETNUM=a.ASSETNUM AND m2.ITEMNUM=a.ITEMNUM "
         "AND m2.TOSTORELOC=a.LOCATION AND m2.SITEID=a.SITEID AND m2.QUANTITY=1) "
         "WHERE a.ITEMNUM='%s' AND a.LOCATION='%s' AND a.SITEID='%s' AND a.STATUS='ACTIVE'%s "
         "ORDER BY a.ASSETNUM" % (q(itemnum),q(location),q(siteid),itemset_sql))
    db=MXServer.getMXServer().getDBManager()
    key=inventory.getUserInfo().getConnectionKey()
    con=st=rs=None
    pairs=[]
    try:
        con=db.getConnection(key)
        st=con.createStatement()
        rs=st.executeQuery(sql)
        while rs.next():
            if len(pairs)>=MAX_ROWS:
                raise ValueError("Limita ASSET rotating depasita")
            ref_id=rs.getLong(2)
            if rs.wasNull():
                ref_id=None
            cost=None if rs.getBigDecimal(3) is None else ExactNumber(rs.getBigDecimal(3))
            pairs.append((rs.getString(1), ref_id, cost, rs.getTimestamp(4)))
    finally:
        if rs is not None:
            try: rs.close()
            except Exception: pass
        if st is not None:
            try: st.close()
            except Exception: pass
        if con is not None:
            db.freeConnection(key)
    if not pairs:
        raise ValueError("Niciun ASSET ACTIVE in gestiune")
    return rotating_layers_from_pairs(pairs)

def _sql_set_nullish(ps,idx,value,sql_type,as_long=False):
    from java.sql import Types
    if value is None:
        ps.setNull(idx,sql_type)
    elif as_long:
        ps.setLong(idx,long(value))
    elif sql_type==Types.VARCHAR:
        ps.setString(idx,value)
    else:
        ps.setTimestamp(idx,value)

def apply_rotating_invlifo_sql(inventory,keeps,updates,deletes,creates,script_service):
    from psdi.server import MXServer
    from java.util import UUID
    from java.sql import Types
    if inventory.isNull("ORGID") or inventory.isNull("ITEMSETID"):
        raise ValueError("ORGID/ITEMSETID lipsa pe INVENTORY")
    orgid,itemnum,itemset=inventory.getString("ORGID"),inventory.getString("ITEMNUM"),inventory.getString("ITEMSETID")
    siteid,location=inventory.getString("SITEID"),inventory.getString("LOCATION")
    db=MXServer.getMXServer().getDBManager()
    key=inventory.getUserInfo().getConnectionKey()
    con=ps_upd=ps_del=ps_ins=None
    try:
        con=db.getConnection(key)
        if updates:
            ps_upd=con.prepareStatement(
                "UPDATE INVLIFOFIFOCOST SET UNITCOST=?,QUANTITY=?,COSTDATE=?,"
                "REFOBJECT=?,REFOBJECTID=?,CONDRATE=?,COSTTYPE=? WHERE INVLIFOFIFOCOSTID=?")
            for item in updates:
                layer,row=item["layer"],item["row"]
                ps_upd.setBigDecimal(1,layer["cost"].value)
                ps_upd.setBigDecimal(2,ONE.value)
                _sql_set_nullish(ps_upd,3,_sql_ts(layer.get("date")),Types.TIMESTAMP)
                _sql_set_nullish(ps_upd,4,normalize_ref_mbo(layer.get("ref_mbo")),Types.VARCHAR)
                _sql_set_nullish(ps_upd,5,layer.get("ref_id"),Types.BIGINT,True)
                ps_upd.setInt(6,100)
                ps_upd.setString(7,"FIFO")
                ps_upd.setLong(8,long(row["id"]))
                if ps_upd.executeUpdate()!=1:
                    raise ValueError("UPDATE INVLIFOFIFOCOSTID=%s esuat" % row["id"])
        if deletes:
            ps_del=con.prepareStatement("DELETE FROM INVLIFOFIFOCOST WHERE INVLIFOFIFOCOSTID=?")
            for row in deletes:
                ps_del.setLong(1,long(row["id"]))
                if ps_del.executeUpdate()!=1:
                    raise ValueError("DELETE INVLIFOFIFOCOSTID=%s esuat" % row["id"])
        if creates:
            ps_ins=con.prepareStatement(
                "INSERT INTO INVLIFOFIFOCOST (ORGID,ITEMNUM,ITEMSETID,CONDITIONCODE,COSTTYPE,"
                "COSTDATE,UNITCOST,QUANTITY,REFOBJECT,CONDRATE,SITEID,LOCATION,REFOBJECTID,"
                "CONTENTUID,INVLIFOFIFOCOSTID) VALUES "
                "(?,?,?,NULL,'FIFO',?,?,?,?,100,?,?,?,?,NEXT VALUE FOR INVLIFOFIFOCOSTSEQ)")
            for layer in creates:
                ps_ins.setString(1,orgid); ps_ins.setString(2,itemnum); ps_ins.setString(3,itemset)
                _sql_set_nullish(ps_ins,4,_sql_ts(layer.get("date")),Types.TIMESTAMP)
                ps_ins.setBigDecimal(5,layer["cost"].value)
                ps_ins.setBigDecimal(6,ONE.value)
                _sql_set_nullish(ps_ins,7,normalize_ref_mbo(layer.get("ref_mbo")),Types.VARCHAR)
                ps_ins.setString(8,siteid); ps_ins.setString(9,location)
                _sql_set_nullish(ps_ins,10,layer.get("ref_id"),Types.BIGINT,True)
                ps_ins.setString(11,UUID.randomUUID().toString())
                if ps_ins.executeUpdate()!=1:
                    raise ValueError("INSERT INVLIFOFIFOCOST esuat")
        con.commit()
        script_service.log_info("CXINVAUDIT ROTATING INVLIFO SQL keep=%s upd=%s del=%s ins=%s" % (
            len(keeps),len(updates),len(deletes),len(creates)))
    except Exception:
        if con is not None:
            try: con.rollback()
            except Exception: pass
        raise
    finally:
        for ps in (ps_upd,ps_del,ps_ins):
            if ps is not None:
                try: ps.close()
                except Exception: pass
        if con is not None:
            db.freeConnection(key)

def sync_invlifofifocost_rotating(inventory,rows,audit,script_service):
    try:
        desired=rotating_asset_fifo_layers(inventory)
        curbal=read_invbalances_curbal(inventory)
    except Exception as exc:
        msg="CORECTIE INVLIFOFIFOCOST ROTATING: sarita (%s)" % txt(exc)
        script_service.log_info("CXINVAUDIT "+msg); return msg
    layers_qty=sum((u["qty"] for u in desired),ZERO)
    if far(curbal,layers_qty,QTY_TOLERANCE):
        msg="CORECTIE INVLIFOFIFOCOST ROTATING: sarita (CURBAL %s != ASSET ACTIVE %s)" % (
            fmt_ro(curbal),fmt_ro(layers_qty))
        script_service.log_info("CXINVAUDIT "+msg); return msg
    ms=None
    try:
        ms=open_scope(inventory,"INVLIFOFIFOCOST",True)
        current=[]
        m=ms.moveFirst()
        while m is not None:
            if len(current)>=MAX_ROWS:
                raise ValueError("Limita INVLIFOFIFOCOST depasita")
            price,qty=numeric_field(m,"UNITCOST"),numeric_field(m,"QUANTITY")
            if price is None or qty is None:
                raise ValueError("INVLIFOFIFOCOST fara pret/cantitate")
            current.append({"id":m.getLong("INVLIFOFIFOCOSTID"),"cost":price,"qty":qty,
                "ref_mbo":None if m.isNull("REFOBJECT") else m.getString("REFOBJECT"),
                "ref_id":None if m.isNull("REFOBJECTID") else m.getLong("REFOBJECTID")})
            m=ms.moveNext()
        keeps,updates,deletes,creates=plan_rotating_invlifo(desired,current)
        if not updates and not deletes and not creates:
            msg="CORECTIE INVLIFOFIFOCOST ROTATING: deja aliniat (%s x qty=1)" % len(keeps)
            script_service.log_info("CXINVAUDIT "+msg); return msg
        apply_rotating_invlifo_sql(inventory,keeps,updates,deletes,creates,script_service)
        reused=sum(1 for i in updates if i.get("reuse"))
        msg="\n".join([
            "CORECTIE INVLIFOFIFOCOST ROTATING (SQL)",
            "  Conditie: 1 strat / ASSET ACTIVE; CURBAL=%s" % fmt_ro(curbal),
            "  Tinta: %s x QUANTITY=1, REFOBJECT=MATRECTRANS" % len(desired),
            "  Pastrate: %s | Update: %s (reuse %s) | Delete: %s | Insert: %s" % (
                len(keeps),len(updates),reused,len(deletes),len(creates))])
        script_service.log_info("CXINVAUDIT "+msg.replace("\n"," | ")); return msg
    except Exception as exc:
        msg="CORECTIE INVLIFOFIFOCOST ROTATING ESUATA: %s" % txt(exc)
        script_service.log_info("CXINVAUDIT "+msg); return msg
    finally:
        close_set(ms)

def sync_invlifofifocost(inventory,rows,audit,script_service):
    from psdi.mbo import MboConstants
    flags=MboConstants.NOACCESSCHECK | MboConstants.NOVALIDATION_AND_NOACTION
    rotating=item_is_rotating(inventory)
    if rotating is None:
        msg="CORECTIE INVLIFOFIFOCOST: sarita (ITEM negasit; fara comasare)"
        script_service.log_info("CXINVAUDIT "+msg)
        return msg
    if rotating:
        return sync_invlifofifocost_rotating(inventory,rows,audit,script_service)
    desired=collapse_invlifo_desired(desired_fifo_layers(rows,audit))
    layers_qty=sum((layer["qty"] for layer in desired),ZERO)
    try:
        curbal=read_invbalances_curbal(inventory)
    except Exception as exc:
        msg="CORECTIE INVLIFOFIFOCOST: sarita (%s)" % txt(exc)
        script_service.log_info("CXINVAUDIT "+msg)
        return msg
    if far(curbal,layers_qty,QTY_TOLERANCE):
        msg="CORECTIE INVLIFOFIFOCOST: sarita (CURBAL %s != CXSTOCURI %s)" % (
            fmt_ro(curbal),fmt_ro(layers_qty))
        script_service.log_info("CXINVAUDIT "+msg)
        return msg
    try:
        ms=open_invlifofifocost(inventory)
        current=[]
        m=ms.moveFirst()
        while m is not None:
            if len(current)>=MAX_ROWS:
                raise ValueError("Limita INVLIFOFIFOCOST depasita")
            price,qty=numeric_field(m,"UNITCOST"),numeric_field(m,"QUANTITY")
            if price is None or qty is None:
                raise ValueError("INVLIFOFIFOCOST fara pret/cantitate")
            current.append({
                "id":m.getLong("INVLIFOFIFOCOSTID"),"cost":price,"qty":qty,
                "ref_mbo":None if m.isNull("REFOBJECT") else m.getString("REFOBJECT"),
                "ref_id":None if m.isNull("REFOBJECTID") else m.getLong("REFOBJECTID"),
                "mbo":m,
            })
            m=ms.moveNext()
        keeps,updates,deletes,creates=plan_invlifo_alignment(desired,current)
        sections=[]
        if not updates and not deletes and not creates:
            msg="CORECTIE INVLIFOFIFOCOST: deja aliniat la straturile CXSTOCURI"
            script_service.log_info("CXINVAUDIT "+msg)
            return msg
        reused=sum(1 for item in updates if item.get("reuse"))
        if updates or deletes:
            for item in updates:
                apply_invlifo_layer(item["row"]["mbo"],item["layer"],flags,script_service)
            for row in deletes:
                row["mbo"].delete(flags)
            ms.save()
            sections.append("\n".join([
                "CORECTIE INVLIFOFIFOCOST",
                "  Conditie: CURBAL = CXSTOCURI = %s" % fmt_ro(curbal),
                "  Pastrate: %s" % len(keeps),
                "  Actualizate: %s (reutilizate: %s)" % (len(updates),reused),
                "  Sterse: %s" % len(deletes),
                "  Fara create (doar stergere/editare/reutilizare).",
            ]))
        elif creates:
            sections.append("\n".join([
                "CORECTIE INVLIFOFIFOCOST",
                "  Conditie: CURBAL = CXSTOCURI = %s" % fmt_ro(curbal),
                "  Nicio stergere/editare posibila: nu exista randuri de reutilizat.",
            ]))
        if creates:
            sections.append(format_missing_invlifo_creates(creates))
        msg="\n\n".join(sections)
        script_service.log_info("CXINVAUDIT "+msg.replace("\n"," | "))
        return msg
    except Exception as exc:
        msg="CORECTIE INVLIFOFIFOCOST ESUATA: %s" % txt(exc)
        script_service.log_info("CXINVAUDIT "+msg)
        return msg

def invlifo_totals(inventory,rows,script_service):
    ms=None
    try:
        journal=recorded_balances_by_cost(rows)
        ms=open_scope(inventory,"INVLIFOFIFOCOST",True)
        official,count,invalid={},0,0
        m=ms.moveFirst()
        while m is not None:
            count+=1
            if count>MAX_ROWS:
                raise ValueError("Limita de straturi oficiale depasita")
            price,qty=numeric_field(m,"UNITCOST"),numeric_field(m,"QUANTITY")
            if price is None or qty is None:
                raise ValueError("Strat oficial fara pret/cantitate")
            invalid+=1 if price<ZERO or qty<ZERO else 0
            official[price]=official.get(price,ZERO)+qty
            m=ms.moveNext()
        jq,fq=sum(journal.values(),ZERO),sum(official.values(),ZERO)
        jv=sum((p*q for p,q in journal.items()),ZERO)
        fv=sum((p*q for p,q in official.items()),ZERO)
        lines=["TOTALURI",
               "  Cantitate: CXSTOCURI %s | INVLIFOFIFOCOST %s | diferenta %s" % (fmt_ro(jq),fmt_ro(fq),fmt_ro(jq-fq)),
               "  Valoare: CXSTOCURI %s | INVLIFOFIFOCOST %s | diferenta %s" % (fmt_ro(jv),fmt_ro(fv),fmt_ro(jv-fv))]
        if count==0:
            lines.append("  INVLIFOFIFOCOST nu are randuri. Comparatia foloseste zero.")
        if invalid:
            lines.append("  INVLIFOFIFOCOST cu pret sau cantitate negativa: %s." % invalid)
        script_service.log_info("CXINVAUDIT TOTALURI: "+" | ".join(lines))
        return "\n".join(lines)
    except Exception as exc:
        script_service.log_info("CXINVAUDIT TOTALURI indisponibile: "+txt(exc))
        return "TOTALURI INDISPONIBILE: %s. Auditul local ramane valabil." % txt(exc)
    finally:
        close_set(ms)


def chrono_exit(row):
    # Same-day exit-after-entry: doar ISSUE MATUSETRANS.
    # MATRECTRANS pe aceeasi zi e reordonat dupa CXREFID.
    kind,qty,ref_mbo=row.get("kind"),row.get("qty"),row.get("ref_mbo")
    if qty is None or qty>=-QTY_TOLERANCE:
        return False
    return kind=="ISSUE" and ref_mbo=="MATUSETRANS"

def chrono_entry(row):
    # RETURN / SHIPRETURN+ / SHIPCANCEL nu sunt ancore same-day.
    if chrono_exit(row):
        return False
    if row.get("kind") in ("INITIAL","RETURN","SHIPCANCEL"):
        return False
    qty=row.get("qty")
    if row.get("kind")=="SHIPRETURN" and qty is not None and qty>QTY_TOLERANCE:
        return False
    return qty is not None and qty>QTY_TOLERANCE

def second_bucket(row):
    d=row.get("date")
    if not d:
        return None
    return txt(d)[:19]

def day_bucket(row):
    d=row.get("date")
    if not d:
        return None
    return txt(d)[:10]

def minute_floor_ms(ms):
    ms=long(ms)
    return ms-(ms%60000)

def second_key_ms(ms):
    return long(ms)//1000

def chrono_effective_ms(rows,prior_shifts=None):
    effective={}
    for r in rows:
        if r.get("date_ms") is not None:
            effective[r["id"]]=long(r["date_ms"])
    for s in (prior_shifts or []):
        effective[s["row"]["id"]]=long(s["new_ms"])
    return effective

def plan_matrectrans_refid_day_shifts(rows):
    # Aceeasi zi, CXREFMBO=MATRECTRANS: cronologia urmeaza CXREFID crescator.
    by_day={}
    for r in rows:
        if normalize_ref_mbo(r.get("ref_mbo"))!="MATRECTRANS":
            continue
        if r.get("kind")=="INITIAL":
            continue
        if r.get("ref_id") is None or r.get("date_ms") is None:
            continue
        day=day_bucket(r)
        if day is None:
            continue
        by_day.setdefault(day,[]).append(r)
    shifts=[]
    for day,group in sorted(by_day.items()):
        if len(group)<2:
            continue
        desired=sorted(group,key=lambda r:(long(r["ref_id"]),r["id"]))
        violated=False
        for i in range(1,len(desired)):
            if long(desired[i]["date_ms"])<long(desired[i-1]["date_ms"]):
                violated=True
                break
        if not violated:
            continue
        base_ms=minute_floor_ms(min(long(r["date_ms"]) for r in group))
        for i,r in enumerate(desired):
            new_ms=long(base_ms)+i*60000
            if long(r["date_ms"])!=new_ms:
                shifts.append({"row":r,"new_ms":new_ms,"day":day,"step":"MR%s" % (i+1)})
    return shifts

def plan_same_day_shifts(rows,prior_shifts=None):
    # ISSUE MATUSETRANS inaintea intrarilor (fara restore ca ancora) =>
    # max(intrari)+1..N min. MATRECTRANS: plan_matrectrans_refid_day_shifts.
    effective=chrono_effective_ms(rows,prior_shifts)
    by_day={}
    for r in rows:
        day=day_bucket(r)
        if day is None or r["id"] not in effective:
            continue
        by_day.setdefault(day,[]).append(r)
    shifts=[]
    for day,group in sorted(by_day.items()):
        entries=[r for r in group if chrono_entry(r)]
        exits=[r for r in group if chrono_exit(r)]
        if not entries or not exits:
            continue
        base_ms=max(effective[r["id"]] for r in entries)
        entry_secs=set(second_key_ms(effective[r["id"]]) for r in entries)
        to_move=[r for r in exits
                 if effective[r["id"]]<=base_ms or second_key_ms(effective[r["id"]]) in entry_secs]
        if not to_move:
            continue
        to_move.sort(key=lambda r:(effective[r["id"]],r.get("ref_id") or 0,r["id"]))
        for i,r in enumerate(to_move):
            new_ms=long(base_ms)+(i+1)*60000
            if effective[r["id"]]!=new_ms:
                shifts.append({"row":r,"new_ms":new_ms,"day":day,"step":i+1})
                effective[r["id"]]=new_ms
    return shifts

def plan_return_after_issue_shifts(rows,prior_shifts=None):
    # RETURN aferent consumului: strict dupa zi/ora/minut a ISSUE (ISSUEID).
    effective=chrono_effective_ms(rows,prior_shifts)
    issues_by_ref={}
    for r in rows:
        if r.get("kind")=="ISSUE" and r.get("ref_mbo")=="MATUSETRANS" and r.get("ref_id") is not None:
            issues_by_ref[r["ref_id"]]=r
    shifts=[]
    used={}
    returns=[r for r in rows if r.get("kind")=="RETURN" and r.get("ref_mbo")=="MATUSETRANS"
             and r.get("issue_id") is not None and r.get("date_ms") is not None]
    returns.sort(key=lambda r:(r.get("date") or "",r.get("ref_id") or 0,r["id"]))
    for r in returns:
        issue=issues_by_ref.get(r["issue_id"])
        if issue is None or issue["id"] not in effective:
            continue
        issue_min=minute_floor_ms(effective[issue["id"]])
        ret_ms=effective.get(r["id"],long(r["date_ms"]))
        if minute_floor_ms(ret_ms)>issue_min:
            continue
        used[r["issue_id"]]=used.get(r["issue_id"],0)+1
        new_ms=issue_min+used[r["issue_id"]]*60000
        if new_ms!=ret_ms:
            shifts.append({"row":r,"new_ms":new_ms,"day":day_bucket(r),"step":"RAI%s" % used[r["issue_id"]]})
            effective[r["id"]]=new_ms
    return shifts

def plan_chrono_shifts(rows):
    matrec=plan_matrectrans_refid_day_shifts(rows)
    same=plan_same_day_shifts(rows,matrec)
    return matrec+same+plan_return_after_issue_shifts(rows,matrec+same)

def plan_same_second_shifts(rows):
    return plan_chrono_shifts(rows)

def sql_update_timestamp(user,table,pk_field,pk_value,field,new_ms):
    from psdi.server import MXServer
    from java.sql import Timestamp
    db=MXServer.getMXServer().getDBManager()
    key=user.getConnectionKey()
    con=ps=None
    try:
        con=db.getConnection(key)
        ps=con.prepareStatement("UPDATE %s SET %s=? WHERE %s=?" % (table,field,pk_field))
        ps.setTimestamp(1,Timestamp(long(new_ms)))
        ps.setLong(2,long(pk_value))
        n=ps.executeUpdate()
        if n!=1:
            raise ValueError("UPDATE %s.%s %s=%s: %s randuri" % (table,field,pk_field,pk_value,n))
        con.commit()
    except Exception:
        if con is not None:
            try: con.rollback()
            except Exception: pass
        raise
    finally:
        if ps is not None:
            try: ps.close()
            except Exception: pass
        if con is not None:
            db.freeConnection(key)

def sql_update_cxcurbal(user,cxid,value):
    from psdi.server import MXServer
    db=MXServer.getMXServer().getDBManager()
    key=user.getConnectionKey()
    con=ps=None
    try:
        con=db.getConnection(key)
        ps=con.prepareStatement("UPDATE CXSTOCURI SET CXCURBAL=? WHERE CXSTOCURIID=?")
        ps.setBigDecimal(1,value.value)
        ps.setLong(2,long(cxid))
        n=ps.executeUpdate()
        if n!=1:
            raise ValueError("UPDATE CXCURBAL CXSTOCURIID=%s: %s randuri" % (cxid,n))
        con.commit()
    except Exception:
        if con is not None:
            try: con.rollback()
            except Exception: pass
        raise
    finally:
        if ps is not None:
            try: ps.close()
            except Exception: pass
        if con is not None:
            db.freeConnection(key)

def running_cxcurbal(rows):
    # Sold pe partitie UNITCOST, ordine data/ref/id (dupa noile date).
    partitions={}
    for r in rows:
        cost=r.get("cost")
        if cost is None:
            raise ValueError("UNITCOST lipsa pe CXSTOCURIID=%s" % r["id"])
        partitions.setdefault(price_label(cost),[]).append(r)
    expected={}
    for key,group in partitions.items():
        ordered=sorted(group,key=lambda r:(r.get("date") or "",r.get("ref_id") or 0,r["id"]))
        running=ZERO
        initial_seen=False
        movement_seen=False
        for r in ordered:
            if r.get("kind")=="INITIAL":
                if initial_seen or movement_seen or r.get("balance") is None:
                    raise ValueError("INITIAL ambiguu/fara CXCURBAL pe CXSTOCURIID=%s" % r["id"])
                running=r["balance"]
                initial_seen=True
            else:
                if r.get("qty") is None:
                    raise ValueError("CXQTY lipsa pe CXSTOCURIID=%s" % r["id"])
                running=running+r["qty"]
                movement_seen=True
            expected[r["id"]]=running
    return expected

def apply_same_day_reorder(inventory,rows,script_service):
    # SQL: CXDOCUMENTDATE + ACTUALDATE; MATRECTRANS pe CXREFID; RETURN dupa ISSUE; CXCURBAL.
    # Oprit: nu rearanjeaza tranzactii/solduri din Check FIFO.
    if not CHRONO_REORDER_ENABLED:
        msg="REORDONARE CRONO: dezactivata (CHRONO_REORDER_ENABLED=False)"
        script_service.log_info("CXINVAUDIT "+msg)
        return msg
    from java.text import SimpleDateFormat
    from java.util import TimeZone,Date
    shifts=plan_chrono_shifts(rows)
    if not shifts:
        return "REORDONARE CRONO: nicio mutare MATRECTRANS-CXREFID / ISSUE / RETURN"
    user=inventory.getUserInfo()
    fmt=SimpleDateFormat("yyyy-MM-dd HH:mm:ss")
    fmt.setTimeZone(TimeZone.getTimeZone("UTC"))
    for item in shifts:
        r=item["row"]
        new_ms=item["new_ms"]
        sql_update_timestamp(user,"CXSTOCURI","CXSTOCURIID",r["id"],"CXDOCUMENTDATE",new_ms)
        ref_mbo=normalize_ref_mbo(r.get("ref_mbo"))
        ref_id=r.get("ref_id")
        if ref_mbo=="MATUSETRANS" and ref_id is not None:
            sql_update_timestamp(user,"MATUSETRANS","MATUSETRANSID",ref_id,"ACTUALDATE",new_ms)
        elif ref_mbo=="MATRECTRANS" and ref_id is not None:
            sql_update_timestamp(user,"MATRECTRANS","MATRECTRANSID",ref_id,"ACTUALDATE",new_ms)
        r["date_ms"]=new_ms
        r["date"]=fmt.format(Date(long(new_ms)))+".000000000"
    expected=running_cxcurbal(rows)
    bal_changed=0
    for r in rows:
        new_bal=expected[r["id"]]
        old_bal=r.get("balance")
        if old_bal is None or far(old_bal,new_bal,QTY_TOLERANCE):
            sql_update_cxcurbal(user,r["id"],new_bal)
            r["balance"]=new_bal
            bal_changed+=1
    n_mat=sum(1 for s in shifts if str(s.get("step")).startswith("MR"))
    n_ret=sum(1 for s in shifts if s["row"].get("kind")=="RETURN")
    n_issue=len(shifts)-n_mat-n_ret
    msg="\n".join([
        "REORDONARE CRONO",
        "  MATRECTRANS CXREFID: %s | ISSUE dupa intrari: %s | RETURN dupa ISSUE: %s" % (
            n_mat,n_issue,n_ret),
        "  CXCURBAL rescrise: %s" % bal_changed,
    ])
    for item in shifts[:MAX_LAYER_LINES]:
        r=item["row"]
        msg+="\n  CXSTOCURIID=%s %s RefID=%s -> step %s" % (
            r["id"],r.get("kind"),r.get("ref_id"),item["step"])
    if len(shifts)>MAX_LAYER_LINES:
        msg+="\n  ... +%s mutari in log" % (len(shifts)-MAX_LAYER_LINES)
    script_service.log_info("CXINVAUDIT "+msg.replace("\n"," | "))
    return msg

def apply_same_second_reorder(inventory,rows,script_service):
    return apply_same_day_reorder(inventory,rows,script_service)

def check_same_day_plan():
    # ISSUE MATUSETRANS + RECEIPT same-second: doar ISSUE mutate (nu MATRECTRANS exit).
    rows=[
        {"id":1,"kind":"ISSUE","qty":ExactNumber("-10"),"ref_mbo":"MATUSETRANS","ref_id":10,
         "date":"2026-07-17 00:00:00.000000000","date_ms":1000,"cost":ExactNumber("6.3"),"balance":ExactNumber("-10")},
        {"id":2,"kind":"ISSUE","qty":ExactNumber("-30"),"ref_mbo":"MATUSETRANS","ref_id":11,
         "date":"2026-07-17 00:00:00.100000000","date_ms":1100,"cost":ExactNumber("6.3"),"balance":ExactNumber("-40")},
        {"id":3,"kind":"RECEIPT","qty":ExactNumber("50"),"ref_mbo":"MATRECTRANS","ref_id":20,
         "date":"2026-07-17 00:00:00.200000000","date_ms":1200,"cost":ExactNumber("6.3"),"balance":ExactNumber("10")},
    ]
    shifts=plan_same_day_shifts(rows)
    if len(shifts)!=2:
        raise ValueError("self-check: same-day ISSUE trebuie 2 mutari")
    base=1200
    if [s["new_ms"] for s in shifts]!=[base+60000,base+120000]:
        raise ValueError("self-check: same-day esalonare +1/+2 min")
    by=dict((s["row"]["id"],s["new_ms"]) for s in shifts)
    for r in rows:
        if r["id"] in by:
            r["date_ms"]=by[r["id"]]
            r["date"]="2026-07-17 00:%02d:00.000000000" % ((by[r["id"]]-base)//60000)
    exp=running_cxcurbal(rows)
    if far(exp[3],ExactNumber("50"),QTY_TOLERANCE) or far(exp[1],ExactNumber("40"),QTY_TOLERANCE):
        raise ValueError("self-check: CXCURBAL dupa same-day (receipt/issue1)")
    if far(exp[2],ExactNumber("10"),QTY_TOLERANCE):
        raise ValueError("self-check: CXCURBAL dupa same-day (issue2)")
    # Pic: SHIPRETURN inaintea SHIPTRANSFER pe aceeasi zi, dar CXREFID transfer < return.
    t0=10*3600*1000+2*60000
    pic=[
        {"id":1,"kind":"SHIPRETURN","qty":ExactNumber("7"),"ref_mbo":"MATRECTRANS","ref_id":1337429224,
         "date":"2026-03-10 00:02:00.000000000","date_ms":t0,"cost":ExactNumber("86"),"balance":ExactNumber("217")},
        {"id":2,"kind":"SHIPTRANSFER","qty":ExactNumber("-7"),"ref_mbo":"MATRECTRANS","ref_id":1337391126,
         "date":"2026-03-10 00:03:00.000000000","date_ms":t0+60000,"cost":ExactNumber("86"),"balance":ExactNumber("210")},
    ]
    mr=plan_matrectrans_refid_day_shifts(pic)
    if len(mr)!=2:
        raise ValueError("self-check: MATRECTRANS CXREFID trebuie sa mute transfer+return")
    by_mr=dict((s["row"]["id"],s["new_ms"]) for s in mr)
    if by_mr[2]>=by_mr[1]:
        raise ValueError("self-check: SHIPTRANSFER (CXREFID mic) trebuie inaintea SHIPRETURN")
    if plan_matrectrans_refid_day_shifts([
        {"id":1,"kind":"SHIPTRANSFER","qty":ExactNumber("-7"),"ref_mbo":"MATRECTRANS","ref_id":100,
         "date":"2026-03-10 00:02:00.000000000","date_ms":t0,"cost":ExactNumber("86")},
        {"id":2,"kind":"SHIPRETURN","qty":ExactNumber("7"),"ref_mbo":"MATRECTRANS","ref_id":200,
         "date":"2026-03-10 00:03:00.000000000","date_ms":t0+60000,"cost":ExactNumber("86")},
    ]):
        raise ValueError("self-check: MATRECTRANS deja pe CXREFID nu trebuie mutat")
    # Iesiri dimineata, receptii seara (cazul BADFIFO fara stoc anterior).
    morning=8*3600*1000
    evening=18*3600*1000
    day_rows=[]
    for i in range(1,5):
        day_rows.append({"id":i,"kind":"ISSUE","qty":ExactNumber("-1"),"ref_mbo":"MATUSETRANS","ref_id":100+i,
            "date":"2026-01-19 09:09:00.000000000","date_ms":morning+i,"cost":ExactNumber("446"),
            "balance":ExactNumber("-%s" % i)})
    day_rows.append({"id":10,"kind":"RECEIPT","qty":ExactNumber("8"),"ref_mbo":"MATRECTRANS","ref_id":200,
        "date":"2026-01-19 18:39:00.000000000","date_ms":evening,"cost":ExactNumber("446"),"balance":ExactNumber("4")})
    day_rows.append({"id":11,"kind":"RECEIPT","qty":ExactNumber("8"),"ref_mbo":"MATRECTRANS","ref_id":201,
        "date":"2026-01-19 18:48:00.000000000","date_ms":evening+9*60000,"cost":ExactNumber("133.8"),
        "balance":ExactNumber("8")})
    day_shifts=plan_same_day_shifts(day_rows)
    if len(day_shifts)!=4:
        raise ValueError("self-check: same-day dimineata->seara trebuie 4 ISSUE mutate")
    base2=evening+9*60000
    if day_shifts[0]["new_ms"]!=base2+60000 or day_shifts[3]["new_ms"]!=base2+4*60000:
        raise ValueError("self-check: same-day ancora pe max(receptii)")
    # Iesire deja dupa receptii: nu se muta.
    late=[{"id":1,"kind":"RECEIPT","qty":ExactNumber("5"),"ref_mbo":"MATRECTRANS","ref_id":1,
           "date":"2026-01-20 10:00:00.000000000","date_ms":100000,"cost":ExactNumber("1"),"balance":ExactNumber("5")},
          {"id":2,"kind":"ISSUE","qty":ExactNumber("-1"),"ref_mbo":"MATUSETRANS","ref_id":2,
           "date":"2026-01-20 11:00:00.000000000","date_ms":100000+3600000,"cost":ExactNumber("1"),
           "balance":ExactNumber("4")}]
    if plan_same_day_shifts(late):
        raise ValueError("self-check: iesirea de dupa receptii nu trebuie mutata")
    # RETURN dupa ISSUE la zi/ora/min: nu ancora; urmeaza ISSUE daca e mutat / prea devreme.
    pair=[
        {"id":1,"kind":"ISSUE","qty":ExactNumber("-1790"),"ref_mbo":"MATUSETRANS","ref_id":50,
         "date":"2026-02-06 15:12:00.000000000","date_ms":1000,"cost":ExactNumber("24")},
        {"id":2,"kind":"RETURN","qty":ExactNumber("1790"),"ref_mbo":"MATUSETRANS","ref_id":51,
         "issue_id":50,"date":"2026-02-06 15:13:00.000000000","date_ms":1000+60000,"cost":ExactNumber("24")},
    ]
    if plan_chrono_shifts(pair):
        raise ValueError("self-check: ISSUE+RETURN deja OK nu trebuie mutat")
    early_ret=[
        {"id":1,"kind":"ISSUE","qty":ExactNumber("-1"),"ref_mbo":"MATUSETRANS","ref_id":50,
         "date":"2026-02-06 15:12:00.000000000","date_ms":15*3600*1000+12*60000,"cost":ExactNumber("24")},
        {"id":2,"kind":"RETURN","qty":ExactNumber("1"),"ref_mbo":"MATUSETRANS","ref_id":51,
         "issue_id":50,"date":"2026-02-06 15:12:00.000000000","date_ms":15*3600*1000+12*60000,"cost":ExactNumber("24")},
    ]
    er=plan_return_after_issue_shifts(early_ret)
    if len(er)!=1 or minute_floor_ms(er[0]["new_ms"])<=minute_floor_ms(early_ret[0]["date_ms"]):
        raise ValueError("self-check: RETURN pe acelasi minut ca ISSUE trebuie +1 min")
    pair2=list(pair)+[
        {"id":3,"kind":"RECEIPT","qty":ExactNumber("10"),"ref_mbo":"MATRECTRANS","ref_id":90,
         "date":"2026-02-06 18:00:00.000000000","date_ms":1000+3*3600000,"cost":ExactNumber("24")},
    ]
    p2=plan_chrono_shifts(pair2)
    issue_s=[s for s in p2 if s["row"]["id"]==1]
    ret_s=[s for s in p2 if s["row"]["id"]==2]
    if len(issue_s)!=1 or len(ret_s)!=1:
        raise ValueError("self-check: ISSUE+RETURN cu receptie trebuie mutate ambele")
    if minute_floor_ms(ret_s[0]["new_ms"])<=minute_floor_ms(issue_s[0]["new_ms"]):
        raise ValueError("self-check: RETURN trebuie dupa minutul ISSUE")

def check_same_second_plan():
    check_same_day_plan()

def _audit_self_row(ident, date, ref, kind, qty, cost, balance, mbo="MATRECTRANS"):
    return {"id":ident,"group":"G","date":date,"ref_id":ref,"ref_mbo":mbo,
            "kind":kind,"qty":ExactNumber(qty),"cost":ExactNumber(cost),"balance":ExactNumber(balance)}

def check_layer_fifo_basics():
    audit=audit_rows([
        _audit_self_row(1,"2026-06-01 00:00:00.000000000",300,"SHIPTRANSFER","-10","9.098","-10"),
        _audit_self_row(2,"2026-06-08 00:00:00.000000000",100,"SHIPRECEIPT","10","9.098","0"),
        _audit_self_row(3,"2026-09-07 00:00:00.000000000",400,"SHIPRECEIPT","20","9.846","20"),
        _audit_self_row(4,"2026-09-10 00:00:00.000000000",500,"SHIPTRANSFER","-1","9.098","-1"),
    ])
    rec=audit["records"][4]
    if rec["status"]!="BAD" or far(rec["expected"],ExactNumber("9.846"),COST_TOLERANCE):
        raise ValueError("self-check: iesirea nu consuma stratul anterior")
    if not rec["allocations"] or rec["allocations"][0].get("source_ref_id")!=400:
        raise ValueError("self-check: sursa nu este intrarea anterioara")
    blocked=audit_rows([
        _audit_self_row(1,"2026-06-01 00:00:00.000000000",1,"SHIPTRANSFER","-1","9","-1"),
        _audit_self_row(2,"2026-06-02 00:00:00.000000000",2,"SHIPTRANSFER","-1","9","-2"),
    ])
    if blocked["records"][2]["status"]!="UNVERIFIED":
        raise ValueError("self-check: iesirea fara stoc nu trebuie certificata")
    bad_complete,bad_reason=journal_fifo_complete(blocked)
    if bad_complete:
        raise ValueError("self-check: jurnalul insuficient nu trebuie sa autorizeze CURBAL")
    cross=audit_rows([
        dict(_audit_self_row(1,"2026-08-07 00:00:00.000000000",1337476211,"SHIPRECEIPT","1","1","1"),group="A"),
        dict(_audit_self_row(2,"2026-09-25 00:00:00.000000000",1337483496,"SHIPTRANSFER","-1","1","-1"),group="B"),
    ])
    if cross["records"][2]["status"]!="OK":
        raise ValueError("self-check: SHIPTRANSFER trebuie sa consume SHIPRECEIPT indiferent de COMMODITYGROUP")
    if not cross["records"][2]["allocations"] or cross["records"][2]["allocations"][0].get("source_ref_id")!=1337476211:
        raise ValueError("self-check: sursa SHIPTRANSFER trebuie sa fie SHIPRECEIPT")

def check_layer_void_ship():
    voided=audit_rows([
        _audit_self_row(1,"2026-09-07 00:00:00.000000000",10,"RECEIPT","50319","9.846","50319"),
        _audit_self_row(2,"2026-09-11 00:00:00.000000000",20,"RECEIPT","172","9.846","50491"),
        _audit_self_row(3,"2026-09-11 00:00:00.000000000",30,"VOIDRECEIPT","-172","9.846","50319"),
        _audit_self_row(4,"2026-09-12 00:00:00.000000000",40,"ISSUE","-542","9.846","49777","MATUSETRANS"),
    ])
    if voided["records"][3]["status"]!="OK":
        raise ValueError("self-check: VOIDRECEIPT trebuie sa fie OK")
    if not voided["records"][3]["allocations"] or voided["records"][3]["allocations"][0].get("source_ref_id")!=20:
        raise ValueError("self-check: VOIDRECEIPT trebuie sa anuleze receptia recenta")
    if voided["records"][4]["status"]!="OK":
        raise ValueError("self-check: ISSUE dupa VOIDRECEIPT trebuie verificat")
    layers=voided.get("layers") or []
    if len(layers)!=1 or far(layers[0]["qty"],ExactNumber("49777"),QTY_TOLERANCE):
        raise ValueError("self-check: stratul ramas dupa VOIDRECEIPT/ISSUE e gresit")
    if far(layers[0]["cost"],ExactNumber("9.846"),COST_TOLERANCE) or layers[0].get("source_ref_id")!=10:
        raise ValueError("self-check: provenienta stratului ramas e gresita")
    if layers[0].get("source_ref_mbo")!="MATRECTRANS":
        raise ValueError("self-check: CXREFMBO stratului ramas lipseste")
    ok_complete,ok_reason=journal_fifo_complete(voided)
    if not ok_complete:
        raise ValueError("self-check: jurnalul VOIDRECEIPT trebuia considerat complet OK: "+ok_reason)
    sold_rec=voided["records"][4]
    sold_rec["balance_bad"]=True
    if flag(sold_rec)!="Y":
        raise ValueError("self-check: sold gresit trebuie BADFIFO=Y")
    sold_rec["balance_bad"]=False
    if flag(sold_rec)!="N":
        raise ValueError("self-check: ISSUE OK fara sold gresit trebuie BADFIFO=N")
    sold_rec["row"]=dict(sold_rec["row"])
    sold_rec["row"]["balance"]=ExactNumber("-40")
    if flag(sold_rec)!="Y":
        raise ValueError("self-check: sold negativ trebuie BADFIFO=Y chiar daca pretul e OK")

def check_return_before_issue():
    # RETURN inaintea ISSUE legat: pret+cantitate aliniate => OK + put_back (nu blocheaza U).
    rows=[
        _audit_self_row(1,"2026-03-01 00:00:00.000000000",10,"SHIPRECEIPT","3","10.950","3"),
        dict(_audit_self_row(2,"2026-03-31 00:27:00.000000000",164580,"RETURN","32","10.950","35","MATUSETRANS"),
             issue_id=163459),
        _audit_self_row(3,"2026-03-31 00:28:00.000000000",163459,"ISSUE","-32","10.950","3","MATUSETRANS"),
        _audit_self_row(4,"2026-04-12 00:00:00.000000000",200,"ISSUE","-1","10.950","2","MATUSETRANS"),
    ]
    audit=audit_rows(rows)
    ret,iss,later=audit["records"][2],audit["records"][3],audit["records"][4]
    if ret["status"]!="OK" or not ret.get("return_before_issue"):
        raise ValueError("self-check: RETURN inaintea ISSUE trebuie OK (before_issue)")
    if flag(ret)!="N":
        raise ValueError("self-check: RETURN inaintea ISSUE trebuie BADFIFO=N")
    if ret.get("link_ref")!=163459:
        raise ValueError("self-check: RETURN trebuie legat de ISSUE 163459")
    if iss["status"]!="OK" or flag(iss)!="N":
        raise ValueError("self-check: ISSUE dupa RETURN aliniat trebuie OK/N")
    if later["status"]!="OK" or flag(later)!="N":
        raise ValueError("self-check: ISSUE ulterior nu trebuie blocat de U")
    bad=audit_rows([
        _audit_self_row(1,"2026-03-01 00:00:00.000000000",10,"SHIPRECEIPT","3","10.950","3"),
        dict(_audit_self_row(2,"2026-03-31 00:27:00.000000000",164580,"RETURN","32","10.950","35","MATUSETRANS"),
             issue_id=163459),
        _audit_self_row(3,"2026-03-31 00:28:00.000000000",163459,"ISSUE","-30","10.950","5","MATUSETRANS"),
    ])
    if bad["records"][2]["status"]!="UNVERIFIED":
        raise ValueError("self-check: RETURN inaintea ISSUE cu qty nealiniata trebuie U")

def check_layer_shipreturn_cancel():
    check_return_before_issue()
    shipret=audit_rows([
        _audit_self_row(1,"2026-01-13 00:00:00.000000000",11,"SHIPRECEIPT","400","0.440","400"),
        _audit_self_row(2,"2026-01-13 10:42:00.000000000",12,"ISSUE","-400","0.440","0","MATUSETRANS"),
        _audit_self_row(3,"2026-03-10 10:43:00.000000000",21,"SHIPRECEIPT","500","0.440","500"),
        _audit_self_row(4,"2026-03-10 11:04:00.000000000",22,"SHIPRECEIPT","500","0.440","1000"),
        _audit_self_row(5,"2026-03-10 14:42:00.000000000",31,"SHIPRETURN","-500","0.440","500"),
        _audit_self_row(6,"2026-03-10 14:43:00.000000000",41,"ISSUE","-500","0.440","0","MATUSETRANS"),
    ])
    if shipret["records"][5]["status"]!="OK":
        raise ValueError("self-check: SHIPRETURN trebuie sa fie OK")
    if not shipret["records"][5]["allocations"] or shipret["records"][5]["allocations"][0].get("source_ref_id")!=22:
        raise ValueError("self-check: SHIPRETURN trebuie sa anuleze receptia recenta")
    if shipret["records"][6]["status"]!="OK":
        raise ValueError("self-check: ISSUE dupa SHIPRETURN nu trebuie NEVERIFICAT")
    if flag(shipret["records"][5])!="N" or flag(shipret["records"][6])!="N":
        raise ValueError("self-check: SHIPRETURN/ISSUE OK trebuie BADFIFO=N")
    sr_complete,sr_reason=journal_fifo_complete(shipret)
    if not sr_complete:
        raise ValueError("self-check: jurnalul SHIPRETURN trebuia complet OK: "+sr_reason)
    shipret_in=audit_rows([
        _audit_self_row(1,"2026-01-01 00:00:00.000000000",1,"INITIAL","210","86","210"),
        _audit_self_row(2,"2026-03-10 00:00:00.000000000",20,"SHIPTRANSFER","-7","86","203"),
        _audit_self_row(3,"2026-03-10 00:00:00.000000000",30,"SHIPRETURN","7","86","210"),
        _audit_self_row(4,"2026-03-30 00:00:00.000000000",40,"SHIPTRANSFER","-10","86","200"),
    ])
    if shipret_in["records"][3]["status"]!="OK":
        raise ValueError("self-check: SHIPRETURN pozitiv trebuie OK")
    if flag(shipret_in["records"][3])!="N":
        raise ValueError("self-check: SHIPRETURN pozitiv trebuie BADFIFO=N")
    if shipret_in["records"][3].get("link_ref")!=20:
        raise ValueError("self-check: SHIPRETURN pozitiv trebuie legat de SHIPTRANSFER")
    if shipret_in["records"][4]["status"]!="OK" or flag(shipret_in["records"][4])!="N":
        raise ValueError("self-check: SHIPTRANSFER dupa SHIPRETURN pozitiv trebuie OK/N")
    shipcancel=audit_rows([
        _audit_self_row(1,"2026-02-01 00:00:00.000000000",10,"SHIPRECEIPT","500","11.340","500"),
        _audit_self_row(2,"2026-02-02 00:00:00.000000000",20,"SHIPTRANSFER","-54","11.340","446"),
        _audit_self_row(3,"2026-02-02 00:00:00.000000000",21,"SHIPCANCEL","54","11.340","500"),
        _audit_self_row(4,"2026-02-02 00:00:00.000000000",30,"SHIPTRANSFER","-54","11.340","446"),
    ])
    if shipcancel["records"][3]["status"]!="OK":
        raise ValueError("self-check: SHIPCANCEL trebuie sa fie OK")
    if shipcancel["records"][3].get("link_ref")!=20:
        raise ValueError("self-check: SHIPCANCEL trebuie legat de SHIPTRANSFER anterior")
    if flag(shipcancel["records"][3])!="N":
        raise ValueError("self-check: SHIPCANCEL OK trebuie BADFIFO=N")
    if shipcancel["records"][4]["status"]!="OK":
        raise ValueError("self-check: SHIPTRANSFER dupa SHIPCANCEL trebuie verificat")
    sc_complete,sc_reason=journal_fifo_complete(shipcancel)
    if not sc_complete:
        raise ValueError("self-check: jurnalul SHIPCANCEL trebuia complet OK: "+sc_reason)
    neg_receipt=audit_rows([
        _audit_self_row(1,"2026-04-23 00:00:00.000000000",10,"RECEIPT","12","12.000","12"),
        _audit_self_row(2,"2026-04-24 00:51:00.000000000",20,"RECEIPT","-6","12.000","6"),
        _audit_self_row(3,"2026-04-24 00:54:00.000000000",30,"RECEIPT","-2","12.000","4"),
        _audit_self_row(4,"2026-04-24 01:03:00.000000000",40,"RECEIPT","4","12.000","8"),
        _audit_self_row(5,"2026-04-24 01:04:00.000000000",45,"RECEIPT","10","12.000","18"),
        _audit_self_row(6,"2026-04-24 01:05:00.000000000",46,"RECEIPT","-2","12.000","16"),
        _audit_self_row(7,"2026-04-24 01:06:00.000000000",47,"RECEIPT","-6","12.000","10"),
        _audit_self_row(8,"2026-04-25 00:04:00.000000000",50,"SHIPTRANSFER","-2","12.000","8"),
    ])
    for rid in (2,3,6,7,8):
        rec=neg_receipt["records"][rid]
        if rec["status"]!="OK":
            raise ValueError("self-check: RECEIPT/SHIPTRANSFER negativ trebuie OK, got %s (%s)" % (
                rec["status"],rec.get("reason")))
        if flag(rec)!="N":
            raise ValueError("self-check: iesire negativa OK trebuie BADFIFO=N, got %s (sold_bad=%s/%s)" % (
                flag(rec),rec.get("balance_bad"),rec.get("balance_expected")))
    if "neimplementat" in (neg_receipt["records"][2].get("reason") or ""):
        raise ValueError("self-check: RECEIPT negativ nu trebuie tip neimplementat")


def check_layer_invlifo_plans():
    desired=[
        {"cost":ExactNumber("18.990"),"qty":ExactNumber("634"),"ref_mbo":"MATRECTRANS","ref_id":1337445295},
        {"cost":ExactNumber("15.700"),"qty":ExactNumber("360"),"ref_mbo":"MATRECTRANS","ref_id":1337445303},
        {"cost":ExactNumber("17.500"),"qty":ExactNumber("570"),"ref_mbo":None,"ref_id":None},
    ]
    current=[
        {"id":1,"cost":ExactNumber("18.990"),"qty":ExactNumber("634"),"ref_mbo":"MATRECTRANS","ref_id":1337445295},
        {"id":2,"cost":ExactNumber("18.990"),"qty":ExactNumber("634"),"ref_mbo":"MATRECTRANS","ref_id":1337445295},
        {"id":3,"cost":ExactNumber("15.700"),"qty":ExactNumber("360"),"ref_mbo":"MATRECTRANS","ref_id":1337445303},
        {"id":4,"cost":ExactNumber("15.700"),"qty":ExactNumber("360"),"ref_mbo":"MATRECTRANS","ref_id":1337445303},
        {"id":5,"cost":ExactNumber("17.500"),"qty":ExactNumber("570"),"ref_mbo":None,"ref_id":None},
        {"id":6,"cost":ExactNumber("12.640"),"qty":ExactNumber("100"),"ref_mbo":None,"ref_id":None},
    ]
    keeps,updates,deletes,creates=plan_invlifo_alignment(desired,current)
    if updates or creates or len(keeps)!=3 or sorted(r["id"] for r in deletes)!=[2,4,6]:
        raise ValueError("self-check: alinierea INVLIFOFIFOCOST nu elimina duplicatele corect")
    missing_plan=plan_invlifo_alignment(
        desired+[{"cost":ExactNumber("99.000"),"qty":ExactNumber("1"),"ref_mbo":None,"ref_id":None}],
        [row for row in current if row["id"] in (1,3,5)])
    if len(missing_plan[3])!=1 or missing_plan[3][0]["cost"]!=ExactNumber("99.000"):
        raise ValueError("self-check: lipsa INVLIFOFIFOCOST trebuie semnalata fara create")
    rot_units=expand_rotating_desired([
        {"cost":ExactNumber("67.800"),"qty":ExactNumber("2"),"ref_mbo":"MATRECTRANS","ref_id":100,
         "date":"2026-10-06 00:00:00.000000000","source":1,"priority":("G",1,0),"initial":False},
        {"cost":ExactNumber("67.800"),"qty":ONE,"ref_mbo":"MATRECTRANS","ref_id":101,
         "date":"2026-10-06 00:00:00.000000000","source":2,"priority":("G",2,0),"initial":False}])
    if [u["ref_id"] for u in rot_units]!=[100,100,101] or any(far(u["qty"],ONE,QTY_TOLERANCE) for u in rot_units):
        raise ValueError("self-check: ROTATING expand qty=1 / REFOBJECTID")
    rot_cur=[{"id":1,"cost":ExactNumber("67.800"),"qty":ExactNumber("77"),"ref_mbo":"MATRECTRANS","ref_id":100},
             {"id":2,"cost":ExactNumber("10.000"),"qty":ONE,"ref_mbo":"MATRECTRANS","ref_id":999}]
    rk,ru,rd,rc=plan_rotating_invlifo(rot_units,rot_cur)
    if rk or rd or len(ru)!=2 or len(rc)!=1 or rc[0]["ref_id"]!=101 or sorted(u["row"]["id"] for u in ru)!=[1,2]:
        raise ValueError("self-check: ROTATING update/reuse/insert")
    rk2,ru2,rd2,rc2=plan_rotating_invlifo(
        [{"cost":ExactNumber("67.800"),"qty":ONE,"ref_mbo":"MATRECTRANS","ref_id":100}],
        rot_cur+[{"id":3,"cost":ONE,"qty":ONE,"ref_mbo":"MATRECTRANS","ref_id":888}])
    if rc2 or sorted(r["id"] for r in rd2)!=[2,3] or len(ru2)!=1 or ru2[0]["row"]["id"]!=1:
        raise ValueError("self-check: ROTATING delete surplus")
    reuse_desired=[{"cost":ExactNumber("14.590"),"qty":ExactNumber("1"),
                    "ref_mbo":"MATRECTRANS","ref_id":1337422726}]
    reuse_current=[
        {"id":10,"cost":ExactNumber("14.590"),"qty":ExactNumber("4"),"ref_mbo":None,"ref_id":None},
        {"id":11,"cost":ExactNumber("10.000"),"qty":ExactNumber("1"),"ref_mbo":"MATRECTRANS","ref_id":999},
    ]
    r_keeps,r_updates,r_deletes,r_creates=plan_invlifo_alignment(reuse_desired,reuse_current)
    if r_keeps or r_creates or len(r_updates)!=1 or not r_updates[0].get("reuse"):
        raise ValueError("self-check: surplusul trebuia reutilizat, nu sters+create")
    if r_updates[0]["row"]["id"]!=10 or [r["id"] for r in r_deletes]!=[11]:
        raise ValueError("self-check: reutilizare/stergere surplus gresita")
    same_price=[
        {"cost":ExactNumber("200.000"),"qty":ExactNumber("3000"),"ref_mbo":"MATRECTRANS","ref_id":1337451940,
         "priority":("G",1,0),"source":1,"date":"2026-07-07 00:00:00.000000000","initial":False},
        {"cost":ExactNumber("261.900"),"qty":ExactNumber("1000"),"ref_mbo":"MATRECTRANS","ref_id":1337451934,
         "priority":("G",2,0),"source":2,"date":"2026-07-07 00:01:00.000000000","initial":False},
        {"cost":ExactNumber("261.900"),"qty":ExactNumber("1000"),"ref_mbo":"MATRECTRANS","ref_id":1337471973,
         "priority":("G",3,0),"source":3,"date":"2026-08-27 00:00:00.000000000","initial":False},
    ]
    collapsed=collapse_invlifo_desired(same_price)
    if len(collapsed)!=2:
        raise ValueError("self-check: acelasi pret trebuie un strat INVLIFO")
    by_cost=dict((price_label(layer["cost"]),layer) for layer in collapsed)
    if price_label(ExactNumber("200.000")) not in by_cost or price_label(ExactNumber("261.900")) not in by_cost:
        raise ValueError("self-check: preturi dupa colaps gresite")
    if by_cost[price_label(ExactNumber("261.900"))]["qty"]!=ExactNumber("2000"):
        raise ValueError("self-check: suma pe pret gresita")
    if by_cost[price_label(ExactNumber("261.900"))]["ref_id"]!=1337451934:
        raise ValueError("self-check: trebuie cel mai vechi MATRECTRANSID")
    rot_pairs=[("99628",1337345444,ExactNumber("4.600"),"2026-07-05 15:30:52"),
               ("99705",1337345521,ExactNumber("4.700"),"2026-07-05 15:31:16")]
    rot_asset_layers=rotating_layers_from_pairs(rot_pairs)
    if [layer["ref_id"] for layer in rot_asset_layers]!=[1337345444,1337345521]:
        raise ValueError("self-check: ROTATING trebuie un MATRECTRANSID per activ")
    if far(rot_asset_layers[1]["cost"],ExactNumber("4.700"),COST_TOLERANCE):
        raise ValueError("self-check: ROTATING pastreaza costul intrarii, nu il comaseaza")
    try:
        rotating_layers_from_pairs([("99628",None,ExactNumber("4.600"),"2026-07-05 15:30:52")])
        raise ValueError("self-check: activ fara intrare trebuia blocat")
    except ValueError as exc:
        if "fara MATRECTRANS" not in txt(exc):
            raise
    inv_current=[
        {"id":21,"cost":ExactNumber("261.900"),"qty":ExactNumber("1000"),"ref_mbo":"MATRECTRANS","ref_id":1337451934},
        {"id":22,"cost":ExactNumber("200.000"),"qty":ExactNumber("3000"),"ref_mbo":"MATRECTRANS","ref_id":1337451940},
    ]
    c_keeps,c_updates,c_deletes,c_creates=plan_invlifo_alignment(collapsed,inv_current)
    if c_creates or c_deletes or len(c_keeps)!=1 or len(c_updates)!=1:
        raise ValueError("self-check: colaps pe pret trebuia update fara create")
    if c_updates[0]["layer"]["qty"]!=ExactNumber("2000") or c_updates[0]["row"]["id"]!=21:
        raise ValueError("self-check: update INVLIFO pe pret gresit")
def check_layer_beats_negative_balance():
    check_same_second_plan()
    check_layer_fifo_basics()
    check_layer_void_ship()
    check_layer_shipreturn_cancel()
    check_layer_invlifo_plans()


def split_gap_by_matusetrans(inventory, rows, script_service):
    from psdi.mbo import SqlFormat
    try:
        have=set()
        for r in rows:
            if r.get("ref_mbo")=="MATUSETRANS" and r.get("ref_id") is not None:
                have.add(r["ref_id"])
        condition=SqlFormat("ITEMNUM=:1 AND SITEID=:2 AND FROMSTORELOC=:3")
        condition.setObject(1,"INVUSELINE","ITEMNUM",inventory.getString("ITEMNUM"))
        condition.setObject(2,"INVUSELINE","SITEID",inventory.getString("SITEID"))
        condition.setObject(3,"INVUSELINE","FROMSTORELOC",inventory.getString("LOCATION"))
        line_rows=fetch_rows(inventory,"INVUSELINE",condition.format(),(("INVUSELINEID","L"),))
        line_ids=[r["INVUSELINEID"] for r in line_rows if r.get("INVUSELINEID") is not None]
        splits=[]
        for chunk in in_chunks(line_ids):
            where="INVUSELINEID IN (%s)" % ",".join(txt(i) for i in chunk)
            splits.extend(fetch_rows(inventory,"INVUSELINESPLIT",where,(
                ("INVUSELINESPLITID","L"),("INVUSELINEID","L"))))
        split_to_line={}
        for s in splits:
            if s.get("INVUSELINESPLITID") is not None:
                split_to_line[s["INVUSELINESPLITID"]]=s.get("INVUSELINEID")
        mts=[]
        for chunk in in_chunks(list(split_to_line.keys())):
            where="INVUSELINESPLITID IN (%s)" % ",".join(txt(i) for i in chunk)
            mts.extend(fetch_rows(inventory,"MATUSETRANS",where,(
                ("MATUSETRANSID","L"),("INVUSELINESPLITID","L"))))
        by_split={}
        for m in mts:
            by_split.setdefault(m.get("INVUSELINESPLITID"),[]).append(m)
        miss_mt={}
        for s in splits:
            if not by_split.get(s.get("INVUSELINESPLITID")):
                miss_mt.setdefault(s.get("INVUSELINEID"),[]).append(s.get("INVUSELINESPLITID"))
        miss_cx={}
        for m in mts:
            if m.get("MATUSETRANSID") not in have:
                line=split_to_line.get(m.get("INVUSELINESPLITID"))
                miss_cx.setdefault(line,[]).append(m.get("MATUSETRANSID"))
        notes={}
        for line in set(list(miss_mt.keys())+list(miss_cx.keys())):
            parts=[]
            ids=miss_mt.get(line) or []
            if ids:
                parts.append("fara MATUSETRANS "+",".join(txt(i) for i in ids[:12]))
            ids=miss_cx.get(line) or []
            if ids:
                parts.append("fara CXSTOCURI "+",".join(txt(i) for i in ids[:12]))
            note="SPLIT LIPSA: "+", ".join(parts)
            for m in mts:
                if split_to_line.get(m.get("INVUSELINESPLITID"))==line and m.get("MATUSETRANSID") in have:
                    notes[m["MATUSETRANSID"]]=note
        script_service.log_info("CXINVAUDIT split lipsa pe %s linii, notate %s randuri" % (
            len(set(list(miss_mt.keys())+list(miss_cx.keys()))),len(notes)))
        return notes
    except Exception as exc:
        script_service.log_info("CXINVAUDIT split lipsa indisponibil: "+txt(exc))
        return {}

def run_local(inventory,script_service):
    from psdi.mbo import MboConstants
    check_layer_beats_negative_balance()
    if inventory is None or inventory.getName()!="INVENTORY":
        raise ValueError("Ruleaza Check FIFO din INVENTORY")
    for f in ("ITEMNUM","SITEID","LOCATION"):
        if inventory.isNull(f):
            raise ValueError("Lipseste "+f)
    if inventory.toBeAdded() or inventory.isModified():
        raise ValueError("Salveaza/renunta la modificarile Inventory inainte de audit")
    bean=fifo_table(inventory,script_service)
    root,verify=None,None
    try:
        root=open_scope(inventory,"CXSTOCURI")
        rows,mbos=read_journal(root)
        if not rows:
            raise ValueError("Nu exista randuri CXSTOCURI")
        # ISSUEID pe RETURN inainte de same-day (returul ramane dupa ISSUE).
        enrich_returns(inventory,rows,script_service)
        reorder_msg=apply_same_day_reorder(inventory,rows,script_service)
        if "CXCURBAL rescrise:" in reorder_msg or "RETURN dupa ISSUE:" in reorder_msg:
            close_set(root)
            root=open_scope(inventory,"CXSTOCURI")
            rows,mbos=read_journal(root)
            if not rows:
                raise ValueError("Nu exista randuri CXSTOCURI dupa same-day")
            enrich_returns(inventory,rows,script_service)
        original=snapshot(rows)
        unknown=enrich_origins(inventory,rows,script_service)
        enrich_shipcancels(inventory,rows,script_service)
        audit=audit_rows(rows)
        gap_notes=split_gap_by_matusetrans(inventory,rows,script_service)
        planned={}
        for r in rows:
            text=description(r["old_description"],audit["records"][r["id"]],{})
            if r.get("ref_mbo")=="MATUSETRANS":
                extra=gap_notes.get(r.get("ref_id"))
                if extra and "SPLIT LIPSA:" not in text:
                    token=" | BADFIFO="
                    pos=text.rfind(token)
                    if pos>=0:
                        merged=text[:pos]+" | "+extra+text[pos:]
                    else:
                        merged=text+" | "+extra
                    if len(merged)<=MAX_DESCRIPTION:
                        text=merged
            planned[r["id"]]=text
        verify=open_scope(inventory,"CXSTOCURI")
        fresh,unused=read_journal(verify)
        if snapshot(fresh)!=original:
            raise ValueError("Jurnal modificat concurent; reruleaza Check FIFO")
        close_set(verify)
        verify=None
        changed=0
        for r in rows:
            if planned[r["id"]]!=r["old_description"]:
                mbos[r["id"]].setValue("DESCRIPTION_LONGDESCRIPTION",planned[r["id"]],MboConstants.NOACCESSCHECK)
                changed+=1
        if changed:
            root.save()
        message=reorder_msg+"\n\n"+local_summary(audit,unknown)
        layers_text,layers_total=fifo_layers_situation(rows,audit,script_service)
        message+="\n\n"+layers_text
        message+="\n\n"+sync_invbalances_curbal(inventory,layers_total,audit,script_service)
        message+="\n\n"+sync_invlifofifocost(inventory,rows,audit,script_service)
        message+="\n\n"+invlifo_totals(inventory,rows,script_service)
        script_service.log_info("CXINVAUDIT "+VERSION+": "+message.replace("\n"," | "))
    finally:
        close_set(verify)
        close_set(root)
    try:
        refresh_fifo_table(bean)
    except Exception as exc:
        message+="\nInfo salvat; refresh nereusit. Redeschide articolul."
        script_service.log_info("CXINVAUDIT refresh: "+txt(exc))
    return message
