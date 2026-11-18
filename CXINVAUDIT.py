# SCRIPT: CXINVAUDIT
# AUTOR: Cristian Grosu
# VERSIUNE: 5.36-RETURN-AFTER-ISSUE
# Partea 1 (launch). def run_local este in CXINVAUDITEXEC (BMXAA7836E Mark invalid).
# INVLIFO ROTATING=0: MBO update/delete. ROTATING=1: SQL dupa BADFIFO curat + CURBAL.
# Same-day: iesiri inaintea intrarilor din aceeasi zi (inclusiv same-second) =>
# SQL +1/+2.. min dupa max(intrari), apoi CXCURBAL (inainte de Info FIFO).
# Necesita CXINVAUDITEXEC.

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

VERSION = "5.36-RETURN-AFTER-ISSUE"
FIFO_TABLE_ID = "1792055730066"
MAX_ROWS = 5000
MAX_DESCRIPTION = 32000
MAX_LAYER_LINES = 30
FIX_PREFIX = "CXFIFO_FIX1|"
BEGIN = "CXFIFO_AUDIT_V2_BEGIN"
END = "CXFIFO_AUDIT_V2_END"
HEADER = "FIFO V2 | "
ZERO = ExactNumber("0")
ONE = ExactNumber("1")
COST_TOLERANCE = ExactNumber("0.0005")
QTY_TOLERANCE = ExactNumber("0.000001")
ENTRY_TYPES = ("RECEIPT", "SHIPRECEIPT", "TRANSFER")
EXIT_TYPES = ("ISSUE", "SHIPTRANSFER", "TRANSFER")
VOID_TYPES = ("VOIDRECEIPT", "SHIPRETURN")
AMBIGUOUS_TYPES = ("VOIDSHIPRECEIPT", "RECBALADJ")
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

def normalize_fifo_groups(rows):
    for row in rows:
        row["group"]=""
    return rows

def flag(record):
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

def peel_pu_trace(text):
    traces = []
    body = []
    for line in txt(text).split("\n"):
        if line.strip().startswith("PU-RECEPTIE:"):
            traces.append(line.strip())
        else:
            body.append(line)
    return "\n".join(body).strip(), traces

def with_pu_trace(value, traces):
    if not traces:
        return value
    combined = value + "\n" + "\n".join(traces)
    if len(combined) > MAX_DESCRIPTION:
        return value
    return combined

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
    kept, traces = peel_pu_trace(kept)
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
        return with_pu_trace(info, traces)
    if row.get("kind")=="INITIAL":
        if record["status"]!="INITIAL":
            return with_pu_trace("INITIAL: BAZA NECONCLUDENTA; vezi rezumatul auditului | BADFIFO=U", traces)
        info="INITIAL: FIFO LOCAL %s buc. la %s" % (fmt_ro(row.get("balance")),fmt_ro(row.get("cost")))
        if record.get("balance_missing"):
            return with_pu_trace(info+" | ATENTIE SOLD: CXCURBAL lipsa | BADFIFO=Y", traces)
        if record["balance_bad"]:
            return with_pu_trace(info+" | ATENTIE SOLD: inregistrat %s; calculat %s | BADFIFO=Y" % (
                fmt_ro(row.get("balance")),fmt_ro(record["balance_expected"])), traces)
        return with_pu_trace(info+" | BADFIFO=N", traces)
    status=record["status"]
    if status=="DATE_ORDER":
        info="OK: pret compatibil %s; intrare ulterioara cu RefID anterior; data iesirii de verificat (conventie)" % fmt_ro(record["expected"])
    elif status=="OK" and row.get("kind") in VOID_TYPES and row.get("qty") is not None and row["qty"]<-QTY_TOLERANCE:
        info="OK: %s anuleaza %s buc. la %s" % (row.get("kind"),fmt_ro(-row["qty"]),fmt_ro(record["expected"]))
    elif status=="OK" and is_ship_restore(row):
        info="OK: %s restabileste %s buc. la %s" % (row.get("kind"),fmt_ro(row["qty"]),fmt_ro(record["expected"]))
    elif status=="OK":
        info="OK: FIFO LOCAL asteptat %s" % fmt_ro(record["expected"])
    elif status=="BAD" and is_ship_restore(row):
        info="DIFERENTA: %s pret %s; asteptat %s" % (
            row.get("kind"),fmt_ro(row["cost"]),fmt_ro(record["expected"]))
    elif status=="BAD":
        info="DIFERENTA: pret %s; asteptat %s" % (
            fmt_ro(row["cost"]),fmt_ro(record["expected"]))
    elif status=="N/A":
        info="FARA MISCARE: cantitate zero"
    else:
        info="NEVERIFICAT: "+record["reason"]
    if record.get("link_ref") is not None and status in ("OK","BAD"):
        if is_ship_restore(row):
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
    return with_pu_trace(value, traces)

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
             "date_ms":None if m.isNull("CXDOCUMENTDATE") else long(m.getDate("CXDOCUMENTDATE").getTime()),
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
    pending=sorted(set(r["ref_id"] for r in rows
                       if r.get("kind") in ("SHIPCANCEL","SHIPRETURN") and r.get("ref_mbo")=="MATRECTRANS"
                       and r.get("ref_id") is not None))
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
            script_service.log_info("CXINVAUDIT legatura SHIPCANCEL/SHIPRETURN indisponibila: "+txt(exc))
        finally:
            close_set(ms)
    for row in rows:
        if row.get("kind") in ("SHIPCANCEL","SHIPRETURN") and row.get("ref_mbo")=="MATRECTRANS":
            row["receipt_ref"]=links.get(row.get("ref_id"))

def price_label(value):
    rounded=fmt(value)
    return (rounded if dec(rounded)==value else txt(value)).replace(".",",")

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


EXEC_SCRIPT="CXINVAUDITEXEC"

def bind_run_local(user):
    from psdi.server import MXServer
    from psdi.mbo import SqlFormat
    ms=None
    try:
        ms=MXServer.getMXServer().getMboSet("AUTOSCRIPT",user)
        sql=SqlFormat("AUTOSCRIPT=:1")
        sql.setObject(1,"AUTOSCRIPT","AUTOSCRIPT",EXEC_SCRIPT)
        ms.setWhere(sql.format())
        ms.reset()
        m=ms.moveFirst()
        if m is None or ms.moveNext() is not None:
            raise ValueError("Lipseste %s. Script jython fara launch point, sub 100000 caractere." % EXEC_SCRIPT)
        src=m.getString("SOURCE")
        if src is None or "def run_local(" not in src:
            raise ValueError("%s nu defineste run_local" % EXEC_SCRIPT)
        ns=bind_run_local.func_globals
        try:
            exec src in ns
        except:
            raise ValueError("%s nu se compileaza: %s" % (EXEC_SCRIPT, txt(__import__("sys").exc_info()[1])))
        if not callable(ns.get("run_local")):
            raise ValueError("%s nu a definit run_local" % EXEC_SCRIPT)
    finally:
        close_set(ms)

if "mbo" in globals() and "service" in globals():
    try:
        bind_run_local(mbo.getUserInfo())
        result=bind_run_local.func_globals["run_local"](mbo,service)
    except ValueError as exc:
        result="Audit local oprit: "+txt(exc)
    except:
        result="Audit local oprit: "+txt(__import__("sys").exc_info()[1])
    service.error("CXCHECKFIFO","RESULT",[result])
