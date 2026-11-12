# -*- coding: utf-8 -*-
# SCRIPT: CXINVAUDIT
# AUTOR ORIGINAL: Cristian Grosu; revizie 5.25-RECEIPT-SAFE
# FIFO pe straturi cu provenienta. CXCURBAL validat pe grupa, pret si receptie.
# Retururile/anularile repetate scad din cantitatea originala returnabila.
# Provenienta gresita / split incomplet / istoric incomplet blocheaza reconcilierea.
# INVBALANCES si INVLIFOFIFOCOST sunt reconciliate intr-o singura tranzactie.
# Nu se creeaza straturi oficiale: daca lipsesc randuri reutilizabile, nu se salveaza partial.
# Soldul oficial negativ necesita reconciliere explicita, nu este inlocuit automat.
# Info FIFO simplificat; BADFIFO si verificarile interne raman active.

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

VERSION = "5.25-RECEIPT-SAFE"
FIFO_TABLE_ID = "1792055730066"
MAX_ROWS = 5000
MAX_DESCRIPTION = 32000
MAX_LAYER_LINES = 30
FIX_PREFIX = "CXFIFO_FIX1|"
BEGIN = "CXFIFO_AUDIT_V2_BEGIN"
END = "CXFIFO_AUDIT_V2_END"
HEADER = "FIFO V2 | "
ZERO = ExactNumber("0")
COST_TOLERANCE = ExactNumber("0.0005")
QTY_TOLERANCE = ExactNumber("0.000001")
ENTRY_TYPES = ("RECEIPT", "SHIPRECEIPT", "TRANSFER")
EXIT_TYPES = ("ISSUE", "SHIPTRANSFER", "TRANSFER")
VOID_TYPES = ("VOIDRECEIPT", "SHIPRETURN")
AMBIGUOUS_TYPES = ("VOIDSHIPRECEIPT", "RECBALADJ")

# BEGIN FIFO RECEIPT KERNEL 1.0 -- identical in all three scripts.
def cx_key_number(value):
    if value is None:
        raise ValueError("Numar lipsa in cheia de strat")
    v = value.value if hasattr(value, "value") else value
    return str(v.stripTrailingZeros().toPlainString())

def cx_receipt_balances(rows, zero):
    """Post-movement balances by group, price and receipt; never by inventory total.
    Source-less legacy movements are inferred only with one unambiguous bucket.
    Returns: (id -> balance, id -> source key, id -> diagnostic).
    Input dictionaries must be sorted-compatible (date/ref/id) and scope-local.
    """
    books, keys, result, errors, last_issue = {}, {}, {}, {}, {}
    def add(a, b):
        return a.add(b) if hasattr(a, "add") else a+b
    def negative(a):
        return a.signum() < 0 if hasattr(a, "signum") else a < zero
    def positive(a):
        return a.signum() > 0 if hasattr(a, "signum") else a > zero
    for r in sorted(rows, key=lambda x:(x["date"], x.get("ref") or 0, x["id"])):
        ident, kind, cost, qty = r["id"], r["kind"], r.get("cost"), r.get("qty")
        if not r.get("date") or cost is None or negative(cost):
            raise ValueError("Data/pret neconform CXSTOCURIID=%s" % ident)
        group, price = r.get("group") or "", cx_key_number(cost)
        receipt = r.get("receipt")
        if kind == "INITIAL":
            key = (group, price, "INITIAL", ident)
            if r.get("balance") is None:
                raise ValueError("INITIAL fara sold CXSTOCURIID=%s" % ident)
            books[key] = r["balance"]
        else:
            if qty is None:
                raise ValueError("Cantitate lipsa CXSTOCURIID=%s" % ident)
            if receipt is not None:
                key = (group, price, "MATRECTRANS", receipt)
            elif kind == "RETURN" and r.get("issue_id") in last_issue:
                origin = last_issue[r["issue_id"]]
                key = (group, price, origin[2], origin[3])
            else:
                candidates = [k for k in books if k[:2] == (group, price) and positive(books[k])]
                if not candidates:
                    candidates = [k for k in books if k[:2] == (group, price)]
                if len(candidates) == 1:
                    key = candidates[0]
                else:
                    key = (group, price, "UNKNOWN", 0)
                    errors[ident] = "Provenienta pe receptie lipsa/ambigua; nu cumula straturile la acelasi pret"
            books[key] = add(books.get(key, zero), qty)
        keys[ident], result[ident] = key, books[key]
        if r.get("refmbo") == "MATUSETRANS" and kind == "ISSUE":
            last_issue[r.get("ref")] = key
    return result, keys, errors

def cx_enrich_receipts(rows, query):
    """Batch-load source links, checking that the source belongs to the journal scope."""
    for table, pk in (("MATUSETRANS", "MATUSETRANSID"), ("MATRECTRANS", "MATRECTRANSID")):
        wanted = sorted(set(r["ref"] for r in rows if r.get("refmbo") == table and r.get("ref") is not None))
        found = {}
        for start in range(0, len(wanted), 300):
            unused, sources = query(table, "%s IN (%s)" % (pk, ",".join(str(i) for i in wanted[start:start+300])))
            for m in sources:
                found[m.getLong(pk)] = m
        for r in rows:
            if r.get("refmbo") != table or r.get("ref") is None:
                continue
            m = found.get(r["ref"])
            if m is None:
                raise ValueError("Sursa %s/%s lipsa" % (table, r["ref"]))
            if r.get("item") is not None and m.getString("ITEMNUM") != r["item"]:
                raise ValueError("Articol sursa/jurnal diferit")
            if table == "MATUSETRANS":
                if r.get("site") is not None and (m.getString("SITEID"), m.getString("STORELOC")) != (r["site"], r["location"]):
                    raise ValueError("Site/gestiune sursa/jurnal diferite")
                r["receipt"] = None if m.isNull("MATRECTRANSID") else m.getLong("MATRECTRANSID")
                r["issue_id"] = None if m.isNull("ISSUEID") else m.getLong("ISSUEID")
            elif r.get("qty") is not None:
                qty = r["qty"]
                inbound = qty.signum() > 0 if hasattr(qty, "signum") else qty > ZERO
                if inbound and r["kind"] in ("RECEIPT", "SHIPRECEIPT", "TRANSFER"):
                    r["receipt"] = r["ref"]
                elif not m.isNull("RECEIPTREF"):
                    r["receipt"] = m.getLong("RECEIPTREF")
    return rows

def cx_rollback(tx):
    if tx is not None:
        try:
            tx.rollback()
        except Exception:
            pass

def cx_verify_plans(plans, read_number):
    for m, field, kind, value, old in plans:
        valid = True
        if kind == "NUMBER":
            valid = read_number(m, field) == value
        elif kind == "ID":
            valid = not m.isNull(field) and m.getLong(field) == long(value)
        elif kind == "NULL":
            valid = m.isNull(field)
        elif kind == "TEXT":
            valid = m.getString(field) == value
        if not valid:
            raise ValueError("Logica save a suprascris %s.%s; rollback" % (m.getName(), field))
# END FIFO RECEIPT KERNEL


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


def clean_info_fifo(value):
    # Only presentation: never change status, balances or BADFIFO.
    parts=[]
    for part in value.replace("FIFO LOCAL ","").replace("FIFO LOCAL","").split(" | "):
        sections=[]
        for section in part.split("; "):
            stripped=section.strip()
            lowered=stripped.lower()
            if lowered.startswith("diferenta ") or lowered.startswith(u"diferen\u021ba "):
                continue
            if lowered.startswith("atentie sold: negativ") or lowered.startswith(u"aten\u021bie sold: negativ"):
                continue
            if stripped:
                sections.append(stripped)
        if sections:
            parts.append("; ".join(sections))
    return " | ".join(parts)


def description(old, record, summary):
    visible, history = split_history(old)
    validate_history(record["row"], history)
    value = clean_info_fifo(description_visible(visible, record, summary))
    if "FIFO_SPLITS=" in visible:
        token=visible.split("FIFO_SPLITS=",1)[1].split(";",1)[0].split("|",1)[0].strip().split()
        if token and all(v.isdigit() for v in token[0].split(",")):
            head,sep,tail=value.partition(" | BADFIFO=")
            value=head+"; FIFO_SPLITS="+token[0]+sep+tail
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
    # Y = pret gresit SAU sold CXCURBAL gresit/lipsa/negativ. INITIAL valid = N.
    row=record["row"]
    bal=row.get("balance")
    neg_sold=bal is not None and bal < -QTY_TOLERANCE
    sold_bad=bool(record.get("balance_bad") or record.get("balance_missing") or neg_sold)
    if ordinary_entry(row):
        return "Y" if sold_bad else None
    if row.get("kind")=="INITIAL":
        if sold_bad:
            return "Y"
        return "N" if record["status"]=="INITIAL" else "U"
    if record["status"]=="N/A":
        return "Y" if sold_bad else "NA"
    if sold_bad:
        return "Y"
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

def put_back(layers,qty,cost,priority,source,source_ref,source_ref_mbo=None,initial=False):
    for layer in layers:
        if not far(layer["cost"],cost,COST_TOLERANCE) and layer.get("priority")==priority:
            layer["qty"]+=qty
            return
    layers.append({"qty":qty,"cost":cost,"source":source,"source_ref_id":source_ref,
                   "source_ref_mbo":source_ref_mbo,"initial":initial,"priority":priority})
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

def shipcancel_target(row,group_rows,records):
    # SHIPCANCEL restabileste un SHIPTRANSFER: RECEIPTREF sau match cantitate/pret.
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
        return None,"SHIPCANCEL fara SHIPTRANSFER unic anterior (RECEIPTREF/cantitate/pret)",None,None,None
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


def receipt_audit_rows(inventory,rows):
    from psdi.server import MXServer
    opened=[]
    def query(name,where):
        ms=MXServer.getMXServer().getMboSet(name,inventory.getUserInfo())
        opened.append(ms)
        ms.setFlag(__import__("psdi.mbo",fromlist=["MboConstants"]).MboConstants.NOSAVE,True)
        ms.setWhere(where)
        ms.reset()
        found=[]
        m=ms.moveFirst()
        while m is not None:
            found.append(m)
            if len(found)>MAX_ROWS:
                raise ValueError("Limita surse audit depasita")
            m=ms.moveNext()
        return ms,found
    try:
        normalized=[]
        for row in rows:
            r=dict(row)
            r["ref"]=r.get("ref_id")
            r["refmbo"]=r.get("ref_mbo")
            r["item"],r["site"],r["location"]=(inventory.getString(f) for f in ("ITEMNUM","SITEID","LOCATION"))
            normalized.append(r)
        cx_enrich_receipts(normalized,query)
        by_id=dict((r["id"],r) for r in normalized)
        for row in rows:
            for key in ("receipt","issue_id"):
                if key in by_id[row["id"]]:
                    row[key]=by_id[row["id"]][key]
        return cx_receipt_balances(normalized,ZERO)
    finally:
        for ms in reversed(opened):
            close_set(ms)

def apply_receipt_audit(audit,rows,balances,keys,errors):
    last={}
    for row in sorted(rows,key=order):
        rec=audit["records"][row["id"]]
        row["receipt_partition"]=keys[row["id"]]
        expected=balances[row["id"]]
        rec["balance_expected"]=expected
        rec["balance_bad"]=row.get("balance") is not None and far(row["balance"],expected,QTY_TOLERANCE)
        if row.get("ref_mbo")=="MATUSETRANS" and row.get("kind") in ("ISSUE","RETURN") and rec.get("allocations"):
            sources=set(None if a.get("initial") else (a.get("source_ref_id") if a.get("source_ref_mbo")=="MATRECTRANS" else None) for a in rec["allocations"])
            if len(sources)!=1 or row.get("receipt") not in sources:
                rec["source_bad"]=True
                rec["status"]="BAD"
                rec["reason"]="Split pe receptii necesar" if len(sources)!=1 else "MATRECTRANSID nu corespunde sursei FIFO"
        if row["id"] in errors:
            rec["status"]="UNVERIFIED"
            rec["reason"]=errors[row["id"]]
        last[keys[row["id"]]]=expected
    audit["ledger_qty"]=sum(last.values(),ZERO)
    audit["receipt_keys"]=keys
    audit["receipt_errors"]=errors


def audit_rows(rows):
    records=dict((r["id"],new_local_record(r)) for r in rows)
    if len(records)!=len(rows):
        raise ValueError("CXSTOCURIID duplicat")
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
                # Mai multe INITIAL in aceeasi data cu preturi diferite = straturi de deschidere OK.
                # Ambiguu doar: dupa miscari, pret/sold invalid, sau acelasi pret duplicat.
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
                expected,link_ref,source_ref,priority,source=return_target(row,group_rows,records)
                if expected is None:
                    rec["reason"]=link_ref
                    continue
                issue_row=next(r for r in group_rows if r.get("ref_mbo")=="MATUSETRANS" and r.get("ref_id")==link_ref and r.get("kind")=="ISSUE")
                origin_rec=records[issue_row["id"]]
                if "returnable" not in origin_rec:
                    origin_rec["returnable"]=[dict(a) for a in origin_rec.get("allocations") or []]
                pool=origin_rec["returnable"]
                if sum((a["qty"] for a in pool),ZERO)+QTY_TOLERANCE<qty:
                    rec["reason"]="Retururi cumulate peste consum sau alocare originala indisponibila"
                    structural=rec["reason"]
                    continue
                restored=[]
                left=qty
                for a in reversed(pool):
                    take=min(left,a["qty"])
                    if take>QTY_TOLERANCE:
                        b=dict(a)
                        b["qty"]=take
                        restored.append(b)
                        a["qty"]-=take
                        left-=take
                        put_back(layers,take,a["cost"],a["priority"],a.get("source"),a.get("source_ref_id"),a.get("source_ref_mbo"),a.get("initial",False))
                    if left<=QTY_TOLERANCE:
                        break
                expected=sum((a["qty"]*a["cost"] for a in restored),ZERO)/qty
                rec["expected"]=expected
                rec["link_ref"]=link_ref
                rec["allocations"]=restored
                rec["status"]="BAD" if far(cost,expected,COST_TOLERANCE) else "OK"
                local_prices.add(expected)
                local_started=True
                continue
            if kind=="SHIPCANCEL":
                if qty<=QTY_TOLERANCE:
                    rec["reason"]="SHIPCANCEL fara cantitate pozitiva"
                    continue
                expected,link_ref,source_ref,priority,source=shipcancel_target(row,group_rows,records)
                if expected is None:
                    rec["reason"]=link_ref
                    continue
                issue_row=next(r for r in group_rows if r.get("ref_mbo")=="MATRECTRANS" and r.get("ref_id")==link_ref and r.get("kind")=="SHIPTRANSFER")
                origin_rec=records[issue_row["id"]]
                if "returnable" not in origin_rec:
                    origin_rec["returnable"]=[dict(a) for a in origin_rec.get("allocations") or []]
                pool=origin_rec["returnable"]
                if sum((a["qty"] for a in pool),ZERO)+QTY_TOLERANCE<qty:
                    rec["reason"]="Anulari cumulate peste expediere sau alocare originala indisponibila"
                    structural=rec["reason"]
                    continue
                restored=[]
                left=qty
                for a in reversed(pool):
                    take=min(left,a["qty"])
                    if take>QTY_TOLERANCE:
                        b=dict(a)
                        b["qty"]=take
                        restored.append(b)
                        a["qty"]-=take
                        left-=take
                        put_back(layers,take,a["cost"],a["priority"],a.get("source"),a.get("source_ref_id"),a.get("source_ref_mbo"),a.get("initial",False))
                    if left<=QTY_TOLERANCE:
                        break
                expected=sum((a["qty"]*a["cost"] for a in restored),ZERO)/qty
                rec["expected"]=expected
                rec["link_ref"]=link_ref
                rec["allocations"]=restored
                rec["status"]="BAD" if far(cost,expected,COST_TOLERANCE) else "OK"
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
                # Doar acest rand; nu infecteaza structural restul grupei.
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
                    known=sum((l["qty"] for l in layers if l["cost"]==cost and l.get("source_ref_id")==row.get("ref_id") and l.get("source_ref_mbo")==row.get("ref_mbo")),ZERO)
                    available=min(qty,max(ZERO,balance-known))
                local_prices.add(cost)
                local_started=True
                if available>QTY_TOLERANCE:
                    layers.append({"qty":available,"cost":cost,"source":row["id"],
                                   "source_ref_id":row.get("ref_id"),"source_ref_mbo":row.get("ref_mbo"),
                                   "initial":False,"priority":order(row)})
                    layers.sort(key=lambda l:l["priority"])
                rec["status"]="INPUT"
                continue
            # qty < 0: iesire FIFO. Include RECEIPT/SHIPRECEIPT negative (comenzi/receptii).
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
    body = [p for p in parts[:-1] if not p.startswith("SPLIT LIPSA:")]
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
    if value.startswith("FROMSTORELOC="):
        parts = value.split(" | ")
        if len(parts) == 1:
            return bool(value[len("FROMSTORELOC="):].strip())
        return parts[-1] in ("BADFIFO=Y", "BADFIFO=N", "BADFIFO=U", "BADFIFO=NA") and bool(
            parts[0][len("FROMSTORELOC="):].strip())
    def initial_qty_cost_ok(body):
        parts_ic = body.split(" buc. la ")
        if len(parts_ic) != 2:
            return False
        for part in parts_ic:
            if part == "necunoscut":
                continue
            try:
                number = dec(part.replace(",", "."))
                if number is None or fmt_ro(number) != part:
                    return False
            except Exception:
                return False
        return True
    prefix = "INITIAL: FIFO LOCAL "
    if value.startswith(prefix) and " | " not in value:
        return initial_qty_cost_ok(value[len(prefix):])
    parts = value.split(" | ")
    if parts and parts[-1] in ("BADFIFO=Y", "BADFIFO=N", "BADFIFO=U", "BADFIFO=NA"):
        core = " | ".join(parts[:-1])
        if core.startswith(prefix) and " | ATENTIE SOLD:" not in core:
            return initial_qty_cost_ok(core[len(prefix):])
        if core.startswith(prefix) and " | ATENTIE SOLD:" in core:
            head = core.split(" | ATENTIE SOLD:")[0]
            return initial_qty_cost_ok(head[len(prefix):]) and parts[-1] == "BADFIFO=Y"
        if core == "INITIAL: BAZA NECONCLUDENTA; vezi rezumatul auditului":
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
        info="FROMSTORELOC="+(txt(row.get("from_location")).strip() or "NEIDENTIFICAT")
        if record.get("balance_missing"):
            info+=" | ATENTIE SOLD: CXCURBAL lipsa | BADFIFO=Y"
        elif record["balance_bad"]:
            info+=" | ATENTIE SOLD: inregistrat %s; calculat %s | BADFIFO=Y" % (
                fmt_ro(row.get("balance")),fmt_ro(record["balance_expected"]))
        return info
    if row.get("kind")=="INITIAL":
        if record["status"]!="INITIAL":
            return "INITIAL: BAZA NECONCLUDENTA; vezi rezumatul auditului | BADFIFO=U"
        info="INITIAL: FIFO LOCAL %s buc. la %s" % (fmt_ro(row.get("balance")),fmt_ro(row.get("cost")))
        if record.get("balance_missing"):
            return info+" | ATENTIE SOLD: CXCURBAL lipsa | BADFIFO=Y"
        if record["balance_bad"]:
            return info+" | ATENTIE SOLD: inregistrat %s; calculat %s | BADFIFO=Y" % (
                fmt_ro(row.get("balance")),fmt_ro(record["balance_expected"]))
        return info+" | BADFIFO=N"
    status=record["status"]
    if record.get("source_bad"):
        info="DIFERENTA: "+record["reason"]
    elif status=="DATE_ORDER":
        info="OK: pret compatibil %s; intrare ulterioara cu RefID anterior; data iesirii de verificat (conventie)" % fmt_ro(record["expected"])
    elif status=="OK" and row.get("kind") in VOID_TYPES:
        info="OK: %s anuleaza %s buc. la %s" % (row.get("kind"),fmt_ro(-row["qty"]),fmt_ro(record["expected"]))
    elif status=="OK" and row.get("kind")=="SHIPCANCEL":
        info="OK: SHIPCANCEL restabileste %s buc. la %s" % (fmt_ro(row["qty"]),fmt_ro(record["expected"]))
    elif status=="OK":
        info="OK: FIFO LOCAL asteptat %s" % fmt_ro(record["expected"])
    elif status=="BAD" and row.get("kind")=="SHIPCANCEL":
        info="DIFERENTA: SHIPCANCEL pret %s; asteptat %s; diferenta %s" % (
            fmt_ro(row["cost"]),fmt_ro(record["expected"]),fmt_ro(row["cost"]-record["expected"]))
    elif status=="BAD":
        info="DIFERENTA: FIFO LOCAL pret %s; asteptat %s; diferenta %s" % (
            fmt_ro(row["cost"]),fmt_ro(record["expected"]),fmt_ro(row["cost"]-record["expected"]))
    elif status=="N/A":
        info="FARA MISCARE: cantitate zero"
    else:
        info="NEVERIFICAT: "+record["reason"]
    if record.get("link_ref") is not None and status in ("OK","BAD"):
        if row.get("kind")=="SHIPCANCEL":
            info+="; expediere %s" % record["link_ref"]
        else:
            info+="; consum %s" % record["link_ref"]
    if record.get("local_basis") and status in ("OK","BAD"):
        info+="; baza locala din intrari"
    if record.get("resumed"):
        info+="; audit reluat pe aceasta iesire"
    if record.get("balance_missing"):
        info+="; ATENTIE SOLD: CXCURBAL lipsa"
    elif row.get("balance") is not None and row["balance"] < -QTY_TOLERANCE:
        info+="; ATENTIE SOLD: negativ %s" % fmt_ro(row.get("balance"))
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

def open_invlifofifocost(inventory):
    # Set copil pe INVENTORY: CXINVLFIFO asteapta mbo.getOwner(); setul MXServer e fara owner.
    ms=inventory.getMboSet("INVLIFOFIFOCOST")
    if ms is None:
        raise ValueError("Relatia INVENTORY.INVLIFOFIFOCOST lipseste")
    ms.reset()
    return ms

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

def enrich_shipcancels(inventory,rows,script_service):
    from psdi.server import MXServer
    pending=sorted(set(r["ref_id"] for r in rows if r.get("kind")=="SHIPCANCEL" and r.get("ref_mbo")=="MATRECTRANS" and r.get("ref_id") is not None))
    links={}
    for start in range(0,len(pending),500):
        ms=None
        try:
            ms=MXServer.getMXServer().getMboSet("MATRECTRANS",inventory.getUserInfo())
            ms.setWhere("MATRECTRANSID IN (%s)" % ",".join(txt(i) for i in pending[start:start+500]))
            ms.reset()
            m=ms.moveFirst()
            while m is not None:
                links[m.getLong("MATRECTRANSID")]=None if m.isNull("RECEIPTREF") else m.getLong("RECEIPTREF")
                m=ms.moveNext()
        except Exception as exc:
            script_service.log_info("CXINVAUDIT legatura SHIPCANCEL indisponibila: "+txt(exc))
        finally:
            close_set(ms)
    for row in rows:
        if row.get("kind")=="SHIPCANCEL" and row.get("ref_mbo")=="MATRECTRANS":
            row["receipt_ref"]=links.get(row.get("ref_id"))

def journal_fifo_complete(audit):
    # True doar fara BADFIFO=Y/U pe pret/sold si fara ORDINE_DATE/neverificat.
    if audit.get("split_gaps"):
        return False,"Split incomplet sau verificarea spliturilor indisponibila"
    if audit.get("receipt_errors"):
        return False,"Provenienta pe receptie incompleta"
    if audit.get("issues"):
        return False,"Istoric incomplet: "+"; ".join(audit["issues"][:3])
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
        if f=="U" and (is_outgoing(row) or row.get("kind") in ("RETURN","SHIPCANCEL")):
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
    complete,reason=journal_fifo_complete(audit)
    if not complete and verdict=="OK":
        verdict="NECONCLUDENT: "+reason
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

def sync_official_stock(inventory,rows,audit,script_service):
    from psdi.server import MXServer
    from psdi.mbo import MboConstants,SqlFormat
    flags=MboConstants.NOACCESSCHECK | MboConstants.NOVALIDATION_AND_NOACTION
    ok,reason=journal_fifo_complete(audit)
    if not ok:
        return "RECONCILIERE STOC: sarita ("+reason+")"
    desired=desired_fifo_layers(rows,audit)
    target=sum((l["qty"] for l in desired),ZERO)
    if far(target,audit["ledger_qty"],QTY_TOLERANCE) or target<ZERO:
        return "RECONCILIERE STOC: sarita; straturile si soldul jurnalului nu concorda"
    opened=[]
    tx=None
    committed=False
    commit_started=False
    try:
        # Fresh INVENTORY owner: existing CXINVLFIFO automation requires an owner.
        invset=open_scope(inventory,"INVENTORY",True)
        opened.append(invset)
        inv=invset.getMbo(0)
        if inv is None or invset.getMbo(1) is not None or inv.getString("COSTTYPE")!="FIFO":
            raise ValueError("Inventory FIFO neidentificat unic")
        itemset=inv.getString("ITEMSETID")
        itemset_mbos=MXServer.getMXServer().getMboSet("ITEM",inventory.getUserInfo())
        opened.append(itemset_mbos)
        sql=SqlFormat("ITEMNUM=:1 AND ITEMSETID=:2")
        sql.setObject(1,"ITEM","ITEMNUM",inventory.getString("ITEMNUM"))
        sql.setObject(2,"ITEM","ITEMSETID",itemset)
        itemset_mbos.setWhere(sql.format())
        itemset_mbos.reset()
        item=itemset_mbos.getMbo(0)
        if item is None or itemset_mbos.getMbo(1) is not None or item.getBoolean("ROTATING") or item.getBoolean("CONDITIONENABLED") or item.getString("LOTTYPE")!="NOLOT":
            raise ValueError("Reconciliere automata doar non-rotating, NOLOT, fara condition code")
        balset=open_scope(inv,"INVBALANCES",True)
        opened.append(balset)
        balance_rows=[]
        m=balset.moveFirst()
        while m is not None:
            qty=numeric_field(m,"CURBAL")
            if qty is None or qty<-QTY_TOLERANCE:
                raise ValueError("Sold oficial lipsa/negativ; necesita reconciliere explicita")
            balance_rows.append((m,qty))
            if len(balance_rows)>MAX_ROWS:
                raise ValueError("Limita INVBALANCES depasita")
            m=balset.moveNext()
        if len(balance_rows)!=1:
            raise ValueError("Mai multe cosuri/loturi: repartizarea soldului nu este determinabila")
        target_mbo,old_qty=balance_rows[0]
        costset=open_invlifofifocost(inv)
        current=[]
        m=costset.moveFirst()
        while m is not None:
            cost,qty=numeric_field(m,"UNITCOST"),numeric_field(m,"QUANTITY")
            if cost is None or qty is None or cost<ZERO or qty<ZERO:
                raise ValueError("Strat oficial lipsa/negativ")
            current.append({"id":m.getLong("INVLIFOFIFOCOSTID"),"cost":cost,"qty":qty,
                "ref_mbo":None if m.isNull("REFOBJECT") else m.getString("REFOBJECT"),
                "ref_id":None if m.isNull("REFOBJECTID") else m.getLong("REFOBJECTID"),"mbo":m,
                "date":None if m.isNull("COSTDATE") else date_key(m.getDate("COSTDATE"))})
            if len(current)>MAX_ROWS:
                raise ValueError("Limita de straturi depasita")
            m=costset.moveNext()
        keeps,updates,deletes,creates=plan_invlifo_alignment(desired,current)
        if creates:
            return "RECONCILIERE STOC: sarita integral; nu exista suficiente randuri reutilizabile.\n"+format_missing_invlifo_creates(creates)
        if not updates and not deletes and not far(old_qty,target,QTY_TOLERANCE):
            return "RECONCILIERE STOC: deja aliniat; cantitate %s; diferente cantitate/valoare zero" % fmt_ro(target)
        # Recheck the audited snapshot immediately before preparing writes.
        check=open_scope(inv,"CXSTOCURI")
        opened.append(check)
        fresh,unused=read_journal(check)
        if snapshot(fresh)!=snapshot(rows):
            raise ValueError("Jurnal schimbat dupa audit; reruleaza Check FIFO")
        if far(old_qty,target,QTY_TOLERANCE):
            put_invlifo_number(target_mbo,"CURBAL",target)
        for change in updates:
            apply_invlifo_layer(change["row"]["mbo"],change["layer"],flags,script_service)
        for row in deletes:
            row["mbo"].delete(flags)
        tx=MXServer.getMXServer().createMXTransaction()
        for ms in (invset,balset,costset):
            ms.setMXTransaction(tx)
            tx.add(ms)
        tx.save()
        if numeric_field(target_mbo,"CURBAL")!=target:
            raise ValueError("CURBAL suprascris la save")
        for change in updates:
            m,layer=change["row"]["mbo"],change["layer"]
            if numeric_field(m,"QUANTITY")!=layer["qty"] or numeric_field(m,"UNITCOST")!=layer["cost"]:
                raise ValueError("Strat suprascris la save")
            if not same_ref(None if m.isNull("REFOBJECT") else m.getString("REFOBJECT"),None if m.isNull("REFOBJECTID") else m.getLong("REFOBJECTID"),layer.get("ref_mbo"),layer.get("ref_id")):
                raise ValueError("Provenienta stratului suprascrisa la save")
            expected_date=parse_layer_date(layer.get("date"))
            if expected_date is not None and (m.isNull("COSTDATE") or m.getDate("COSTDATE").getTime()!=expected_date.getTime()):
                raise ValueError("COSTDATE nu corespunde provenientei; randul nu poate fi reutilizat in siguranta")
        if any(not row["mbo"].toBeDeleted() for row in deletes):
            raise ValueError("Stergere strat anulata la save")
        commit_started=True
        tx.commit()
        committed=True
        return "RECONCILIERE STOC SALVATA ATOMIC: CURBAL %s -> %s; straturi pastrate %s, actualizate %s, sterse %s. Fara Save suplimentar." % (fmt_ro(old_qty),fmt_ro(target),len(keeps),len(updates),len(deletes))
    except Exception as exc:
        if not committed:
            cx_rollback(tx)
        state="COMMIT INCERT; reciteste inainte de repetare" if commit_started and not committed else ("SALVAT, eroare ulterioara" if committed else "OPRITA / ROLLBACK")
        return "RECONCILIERE STOC %s: %s" % (state,txt(exc))
    finally:
        for ms in reversed(opened):
            close_set(ms)

def price_label(value):
    rounded=fmt(value)
    return (rounded if dec(rounded)==value else txt(value)).replace(".",",")

def recorded_balances_by_cost(rows):
    last={}
    for row in sorted(rows,key=order):
        if row.get("cost") is None or not row.get("date"):
            raise ValueError("Pret/data lipsa; sold final nedeterminabil")
        last[(row.get("group") or "",row["cost"],row.get("receipt_partition",(None,None,None,row.get("receipt")))[2:])]=row
    totals={}
    for key,row in last.items():
        if row.get("balance") is None:
            raise ValueError("Sold final lipsa")
        totals[key[1]]=totals.get(key[1],ZERO)+row["balance"]
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
    # 1) match pe pret+REFOBJECT+REFOBJECTID
    # 2) pentru straturi fara match: reutilizeaza surplus (nu create); restul surplus = delete
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
        same_date="date" not in chosen or layer.get("date") is None or chosen.get("date")==layer.get("date")
        if same_qty and same_date:
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
    # Actualizeaza randul existent la stratul CXSTOCURI (fara insert).
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
    # String + locale RO: "30.745" poate deveni 30745. MaxType US pastreaza zecimalul.
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



def invlifo_totals(inventory,rows,script_service):
    # TOTALURI ca in reconcilierea veche: cantitate/valoare CXSTOCURI vs INVLIFOFIFOCOST.
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



def fetch_rows(inventory, name, where, spec):
    from psdi.server import MXServer
    ms=MXServer.getMXServer().getMboSet(name, inventory.getUserInfo())
    try:
        ms.setWhere(where)
        ms.reset()
        out=[]
        m=ms.moveFirst()
        while m is not None:
            if len(out)>=MAX_ROWS:
                break
            row={}
            for field, kind in spec:
                if m.isNull(field):
                    row[field]=None
                elif kind=="L":
                    row[field]=m.getLong(field)
                else:
                    row[field]=numeric_field(m, field)
            out.append(row)
            m=ms.moveNext()
        return out
    finally:
        close_set(ms)

def in_chunks(ids, size=300):
    ids=list(ids)
    start=0
    while start<len(ids):
        yield ids[start:start+size]
        start+=size

def split_gap_by_matusetrans(inventory, rows, script_service):
    # Pe fiecare linie cu split incomplet: nota scurta pentru randurile CXSTOCURI ale liniei.
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
        return {"AUDIT_ERROR":"Verificarea spliturilor indisponibila: "+txt(exc)}

def run_local(inventory,script_service):
    from psdi.mbo import MboConstants
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
        enrich_shipcancels(inventory,rows,script_service)
        receipt_balances,receipt_keys,receipt_errors=receipt_audit_rows(inventory,rows)
        audit=audit_rows(rows)
        apply_receipt_audit(audit,rows,receipt_balances,receipt_keys,receipt_errors)
        gap_notes=split_gap_by_matusetrans(inventory,rows,script_service)
        audit["split_gaps"]=gap_notes
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
            for r in rows:
                r["rowstamp"]=txt(mbos[r["id"]].getRowStamp())
                r["old_description"]=mbos[r["id"]].getString("DESCRIPTION_LONGDESCRIPTION")
        message=local_summary(audit,unknown)
        layers_text,layers_total=fifo_layers_situation(rows,audit,script_service)
        message+="\n\n"+layers_text
        official_message=sync_official_stock(inventory,rows,audit,script_service)
        message+="\n\n"+official_message
        if not (official_message.startswith("RECONCILIERE STOC: deja aliniat") or official_message.startswith("RECONCILIERE STOC SALVATA ATOMIC")):
            message="VERDICT GLOBAL: NECONCLUDENT (reconciliere nefinalizata)\n\n"+message
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

if "mbo" in globals() and "service" in globals():
    try:
        result=run_local(mbo,service)
    except ValueError as exc:
        result="Audit local oprit: "+txt(exc)
    service.error("CXCHECKFIFO","RESULT",[result])