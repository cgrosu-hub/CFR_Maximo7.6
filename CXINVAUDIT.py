# SCRIPT: CXINVAUDIT
# AUTOR: Cristian Grosu
# VERSIUNE: 5.6-VOIDRECEIPT
# Audit FIFO local CXSTOCURI. Reia verificarea inclusiv pe iesirea cu sold >= 0.
# Un CXCURBAL negativ este soldul pretului curent, nu lipsa de stoc: daca un strat
# anterior acopera iesirea, se consuma FIFO si se raporteaza diferenta de pret.
# VOIDRECEIPT anuleaza stoc pe acelasi pret (preferinta: receptia cea mai recenta).
# Conventie: N + MOTIV=ORDINE_DATE daca deficitul poate fi asociat unor intrari
# ulterioare, acelasi CXREFMBO, RefID mai mic, pret compatibil si cantitate suficienta.
# ORDINE_DATE este o exceptie de afisare aprobata; nu certifica data reala.
# MATRECTRANS se citeste numai pentru FROMSTORELOC afisat pe intrari.
# INVLIFOFIFOCOST se citeste numai pentru reconcilierea informativa finala.
# Scrie numai DESCRIPTION_LONGDESCRIPTION. Nu modifica date/cantitati/preturi/solduri.
# Fara expresii regulate, fara restrictii de pilot, fara mod dry-run.

from java.math import BigDecimal, MathContext, RoundingMode
try:
    string_type = unicode
except NameError:
    string_type = str
class ExactNumber(object):
    DIVISION_CONTEXT = MathContext(34, RoundingMode.HALF_EVEN)
    def __init__(self, value):
        if isinstance(value, ExactNumber):
            value = value.value
        elif isinstance(value, float):
            raise ValueError("Foloseste sir sau BigDecimal, nu float, pentru calcule de cost")
        elif not isinstance(value, BigDecimal):
            value = BigDecimal(string_type(value))
        self.value = value.stripTrailingZeros()
    def __str__(self):
        return str(self.value.toPlainString())
    def __unicode__(self):
        return string_type(self.value.toPlainString())
    def __repr__(self):
        return "ExactNumber('%s')" % self.value.toPlainString()
    def __hash__(self):
        return self.value.hashCode()
    def compare(self, other):
        return self.value.compareTo(ExactNumber(other).value)
    def __eq__(self, other):
        if other is None:
            return False
        try:
            return self.compare(other) == 0
        except Exception:
            return False
    def __ne__(self, other):
        return not self == other
    def __lt__(self, other):
        return self.compare(other) < 0
    def __le__(self, other):
        return self.compare(other) <= 0
    def __gt__(self, other):
        return self.compare(other) > 0
    def __ge__(self, other):
        return self.compare(other) >= 0
    def __add__(self, other):
        return ExactNumber(self.value.add(ExactNumber(other).value))
    __radd__ = __add__
    def __sub__(self, other):
        return ExactNumber(self.value.subtract(ExactNumber(other).value))
    def __rsub__(self, other):
        return ExactNumber(other).__sub__(self)
    def __mul__(self, other):
        return ExactNumber(self.value.multiply(ExactNumber(other).value))
    __rmul__ = __mul__
    def __div__(self, other):
        return ExactNumber(self.value.divide(ExactNumber(other).value, self.DIVISION_CONTEXT))
    __truediv__ = __div__
    def __rdiv__(self, other):
        return ExactNumber(other).__div__(self)
    __rtruediv__ = __rdiv__
    def __neg__(self):
        return ExactNumber(self.value.negate())
    def __abs__(self):
        return ExactNumber(self.value.abs())
    def __nonzero__(self):
        return self.value.signum() != 0
    __bool__ = __nonzero__
    def fixed(self, scale):
        return str(self.value.setScale(scale, RoundingMode.HALF_EVEN).toPlainString())

VERSION = "5.6-VOIDRECEIPT"
FIFO_TABLE_ID = "1792055730066"
MAX_ROWS = 5000
MAX_DESCRIPTION = 32000
MAX_RECON_LINES = 30
FIX_PREFIX = "CXFIFO_FIX1|"
BEGIN = "CXFIFO_AUDIT_V2_BEGIN"
END = "CXFIFO_AUDIT_V2_END"
HEADER = "FIFO V2 | "
ZERO = ExactNumber("0")
COST_TOLERANCE = ExactNumber("0.0005")
QTY_TOLERANCE = ExactNumber("0.000001")
ENTRY_TYPES = ("RECEIPT", "SHIPRECEIPT", "TRANSFER")
EXIT_TYPES = ("ISSUE", "SHIPTRANSFER", "TRANSFER")
VOID_TYPES = ("VOIDRECEIPT",)
AMBIGUOUS_TYPES = ("SHIPCANCEL", "VOIDSHIPRECEIPT", "SHIPRETURN", "RECBALADJ")
def txt(value):
    return "" if value is None else string_type(value)

def dec(value):
    if value is None or txt(value).strip() == "":
        return None
    if hasattr(value, "toPlainString"):
        value = value.toPlainString()
    return ExactNumber(value)

def fmt(value):
    return "necunoscut" if value is None else ExactNumber(value).fixed(3)

def fmt_ro(value):
    return fmt(value).replace(".", ",")

def far(left, right, tolerance):
    return left is None or right is None or abs(left - right) > tolerance

def order(row):
    return (row.get("date") or "", row.get("ref_id") or 0, row["id"])

def escape_fix(value):
    return txt(value).replace("%", "%25").replace("|", "%7C").replace("\r", "%0D").replace("\n", "%0A")

def unescape_fix(value):
    return value.replace("%0A", "\n").replace("%0D", "\r").replace("%7C", "|").replace("%25", "%")

def fix_key(row, old, new, source_cost):
    from java.security import MessageDigest
    from java.lang import String
    parts = [row.get(k) for k in ("id", "item", "site", "location", "ref_mbo", "ref_id",
                                 "kind", "qty", "date", "group", "raw_asset")]
    parts += [old, new, source_cost]
    raw = "|".join(escape_fix(p) for p in parts)
    digest = MessageDigest.getInstance("SHA-256").digest(String(raw).getBytes("UTF-8"))
    return "".join("%02x" % (int(b) & 255) for b in digest)

def split_history(value):
    visible, history = [], []
    for line in info_plaintext(value).split("\n"):
        if line.startswith(FIX_PREFIX):
            parts = line.split("|")
            if len(parts) != 8:
                raise ValueError("Istoric corectie incomplet; nimic suprascris")
            old, new, source = [dec(v) for v in parts[1:4]]
            if any(v is None for v in (old, new, source)) or not parts[4] or not parts[5]:
                raise ValueError("Istoric corectie invalid")
            history.append({"old": old, "new": new, "source_cost": source,
                            "when": parts[4], "who": unescape_fix(parts[5]),
                            "key": parts[6], "role": parts[7], "line": line})
        elif FIX_PREFIX in line:
            raise ValueError("Marcaj corectie intr-o nota neidentificata; verificare manuala")
        else:
            visible.append(line)
    return "\n".join(visible).strip(), history

def validate_history(row, history):
    previous = None
    for entry in history:
        if history[0]["old"] != history[0]["source_cost"] or entry["source_cost"] != history[0]["source_cost"]:
            raise ValueError("Istoric fara pret oficial initial coerent; verificare manuala")
        if entry["role"] not in ("IESIRE", "PERECHE") or entry["key"] != fix_key(
                row, entry["old"], entry["new"], entry["source_cost"]):
            raise ValueError("Istoric incompatibil cu CXSTOCURIID=%s" % row["id"])
        if previous is not None and previous != entry["old"]:
            raise ValueError("Lant de corectii intrerupt pentru CXSTOCURIID=%s" % row["id"])
        previous = entry["new"]
    if history and previous != row.get("cost"):
        raise ValueError("Pretul curent difera de ultima corectie pentru CXSTOCURIID=%s" % row["id"])

def consume(layers, required):
    allocations = []
    for layer in layers:
        if required <= QTY_TOLERANCE:
            break
        take = min(required, layer["qty"])
        if take > ZERO:
            allocation = dict(layer)
            allocation["qty"] = take
            allocations.append(allocation)
            required -= take
            layer["qty"] -= take
    layers[:] = [layer for layer in layers if layer["qty"] > QTY_TOLERANCE]
    return allocations

def consume_at_cost(layers, required, cost, newest_first=False):
    # VOIDRECEIPT anuleaza pe pret; newest_first leaga de receptia recenta anulata.
    allocations = []
    indexes = range(len(layers) - 1, -1, -1) if newest_first else range(len(layers))
    for index in indexes:
        if required <= QTY_TOLERANCE:
            break
        layer = layers[index]
        if far(layer["cost"], cost, COST_TOLERANCE):
            continue
        take = min(required, layer["qty"])
        if take > ZERO:
            allocation = dict(layer)
            allocation["qty"] = take
            allocations.append(allocation)
            required -= take
            layer["qty"] -= take
    layers[:] = [layer for layer in layers if layer["qty"] > QTY_TOLERANCE]
    return allocations, required

def info_plaintext(value):
    value = txt(value).replace("<!-- RICH TEXT -->", "")
    for separator in ("<br />", "<br/>", "<br>", "<BR />", "<BR/>", "<BR>"):
        value = value.replace(separator, "\n")
    return value.replace("\r\n", "\n").replace("\r", "\n").strip()

def display_destination(row):
    if row.get("kind") == "INITIAL":
        return row.get("location") or "-"
    return row.get("destination") or "-"

def is_outgoing(row):
    qty = row.get("qty")
    return row.get("kind") != "INITIAL" and qty is not None and qty < -QTY_TOLERANCE

def description(old, record, summary):
    visible, history = split_history(old)
    validate_history(record["row"], history)
    value = description_visible(visible, record, summary)
    value = "\n".join([value] + [entry["line"] for entry in history])
    if len(value) > MAX_DESCRIPTION:
        raise ValueError("Istoric prea lung; nimic salvat")
    return value

def fifo_table(inventory, script_service):
    from psdi.common.context import UIContext
    context = UIContext.getCurrentContext()
    session = context.getWebClientSession() if context is not None else None
    if session is None:
        raise ValueError("Check FIFO se ruleaza din aplicatie; sesiunea UI lipseste")
    bean = session.getDataBean(FIFO_TABLE_ID)
    if bean is None:
        raise ValueError("Tabelul FIFO nu a fost gasit. Confirma ID-ul " + FIFO_TABLE_ID + " in Application Designer")
    table_set = bean.getMboSet()
    if table_set is None or txt(table_set.getName()).upper() != "CXSTOCURI":
        raise ValueError("ID-ul configurat nu identifica tabelul CXSTOCURI")
    if table_set.toBeSaved():
        raise ValueError("Exista modificari nesalvate in jurnal; nu se face refresh")
    visible = table_set.getMbo(0)
    if visible is not None and any(visible.getString(f) != inventory.getString(f) for f in ("ITEMNUM", "SITEID", "LOCATION")):
        raise ValueError("Tabelul afisat nu corespunde articolului/gestiunii selectate")
    return bean

def refresh_fifo_table(bean):
    bean.reset()
    bean.refreshTable()

def ordinary_entry(row):
    return row.get("kind") in ENTRY_TYPES and row.get("qty") is not None and row["qty"] > QTY_TOLERANCE

def flag(record):
    row=record["row"]
    if ordinary_entry(row):
        return None
    if row.get("kind")=="INITIAL" or record["status"]=="N/A":
        return "NA"
    if record["status"] in ("OK","DATE_ORDER"):
        return "N"
    if record["status"]=="BAD" and record["expected"] is not None:
        return "Y"
    return "U"

def new_local_record(row):
    return {"row":row,"status":"UNVERIFIED","expected":None,"allocations":[],
            "reason":"Verificare neefectuata","balance_expected":None,"balance_bad":False,
            "balance_missing":row.get("balance") is None,"resumed":False,"local_basis":False,
            "date_candidate_eligible":False,"partial_allocations":[],"shortfall":ZERO}

def mark_shortage(rec,layers,required,reason):
    available=sum((l["qty"] for l in layers),ZERO)
    partial=consume(layers,min(required,available))
    shortage=max(ZERO,required-sum((a["qty"] for a in partial),ZERO))
    rec["partial_allocations"]=partial
    rec["shortfall"]=shortage
    rec["date_candidate_eligible"]=shortage>QTY_TOLERANCE
    rec["reason"]=reason

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

def put_back(layers,qty,cost,priority,source,source_ref):
    for layer in layers:
        if not far(layer["cost"],cost,COST_TOLERANCE) and layer.get("priority")==priority:
            layer["qty"]+=qty
            return
    layers.append({"qty":qty,"cost":cost,"source":source,"source_ref_id":source_ref,"initial":False,"priority":priority})
    layers.sort(key=lambda layer: layer["priority"])

def return_target(row,group_rows,records):
    issue_id=row.get("issue_id")
    if issue_id is None:
        return None,"Retur fara ISSUEID",None,None,None
    matches=[r for r in group_rows if r.get("ref_mbo")=="MATUSETRANS" and r.get("ref_id")==issue_id and r.get("kind")=="ISSUE" and order(r)<order(row)]
    if len(matches)!=1:
        return None,"Consumul ISSUEID=%s nu este unic in jurnal, inaintea returului" % issue_id,None,None,None
    issue=matches[0]
    rec=records[issue["id"]]
    if rec["status"] in ("OK","BAD","DATE_ORDER") and rec["expected"] is not None:
        expected=rec["expected"]
    elif issue.get("cost") is not None:
        expected=issue["cost"]
    else:
        return None,"Consumul %s nu are pret verificabil" % issue_id,None,None,None
    allocs=rec.get("allocations") or []
    if allocs:
        source,source_ref,priority=allocs[0].get("source"),allocs[0].get("source_ref_id"),allocs[0].get("priority") or order(issue)
    else:
        source,source_ref,priority=issue["id"],issue.get("ref_id"),order(issue)
    return expected,issue.get("ref_id"),source_ref,priority,source

def audit_rows(rows):
    records=dict((r["id"],new_local_record(r)) for r in rows)
    if len(records)!=len(rows):
        raise ValueError("CXSTOCURIID duplicat")
    groups,issues={},[]
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
                    cost in openings or (row["date"] in initial_dates and initial_dates[row["date"]]!=cost)):
                    structural="INITIAL incomplet/negativ/duplicat/dupa miscari sau ordine ambigua"
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
                                   "source_ref_id":row.get("ref_id"),"initial":True,"priority":order(row)})
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
                expected,link_ref,source_ref,priority,source=return_target(row,group_rows,records)
                if expected is None:
                    rec["reason"]=link_ref
                    continue
                rec["expected"]=expected
                rec["link_ref"]=link_ref
                rec["status"]="BAD" if far(cost,expected,COST_TOLERANCE) else "OK"
                rec["allocations"]=[{"qty":qty,"cost":expected,"source":source,"source_ref_id":source_ref,
                                     "initial":False,"priority":priority}]
                put_back(layers,qty,expected,priority,source,source_ref)
                local_prices.add(expected)
                local_started=True
                continue
            if kind in VOID_TYPES:
                if qty>=-QTY_TOLERANCE:
                    rec["reason"]="VOIDRECEIPT fara cantitate negativa"
                    continue
                required=-qty
                available=sum((l["qty"] for l in layers if not far(l["cost"],cost,COST_TOLERANCE)),ZERO)
                if available+QTY_TOLERANCE<required:
                    rec["reason"]="Stoc pe pret insuficient pentru VOIDRECEIPT"
                    continue
                allocations,short=consume_at_cost(layers,required,cost,newest_first=True)
                if short>QTY_TOLERANCE or not allocations:
                    rec["reason"]="VOIDRECEIPT nu a putut anula stocul pe pret"
                    continue
                rec["allocations"]=allocations
                rec["expected"]=cost
                rec["status"]="OK"
                local_started=True
                continue
            if kind in AMBIGUOUS_TYPES:
                structural="Tip %s fara alocare verificabila in jurnal" % kind
                rec["reason"]=structural
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
                                   "source_ref_id":row.get("ref_id"),"initial":False,"priority":order(row)})
                    layers.sort(key=lambda l:l["priority"])
                rec["status"]="INPUT"
                continue
            if kind not in EXIT_TYPES:
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
            # CXCURBAL tine soldul acestui pret. Stratul de la alt pret poate acoperi iesirea.
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
        # Exceptia nu reordoneaza replay-ul si nu scade din nou intrarile.
        if not structural:
            apply_date_order_policy(group_rows,records)
        ledger+=sum(book.values(),ZERO)
        if structural:
            issues.append("Grupa %s: %s" % (group or "(gol)",structural))
        elif recovering:
            issues.append("Grupa %s: segment fara baza cronologica recuperata" % (group or "(gol)"))
        if had_gap or not seen_initial:
            issues.append("Grupa %s: istoric local incomplet/reluat; trecutul nu este certificat" % (group or "(gol)"))
    return {"records":records,"issues":issues,"ledger_qty":ledger if ledger_known else None}
def generated_compact_legacy(value):
    value = info_plaintext(value)
    if "\n" in value:
        return False
    parts = value.split(" | ")
    if (len(parts) == 2 and parts[0].startswith("FROMSTORELOC=") and
            parts[1].startswith("INVUSEID=")):
        invuseid = parts[1][len("INVUSEID="):]
        return bool(parts[0][len("FROMSTORELOC="):]) and (invuseid == "-" or invuseid.isdigit())
    prefixes = ("INITIAL: ", "ANULAT: ", "OK: ", "DIFERENTA: ", "CORECTAT: ",
                "EXPEDIERE ANULATA: ", "ANULARE EXPEDIERE: ", "INTRARE OK: ",
                "FARA MISCARE: ", "NEVERIFICAT: ", "DIFERENTA SURSA: ", "DIFERENTA SOLD: ")
    if len(parts) < 2 or parts[-1] not in ("BADFIFO=Y", "BADFIFO=N", "BADFIFO=U", "BADFIFO=NA"):
        return False
    body = parts[:-1]
    if body and body[-1].startswith("Sursa="):
        if not all(v.isdigit() or v=="INITIAL" for v in body[-1][len("Sursa="):].split(",")):
            return False
        body = body[:-1]
    if len(body) == 1:
        return body[0].startswith(prefixes)
    return len(body) == 2 and bool(body[0]) and body[1].startswith(prefixes)

def generated_compact_info(value):
    value = info_plaintext(value)
    if "\n" in value:
        return False
    if value.startswith("FROMSTORELOC=") and " | " not in value:
        return bool(value[len("FROMSTORELOC="):].strip())
    prefix = "INITIAL: FIFO LOCAL "
    if value.startswith(prefix):
        parts = value[len(prefix):].split(" buc. la ")
        if len(parts) != 2:
            return False
        for part in parts:
            if part == "necunoscut":
                continue
            try:
                number = dec(part.replace(",", "."))
                if number is None or fmt_ro(number) != part:
                    return False
            except Exception:
                return False
        return True
    if value == "INITIAL: BAZA NECONCLUDENTA; vezi rezumatul auditului":
        return True
    parts = value.split(" | ")
    if "MOTIV=ORDINE_DATE" in parts:
        if parts.count("MOTIV=ORDINE_DATE") != 1:
            return False
        parts.remove("MOTIV=ORDINE_DATE")
        value = " | ".join(parts)
    return generated_compact_legacy(value)
def description_visible(old, record, summary):
    kept = txt(old)
    for begin, end in ((BEGIN, END), ("CXFIFO_AUDIT_V1_BEGIN", "CXFIFO_AUDIT_V1_END")):
        while begin in kept:
            start = kept.find(begin)
            finish = kept.find(end, start)
            if finish < 0:
                raise ValueError("Bloc de audit incomplet; descrierea nu este suprascrisa")
            prefix = kept[:start].strip()
            if begin == BEGIN and prefix.startswith(HEADER):
                prefix = ""
            if begin != BEGIN and prefix in (
                    txt(record["row"].get("destination")).strip(),
                    txt(record["row"].get("original_destination")).strip()):
                prefix = ""
            kept = "\n".join(part for part in (prefix, kept[finish + len(end):].strip()) if part)
    if kept.startswith(HEADER):
        parts = kept.split("\n", 1)
        kept = parts[1].strip() if len(parts) > 1 else ""
    previous = info_plaintext(kept).split("\n")
    states = ("OK", "BAD", "INITIAL", "COMPENSAT", "INTRARE", "ZERO", "NECONCLUDENT", "SURSA", "SOLD")
    if len(previous) == 3 and previous[1] in ("BADFIFO=Y", "BADFIFO=N", "BADFIFO=U", "BADFIFO=NA"):
        metadata = previous[2].split("; STARE=")
        if len(metadata) == 2 and metadata[0].startswith("FIFO=") and metadata[1] in states:
            price = metadata[0][len("FIFO="):]
            try:
                if price != "-":
                    dec(price.replace(",", "."))
                kept = ""
            except Exception:
                pass
    if generated_compact_info(kept):
        kept = ""
    row = record["row"]
    if info_plaintext(kept):
        raise ValueError("CXSTOCURIID=%s contine note manuale; descrierea nu este suprascrisa" % row["id"])
    if ordinary_entry(row):
        return "FROMSTORELOC="+(txt(row.get("from_location")).strip() or "NEIDENTIFICAT")
    if row.get("kind")=="INITIAL":
        if record["status"]!="INITIAL":
            return "INITIAL: BAZA NECONCLUDENTA; vezi rezumatul auditului"
        return "INITIAL: FIFO LOCAL %s buc. la %s" % (fmt_ro(row.get("balance")),fmt_ro(row.get("cost")))
    status=record["status"]
    if status=="DATE_ORDER":
        info="OK: pret compatibil %s; intrare ulterioara cu RefID anterior; data iesirii de verificat (conventie)" % fmt_ro(record["expected"])
    elif status=="OK" and row.get("kind")=="VOIDRECEIPT":
        info="OK: VOIDRECEIPT anuleaza %s buc. la %s" % (fmt_ro(-row["qty"]),fmt_ro(record["expected"]))
    elif status=="OK":
        info="OK: FIFO LOCAL asteptat %s" % fmt_ro(record["expected"])
    elif status=="BAD":
        info="DIFERENTA: FIFO LOCAL pret %s; asteptat %s; diferenta %s" % (
            fmt_ro(row["cost"]),fmt_ro(record["expected"]),fmt_ro(row["cost"]-record["expected"]))
    elif status=="N/A":
        info="FARA MISCARE: cantitate zero"
    else:
        info="NEVERIFICAT: "+record["reason"]
    if record.get("link_ref") is not None and status in ("OK","BAD"):
        info+="; consum %s" % record["link_ref"]
    if record.get("local_basis") and status in ("OK","BAD"):
        info+="; baza locala din intrari"
    if record.get("resumed"):
        info+="; audit reluat pe aceasta iesire"
    if record.get("balance_missing"):
        info+="; ATENTIE SOLD: CXCURBAL lipsa"
    elif record["balance_bad"]:
        info+="; ATENTIE SOLD: inregistrat %s; calculat %s" % (fmt_ro(row.get("balance")),fmt_ro(record["balance_expected"]))
    sources=[]
    for a in record["allocations"]:
        label=txt(a.get("source_ref_id")) if a.get("source_ref_id") is not None else ("INITIAL" if a.get("initial") else "")
        if label and label not in sources:
            sources.append(label)
    parts=[info]
    if sources:
        parts.append("Sursa="+",".join(sources))
    if status=="DATE_ORDER":
        parts.append("MOTIV=ORDINE_DATE")
    parts.append("BADFIFO="+flag(record))
    value=" | ".join(parts)
    if len(value)>MAX_DESCRIPTION:
        raise ValueError("Descriere prea lunga; nimic salvat")
    return value

def numeric_field(m,field):
    if m.isNull(field):
        return None
    raw=m.getMboValue(field).getCurrentValue().asString().strip()
    try:
        return dec(raw)
    except Exception:
        from java.text import NumberFormat,ParsePosition
        parser=NumberFormat.getNumberInstance(m.getUserInfo().getLocale())
        parser.setParseBigDecimal(True)
        pos=ParsePosition(0)
        value=parser.parse(raw,pos)
        if value is None or pos.getIndex()!=len(raw):
            raise ValueError("Numar neinterpretabil %s=%s" % (field,raw))
        return dec(value)

def date_key(value):
    if value is None:
        return None
    from java.text import SimpleDateFormat
    from java.util import TimeZone
    f=SimpleDateFormat("yyyy-MM-dd HH:mm:ss")
    f.setTimeZone(TimeZone.getTimeZone("UTC"))
    nanos=value.getNanos() if hasattr(value,"getNanos") else (value.getTime()%1000)*1000000
    return f.format(value)+".%09d" % nanos

def close_set(ms):
    if ms is not None:
        try:
            ms.cleanup()
        finally:
            ms.close()

def open_scope(inventory,name,with_itemset=False):
    from psdi.server import MXServer
    from psdi.mbo import SqlFormat
    ms=MXServer.getMXServer().getMboSet(name,inventory.getUserInfo())
    try:
        fields=["ITEMNUM","SITEID","LOCATION"]
        if with_itemset:
            if inventory.isNull("ITEMSETID"):
                raise ValueError("ITEMSETID lipsa")
            fields.append("ITEMSETID")
        condition=SqlFormat(" AND ".join("%s=:%s" % (f,i+1) for i,f in enumerate(fields)))
        for i,f in enumerate(fields):
            condition.setObject(i+1,name,f,inventory.getString(f))
        ms.setWhere(condition.format())
        if name=="CXSTOCURI":
            ms.setOrderBy("CXDOCUMENTDATE,CXREFID,CXSTOCURIID")
        ms.reset()
        return ms
    except Exception:
        close_set(ms)
        raise

def read_journal(ms):
    rows,mbos,currencies=[],{},set()
    m=ms.moveFirst()
    while m is not None:
        if len(rows)>=MAX_ROWS:
            raise ValueError("Limita de randuri depasita; nimic salvat")
        rid=m.getLong("CXSTOCURIID")
        if rid in mbos:
            raise ValueError("CXSTOCURIID duplicat")
        currency=m.getString("CURRENCYCODE")
        currencies.add(currency)
        row={"id":rid,"item":m.getString("ITEMNUM"),"site":m.getString("SITEID"),
             "location":m.getString("LOCATION"),
             "date":date_key(None if m.isNull("CXDOCUMENTDATE") else m.getDate("CXDOCUMENTDATE")),
             "ref_id":None if m.isNull("CXREFID") else m.getLong("CXREFID"),
             "ref_mbo":m.getString("CXREFMBO"),"kind":m.getString("CXREF"),
             "qty":numeric_field(m,"CXQTY"),"cost":numeric_field(m,"UNITCOST"),
             "balance":numeric_field(m,"CXCURBAL"),"group":m.getString("COMMODITYGROUP"),
             "asset":m.getString("ROTASSETNUM"),"raw_asset":m.getString("ROTASSETNUM"),
             "currency":currency,"rowstamp":txt(m.getRowStamp()),
             "old_description":m.getString("DESCRIPTION_LONGDESCRIPTION")}
        rows.append(row)
        mbos[rid]=m
        m=ms.moveNext()
    if len(currencies)>1:
        raise ValueError("Monede diferite in jurnal; nu se compara fara conversie")
    return rows,mbos

def snapshot(rows):
    fields=("id","item","site","location","date","ref_id","ref_mbo","kind","qty","cost","balance","group","raw_asset","currency","rowstamp","old_description")
    return sorted(tuple(txt(r.get(k)) for k in fields) for r in rows)

def enrich_origins(inventory,rows,script_service):
    from psdi.server import MXServer
    pending=sorted(set(r["ref_id"] for r in rows if ordinary_entry(r) and r.get("ref_mbo")=="MATRECTRANS" and r.get("ref_id") is not None))
    locations={}
    for start in range(0,len(pending),500):
        ms=None
        try:
            ms=MXServer.getMXServer().getMboSet("MATRECTRANS",inventory.getUserInfo())
            ms.setWhere("MATRECTRANSID IN (%s)" % ",".join(txt(i) for i in pending[start:start+500]))
            ms.reset()
            m=ms.moveFirst()
            while m is not None:
                locations[m.getLong("MATRECTRANSID")]=m.getString("FROMSTORELOC")
                m=ms.moveNext()
        except Exception as exc:
            script_service.log_info("CXINVAUDIT provenienta indisponibila: "+txt(exc))
        finally:
            close_set(ms)
    unknown=0
    for row in rows:
        if not ordinary_entry(row):
            continue
        location=locations.get(row.get("ref_id"),"") if row.get("ref_mbo")=="MATRECTRANS" else ""
        if not location:
            first=info_plaintext(row.get("old_description","")).split(" | ")[0]
            if first.startswith("FROMSTORELOC=") and "\n" not in first:
                location=first[len("FROMSTORELOC="):].strip()
        row["from_location"]=location or "NEIDENTIFICAT"
        unknown+=1 if row["from_location"]=="NEIDENTIFICAT" else 0
    return unknown

def enrich_returns(inventory,rows,script_service):
    from psdi.server import MXServer
    pending=sorted(set(r["ref_id"] for r in rows if r.get("kind")=="RETURN" and r.get("ref_mbo")=="MATUSETRANS" and r.get("ref_id") is not None))
    links={}
    for start in range(0,len(pending),500):
        ms=None
        try:
            ms=MXServer.getMXServer().getMboSet("MATUSETRANS",inventory.getUserInfo())
            ms.setWhere("MATUSETRANSID IN (%s)" % ",".join(txt(i) for i in pending[start:start+500]))
            ms.reset()
            m=ms.moveFirst()
            while m is not None:
                links[m.getLong("MATUSETRANSID")]=None if m.isNull("ISSUEID") else m.getLong("ISSUEID")
                m=ms.moveNext()
        except Exception as exc:
            script_service.log_info("CXINVAUDIT legatura retur indisponibila: "+txt(exc))
        finally:
            close_set(ms)
    for row in rows:
        if row.get("kind")=="RETURN" and row.get("ref_mbo")=="MATUSETRANS":
            row["issue_id"]=links.get(row.get("ref_id"))

def local_summary(audit,unknown_origins):
    records=list(audit["records"].values())
    exits=[r for r in records if is_outgoing(r["row"])]
    counts=dict((f,sum(1 for r in exits if flag(r)==f)) for f in ("N","Y","U"))
    date_orders=sum(1 for r in exits if r["status"]=="DATE_ORDER")
    structural=sum(1 for r in records if r["status"]=="UNVERIFIED" and not is_outgoing(r["row"]))
    verdict="DIFERENTE" if counts["Y"] else ("NECONCLUDENT" if counts["U"] or structural else ("N CU EXCEPTII ORDINE_DATE" if date_orders else "OK"))
    warnings=sum(1 for r in records if r["balance_bad"] or r["balance_missing"])
    entries=sum(1 for r in records if ordinary_entry(r["row"]))
    returns=[r for r in records if r["row"].get("kind")=="RETURN"]
    return_counts=dict((f,sum(1 for r in returns if flag(r)==f)) for f in ("N","Y","U"))
    if return_counts["Y"]:
        verdict="DIFERENTE"
    lines=["CHECK FIFO","Verdict: "+verdict,"",
           "Iesiri","  OK: %s" % counts["N"],"  Diferenta de pret: %s" % counts["Y"],
           "  Neverificate: %s" % counts["U"],
           "  Iesiri cu data de verificat: %s" % date_orders,"",
           "Intrari","  Informative: %s" % entries,
           "  Avertizari de sold: %s" % warnings,
           "  Provenienta necunoscuta: %s" % unknown_origins,
           "  Cantitate ramasa in CXSTOCURI: %s" % fmt_ro(audit["ledger_qty"])]
    if returns:
        lines.extend(["","Retururi","  OK: %s" % return_counts["N"],
                      "  Diferenta de pret: %s" % return_counts["Y"],
                      "  Neverificate: %s" % return_counts["U"]])
    return "\n".join(lines)

def recorded_balances_by_cost(rows):
    last={}
    for row in sorted(rows,key=order):
        if row.get("cost") is None or not row.get("date"):
            raise ValueError("Pret/data lipsa; sold final nedeterminabil")
        last[(row.get("group") or "",row["cost"])]=row
    totals={}
    for key,row in last.items():
        if row.get("balance") is None:
            raise ValueError("Sold final lipsa")
        totals[key[1]]=totals.get(key[1],ZERO)+row["balance"]
    return totals

def price_label(value):
    rounded=fmt(value)
    return (rounded if dec(rounded)==value else txt(value)).replace(".",",")

def informative_reconciliation(inventory,rows,script_service):
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
        lines,differences=[],0
        for price in sorted(set(journal)|set(official)):
            left,right=journal.get(price,ZERO),official.get(price,ZERO)
            bad=far(left,right,QTY_TOLERANCE)
            differences+=1 if bad else 0
            lines.append("Pret %s [%s]\n  CXSTOCURI %s | INVLIFOFIFOCOST %s | Diferenta %s" % (
                price_label(price),"DIFERENTA" if bad else "OK",fmt_ro(left),fmt_ro(right),fmt_ro(left-right)))
        jq,fq=sum(journal.values(),ZERO),sum(official.values(),ZERO)
        jv=sum((p*q for p,q in journal.items()),ZERO)
        fv=sum((p*q for p,q in official.items()),ZERO)
        title="COMPARATIE CXSTOCURI / INVLIFOFIFOCOST: "+("DIFERENTE" if differences or invalid else "OK")
        totals=["","Totaluri","  Cantitate: CXSTOCURI %s | INVLIFOFIFOCOST %s | diferenta %s" % (fmt_ro(jq),fmt_ro(fq),fmt_ro(jq-fq)),
                "  Valoare: CXSTOCURI %s | INVLIFOFIFOCOST %s | diferenta %s" % (fmt_ro(jv),fmt_ro(fv),fmt_ro(jv-fv))]
        notes=[]
        if count==0:
            notes.append("INVLIFOFIFOCOST nu are randuri. Comparatia foloseste zero.")
        if invalid:
            notes.append("INVLIFOFIFOCOST cu pret sau cantitate negativa: %s." % invalid)
        script_service.log_info("CXINVAUDIT RECON COMPLET: "+" | ".join([title]+lines+totals+notes))
        visible=[title]+lines[:MAX_RECON_LINES]
        if len(lines)>MAX_RECON_LINES:
            visible.append("Primele %s preturi; detalii complete in log." % MAX_RECON_LINES)
        return "\n".join(visible+totals+notes)
    except Exception as exc:
        script_service.log_info("CXINVAUDIT RECON indisponibila: "+txt(exc))
        return "COMPARATIE INDISPONIBILA: %s. Auditul local ramane valabil." % txt(exc)
    finally:
        close_set(ms)

def check_layer_beats_negative_balance():
    def row(ident, date, ref, kind, qty, cost, balance, mbo="MATRECTRANS"):
        return {"id":ident,"group":"G","date":date,"ref_id":ref,"ref_mbo":mbo,
                "kind":kind,"qty":ExactNumber(qty),"cost":ExactNumber(cost),"balance":ExactNumber(balance)}
    audit=audit_rows([
        row(1,"2026-06-01 00:00:00.000000000",300,"SHIPTRANSFER","-10","9.098","-10"),
        row(2,"2026-06-08 00:00:00.000000000",100,"SHIPRECEIPT","10","9.098","0"),
        row(3,"2026-09-07 00:00:00.000000000",400,"SHIPRECEIPT","20","9.846","20"),
        row(4,"2026-09-10 00:00:00.000000000",500,"SHIPTRANSFER","-1","9.098","-1"),
    ])
    rec=audit["records"][4]
    if rec["status"]!="BAD" or far(rec["expected"],ExactNumber("9.846"),COST_TOLERANCE):
        raise ValueError("self-check: iesirea nu consuma stratul anterior")
    if not rec["allocations"] or rec["allocations"][0].get("source_ref_id")!=400:
        raise ValueError("self-check: sursa nu este intrarea anterioara")
    blocked=audit_rows([
        row(1,"2026-06-01 00:00:00.000000000",1,"SHIPTRANSFER","-1","9","-1"),
        row(2,"2026-06-02 00:00:00.000000000",2,"SHIPTRANSFER","-1","9","-2"),
    ])
    if blocked["records"][2]["status"]!="UNVERIFIED":
        raise ValueError("self-check: iesirea fara stoc nu trebuie certificata")
    voided=audit_rows([
        row(1,"2026-09-07 00:00:00.000000000",10,"RECEIPT","50319","9.846","50319"),
        row(2,"2026-09-11 00:00:00.000000000",20,"RECEIPT","172","9.846","50491"),
        row(3,"2026-09-11 00:00:00.000000000",30,"VOIDRECEIPT","-172","9.846","50319"),
        row(4,"2026-09-12 00:00:00.000000000",40,"ISSUE","-542","9.846","49777","MATUSETRANS"),
    ])
    if voided["records"][3]["status"]!="OK":
        raise ValueError("self-check: VOIDRECEIPT trebuie sa fie OK")
    if not voided["records"][3]["allocations"] or voided["records"][3]["allocations"][0].get("source_ref_id")!=20:
        raise ValueError("self-check: VOIDRECEIPT trebuie sa anuleze receptia recenta")
    if voided["records"][4]["status"]!="OK":
        raise ValueError("self-check: ISSUE dupa VOIDRECEIPT trebuie verificat")

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
        original=snapshot(rows)
        unknown=enrich_origins(inventory,rows,script_service)
        enrich_returns(inventory,rows,script_service)
        audit=audit_rows(rows)
        planned=dict((r["id"],description(r["old_description"],audit["records"][r["id"]],{})) for r in rows)
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
        message=local_summary(audit,unknown)
        message+="\n\n"+informative_reconciliation(inventory,rows,script_service)
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

if "mbo" in globals() and "service" in globals():
    try:
        result=run_local(mbo,service)
    except ValueError as exc:
        result="Audit local oprit: "+txt(exc)
    service.error("CXCHECKFIFO","RESULT",[result])