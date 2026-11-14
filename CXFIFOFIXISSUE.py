# SCRIPT: CXFIFOFIXISSUE
# AUTOR: Cristian Grosu
# VERSIUNE: 3.46-JOURNAL-SPLIT
# Partea 1. def execute este in CXFIFOFIXEXEC (limita Jython 100000 caractere).
# RECEIPT multi-pret: split doar in CXSTOCURI. MATRECTRANS isi pastreaza cantitatea.
# Necesita CXFIFOFIXEXEC si protectia CXADDTOCXSTOCURI.

from java.math import BigDecimal, MathContext, RoundingMode
from java.text import NumberFormat, ParsePosition
from java.util import Locale, TimeZone
from psdi.server import MXServer
from psdi.mbo import MboConstants, SqlFormat
from psdi.util import MaxType
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

VERSION="3.46-JOURNAL-SPLIT"
APP="INVENTOR"
OPTION="CXFIFOFIXISSUE"
TABLE_ID="1792055730066"
MESSAGE_GROUP="CXFIFO"
MESSAGE_KEY="FIXISSUERESULT"
MAX_ROWS=5000
MAX_SPLITS=50
CASCADE_MAX_ISSUES=15
ZERO=ExactNumber("0")
ONE=ExactNumber("1")
STEP=ExactNumber("0.001")
EPS=ExactNumber("0.000001")
PRICE_EPS=ExactNumber("0.0005")
FLAGS=MboConstants.NOACCESSCHECK | MboConstants.NOVALIDATION_AND_NOACTION
ENTRIES=("RECEIPT","SHIPRECEIPT","TRANSFER")
# RECEIPT/SHIPRECEIPT apar si la iesiri (qty<0), ca in CXINVAUDIT.
EXITS=("ISSUE","SHIPTRANSFER","TRANSFER","RECEIPT","SHIPRECEIPT")
VOID_TYPES=("VOIDRECEIPT","SHIPRETURN")
MATREC_TRANSFER_EXITS=("SHIPTRANSFER","TRANSFER")
MATREC_RECEIPT_EXITS=("RECEIPT","SHIPRECEIPT")
MATREC_EXITS=MATREC_TRANSFER_EXITS+MATREC_RECEIPT_EXITS
WRITE_TABLES=("INVUSELINESPLIT","MATUSETRANS","MATRECTRANS","CXSTOCURI")
SPLIT_COPY=("INVUSENUM","ORGID","SITEID","INVUSELINEID","FROMLOT","ROTASSETNUM","FROMBIN",
            "PHYSCNT","PHYSCNTDATE","SENDERSYSID","INVUSELINENUM","ITEMNUM","ITEMSETID",
            "FROMSTORELOC","FROMCONDITIONCODE","STAGINGBIN","STAGINGLOT","PLSTATE","RETURNBIN","RETURNQTY")
MATUSE_COPY=("ITEMNUM","STORELOC","ACTUALDATE","PHYSCNT","PONUM","CONVERSION","ASSETNUM",
             "IT1","IT2","IT3","IT4","IT5","MEMO","OUTSIDE","ISSUETO","PACKINGSLIPNUM","POLINENUM",
             "ROLLUP","ITIN1","ITIN2","ITIN3","BINNUM","LOTNUM","ISSUETYPE","GLDEBITACCT","GLCREDITACCT",
             "FINANCIALPERIOD","CURRENCYCODE","ROTASSETNUM","LOCATION","DESCRIPTION","EXCHANGERATE",
             "SPAREPARTADDED","EXCHANGERATE2","MRNUM","MRLINENUM","IT6","IT7","IT8","IT9","IT10",
             "ITIN4","ITIN5","ITIN6","ITIN7","ORGID","SITEID","REFWO","ENTEREDASTASK","LINETYPE",
             "ITEMSETID","CONDITIONCODE","CONDRATE","COMMODITYGROUP","COMMODITY","TOSITEID","LANGCODE",
             "POREVISIONNUM","INVUSELINEID","INVUSEID","CONSIGNMENT","ISSUEUNIT","WPITEMID","INVPICKLISTID")
MATREC_COPY=("ITEMNUM","ITEMSETID","ORGID","SITEID","FROMSITEID","FROMSTORELOC","TOSTORELOC","ISSUETYPE",
             "PONUM","POLINENUM","POREVISIONNUM","CURRENCYCODE","CONVERSION","EXCHANGERATE","EXCHANGERATE2",
             "GLDEBITACCT","GLCREDITACCT","DESCRIPTION","COMMODITYGROUP","COMMODITY","LINETYPE","ENTERBY",
             "STATUS","RECEIPTREF","ISSUEUNIT")

class FixError(Exception):
    pass

def fail(message):
    raise FixError(message)

def text(value):
    return "" if value is None else string_type(value)

def fmt(value):
    return ExactNumber(value).fixed(3)

def money(value):
    return ExactNumber(ExactNumber(value).value.setScale(3,RoundingMode.HALF_EVEN))

def different(a,b,tolerance=EPS):
    return a is None or b is None or abs(a-b)>tolerance

def number(m,field,nullable=False):
    if m.isNull(field):
        if nullable:
            return None
        fail("Camp lipsa %s.%s" % (m.getName(),field))
    raw=m.getMboValue(field).getCurrentValue().asString().strip()
    try:
        return ExactNumber(raw)
    except Exception:
        parser=NumberFormat.getNumberInstance(m.getUserInfo().getLocale())
        parser.setParseBigDecimal(True)
        pos=ParsePosition(0)
        value=parser.parse(raw,pos)
        if value is None or pos.getIndex()!=len(raw):
            fail("Numar neinterpretabil %s.%s=%s" % (m.getName(),field,raw))
        return ExactNumber(value)

def put_number(m,field,value):
    old=number(m,field,True)
    if old is not None and old==value:
        return
    mv=m.getMboValue(field)
    typed=MaxType.createMaxType(Locale.US,TimeZone.getTimeZone("UTC"),mv.getType())
    typed.setScale(mv.getScale())
    typed.setValue(text(value))
    if ExactNumber(typed.asString())!=value:
        fail("Precizia %s.%s nu pastreaza %s" % (m.getName(),field,text(value)))
    m.setValue(field,typed,FLAGS)
    if number(m,field)!=value:
        fail("Valoare schimbata la setare: "+field)

def datekey(value):
    if value is None:
        return ""
    from java.text import SimpleDateFormat
    f=SimpleDateFormat("yyyy-MM-dd HH:mm:ss")
    f.setTimeZone(TimeZone.getTimeZone("UTC"))
    nanos=value.getNanos() if hasattr(value,"getNanos") else (value.getTime()%1000)*1000000
    return f.format(value)+".%09d" % nanos

def close(ms):
    if ms is not None:
        try:
            ms.cleanup()
        finally:
            ms.close()

def readrows(ms,limit=MAX_ROWS):
    result=[]
    m=ms.moveFirst()
    while m is not None:
        result.append(m)
        if len(result)>limit:
            fail("Limita de volum depasita")
        m=ms.moveNext()
    return result

def open_readonly(user,name,where):
    ms=MXServer.getMXServer().getMboSet(name,user)
    try:
        ms.setFlag(MboConstants.NOSAVE,True)
        ms.setWhere(where)
        ms.reset()
        return ms
    except Exception:
        close(ms)
        raise

def scope_where(context,name,itemset=None):
    fields=[("ITEMNUM",context.getString("ITEMNUM")),("SITEID",context.getString("SITEID")),("LOCATION",context.getString("LOCATION"))]
    if itemset is not None:
        fields.append(("ITEMSETID",itemset))
    sql=SqlFormat(" AND ".join("%s=:%s" % (field,i+1) for i,(field,value) in enumerate(fields)))
    for i,(field,value) in enumerate(fields):
        sql.setObject(i+1,name,field,value)
    return sql.format()

def signature(ms):
    return sorted((m.getUniqueIDValue(),text(m.getRowStamp())) for m in readrows(ms))

def journal_row(m):
    return {"id":m.getLong("CXSTOCURIID"),"ref":None if m.isNull("CXREFID") else m.getLong("CXREFID"),
            "refmbo":m.getString("CXREFMBO"),"kind":m.getString("CXREF"),
            "date":datekey(None if m.isNull("CXDOCUMENTDATE") else m.getDate("CXDOCUMENTDATE")),
            "qty":number(m,"CXQTY",True),"cost":number(m,"UNITCOST"),"balance":number(m,"CXCURBAL",True),
            "group":"","mbo":m}

def order(row):
    return (row["date"],row["ref"] or 0,row["id"])

def consume(layers,required):
    allocations=[]
    for layer in layers:
        if required<=EPS:
            break
        take=min(required,layer["qty"])
        if take>ZERO:
            a=dict(layer)
            a["qty"]=take
            allocations.append(a)
            layer["qty"]-=take
            required-=take
    layers[:]=[l for l in layers if l["qty"]>EPS]
    return allocations,max(ZERO,required)

def consume_at_cost(layers,required,cost,newest_first=False):
    allocations=[]
    indexes=range(len(layers)-1,-1,-1) if newest_first else range(len(layers))
    for index in indexes:
        if required<=EPS:
            break
        layer=layers[index]
        if different(layer["cost"],cost,PRICE_EPS):
            continue
        take=min(required,layer["qty"])
        if take>ZERO:
            a=dict(layer)
            a["qty"]=take
            allocations.append(a)
            layer["qty"]-=take
            required-=take
    layers[:]=[l for l in layers if l["qty"]>EPS]
    return allocations,max(ZERO,required)

def issue_of_returns(rows,query):
    ids=sorted(set(r["ref"] for r in rows if r.get("kind")=="RETURN" and r.get("ref") is not None and r.get("qty") is not None and r["qty"]>ZERO))
    links={}
    for start in range(0,len(ids),500):
        chunk=ids[start:start+500]
        ms,found=query("MATUSETRANS","MATUSETRANSID IN (%s)" % ",".join(text(i) for i in chunk))
        if len(found)!=len(chunk):
            fail("Retur anterior lipsa in MATUSETRANS")
        for m in found:
            links[m.getLong("MATUSETRANSID")]=None if m.isNull("ISSUEID") else m.getLong("ISSUEID")
    return links

def put_back(layers,qty,cost,priority,ref=None,refmbo=None,cxid=None,initial=False):
    for layer in layers:
        if not different(layer["cost"],cost,PRICE_EPS) and layer.get("priority")==priority:
            layer["qty"]+=qty
            return
    layers.append({"qty":qty,"cost":cost,"ref":ref,"refmbo":refmbo,"cxid":cxid,
                   "initial":initial,"priority":priority})
    layers.sort(key=lambda layer: layer.get("priority") or ())

def restore_return(layers,qty,issue_row,allocations,return_cost=None,prior=None):
    remaining=qty
    if allocations:
        for a in reversed(allocations):
            if remaining<=EPS:
                break
            take=min(remaining,a["qty"])
            if take>EPS:
                put_back(layers,take,a["cost"],a.get("priority") or order(issue_row),
                         a.get("ref"),a.get("refmbo"),a.get("cxid"),a.get("initial",False))
                remaining-=take
    if remaining>EPS:
        cost=return_cost if return_cost is not None else issue_row.get("cost")
        if cost is None:
            fail("Retur fara pret de restabilire pentru ISSUEID=%s" % issue_row.get("ref"))
        priority=order(issue_row)
        if prior:
            for p in sorted(prior,key=order):
                if order(p)>=order(issue_row):
                    break
                if p.get("cost") is None or different(p["cost"],cost,PRICE_EPS):
                    continue
                if p.get("kind")=="INITIAL" or (p.get("qty") is not None and p["qty"]>ZERO and p.get("kind") in ENTRIES):
                    priority=order(p)
                    break
        put_back(layers,remaining,cost,priority,
                 issue_row.get("ref"),issue_row.get("refmbo"),issue_row.get("id"),False)

def replay(prior,links=None):
    layers=[]
    issue_allocs={}
    initial=any(r["kind"]=="INITIAL" for r in prior)
    prices,opening=set(),set()
    opening_dates={}
    movement,started,recovering=False,False,False
    for r in sorted(prior,key=order):
        if not r["date"] or r["cost"]<ZERO:
            fail("Data lipsa/pret negativ in istoricul anterior")
        kind,qty,cost=text(r["kind"]).strip(),r["qty"],r["cost"]
        if kind=="INITIAL":
            if movement or cost in opening or r["balance"] is None or r["balance"]<ZERO:
                fail("INITIAL ambiguu")
            opening.add(cost)
            opening_dates[r["date"]]=cost
            if r["balance"]>EPS:
                layers.append({"qty":r["balance"],"cost":cost,"ref":r["ref"],"refmbo":r["refmbo"],
                               "cxid":r["id"],"initial":True,"priority":order(r)})
            continue
        movement=True
        if qty is None:
            fail("Cantitate lipsa in istoricul anterior")
        if abs(qty)<=EPS:
            continue
        if kind=="RETURN":
            if qty<=ZERO:
                fail("Retur anterior cu cantitate nepozitiva RefID=%s" % r["ref"])
            issue_id=None if links is None else links.get(r["ref"])
            if issue_id is None:
                fail("Retur anterior %s fara ISSUEID" % r["ref"])
            matches=[p for p in prior if p.get("kind")=="ISSUE" and p.get("ref")==issue_id and order(p)<order(r)]
            if len(matches)!=1:
                fail("Retur anterior %s fara consum unic anterior" % r["ref"])
            restore_cost=cost if cost is not None else matches[0]["cost"]
            restore_return(layers,qty,matches[0],issue_allocs.get(issue_id) or [],restore_cost,prior)
            started=True
            continue
        if kind=="SHIPCANCEL":
            if qty<=ZERO:
                fail("SHIPCANCEL anterior fara cantitate pozitiva RefID=%s" % r["ref"])
            matches=[p for p in prior if p.get("kind")=="SHIPTRANSFER" and order(p)<order(r)
                     and p.get("qty") is not None and not different(-p["qty"],qty)
                     and p.get("cost") is not None and not different(p["cost"],cost,PRICE_EPS)]
            if len(matches)==1:
                ship=matches[0]
                restore_return(layers,qty,ship,issue_allocs.get(ship.get("ref")) or [],ship["cost"],prior)
            else:
                put_back(layers,qty,cost,order(r),r.get("ref"),r.get("refmbo"),r.get("id"),False)
            started=True
            continue
        if kind in VOID_TYPES:
            if qty>=-EPS:
                fail("%s anterior fara cantitate negativa RefID=%s" % (kind,r["ref"]))
            required=-qty
            available=sum((l["qty"] for l in layers if not different(l["cost"],cost,PRICE_EPS)),ZERO)
            if available+EPS<required:
                fail("Stoc pe pret insuficient pentru %s anterior RefID=%s" % (kind,r["ref"]))
            allocations,short=consume_at_cost(layers,required,cost,newest_first=True)
            if short>EPS or not allocations:
                fail("%s anterior nu a putut anula stocul pe pret RefID=%s" % (kind,r["ref"]))
            started=True
            continue
        if qty>ZERO:
            if kind not in ENTRIES:
                fail("Intrare/retur anterior netratat: %s RefID=%s" % (kind,r["ref"]))
            available=qty
            if (not initial and cost not in prices) or recovering:
                if r["balance"] is None:
                    fail("Sold lipsa pe intrarea de recuperare")
                known=sum((l["qty"] for l in layers if l["cost"]==cost),ZERO)
                available=min(qty,max(ZERO,r["balance"]-known))
            prices.add(cost)
            started=True
            if available>EPS:
                layers.append({"qty":available,"cost":cost,"ref":r["ref"],"refmbo":r["refmbo"],
                               "cxid":r["id"],"initial":False,"priority":order(r)})
                if r["balance"] is not None and r["balance"]>=ZERO:
                    recovering=False
        else:
            # qty<0. RECEIPT/SHIPRECEIPT negativa = iesire FIFO (nu tip necunoscut).
            if kind not in ("ISSUE","SHIPTRANSFER","TRANSFER","RECEIPT","SHIPRECEIPT"):
                fail("Iesire anterioara netratata %s tip=%s" % (VERSION,kind))
            if not initial and not started:
                recovering=True
                continue
            available=sum((l["qty"] for l in layers),ZERO)
            covered=available+EPS>=-qty
            if recovering and (r["balance"] is None or r["balance"]<ZERO) and not covered:
                consume(layers,-qty)
                continue
            allocation,short=consume(layers,-qty)
            if short>EPS:
                recovering=True
                continue
            expected=sum((a["qty"]*a["cost"] for a in allocation),ZERO)/(-qty)
            if different(cost,expected,PRICE_EPS):
                fail("Corecteaza intai iesirea anterioara RefID=%s" % r["ref"])
            if r.get("ref") is not None:
                issue_allocs[r["ref"]]=[dict(a) for a in allocation]
            recovering=False
    if recovering:
        fail("Baza cronologica anterioara nerecuperata; ORDINE_DATE nu autorizeaza update")
    return layers

def writable(m):
    m.setFlag(MboConstants.NOSAVE,False)
    m.getThisMboSet().setFlag(MboConstants.NOSAVE,False)

def copy_value(src,dst,field):
    if src.isNull(field):
        if not dst.isNull(field):
            dst.setValueNull(field,FLAGS)
        return
    dst.setValue(field,src.getMboValue(field).getCurrentValue(),FLAGS)

def split_contentuid(source,index,used=None):
    from java.util import UUID
    uid=text(UUID.randomUUID().toString())
    if used is not None:
        guard=0
        while uid in used and guard<20:
            uid=text(UUID.randomUUID().toString())
            guard+=1
        used.add(uid)
    return uid

def add_minutes(value,minutes):
    from java.util import Calendar
    cal=Calendar.getInstance()
    cal.setTime(value)
    cal.add(Calendar.MINUTE,int(minutes))
    return cal.getTime()

def audit_info(message):
    msg=text(message).replace("\n"," ").strip()
    prefixes=("OK: ","DIFERENTA: ","NEVERIFICAT: ","FARA MISCARE: ","INITIAL: ",
              "ANULAT: ","CORECTAT: ","FROMSTORELOC=")
    if not msg.startswith(prefixes):
        msg="NEVERIFICAT: "+msg
    if " | BADFIFO=" not in msg:
        msg=msg+" | BADFIFO=U"
    return msg

def set_info(mbo,message):
    msg=audit_info(message)
    mbo.setValue("DESCRIPTION_LONGDESCRIPTION",msg,FLAGS)
    return msg

def long_text(m,field="DESCRIPTION_LONGDESCRIPTION"):
    try:
        if m is None or m.isNull(field):
            return ""
        value=m.getString(field)
    except:
        return ""
    return "" if value is None else value

def layer_segments(allocations):
    segments=[]
    for a in allocations:
        if a.get("refmbo")=="MATRECTRANS" and a.get("ref") is not None:
            is_initial=False
            receipt=a["ref"]
        else:
            is_initial=True
            receipt=None
        if ExactNumber(a["qty"].fixed(3))!=a["qty"] or a["qty"]<STEP:
            fail("Cantitate strat nereprezentabila cu trei zecimale")
        if ExactNumber(a["cost"].fixed(3))!=a["cost"] or a["cost"]<ZERO:
            fail("PU strat nereprezentabil")
        same=segments and not different(segments[-1]["cost"],a["cost"],PRICE_EPS) and segments[-1]["receipt"]==receipt and segments[-1]["initial"]==is_initial
        if same:
            segments[-1]["qty"]+=a["qty"]
        else:
            segments.append({"qty":a["qty"],"cost":a["cost"],"receipt":receipt,"initial":is_initial,"source_cxid":a.get("cxid")})
    if not segments:
        fail("Nu exista alocare FIFO")
    costs=[]
    for seg in segments:
        if not any(not different(seg["cost"],c,PRICE_EPS) for c in costs):
            costs.append(seg["cost"])
    if len(costs)==1:
        total_qty=sum((seg["qty"] for seg in segments),ZERO)
        first=segments[0]
        return [{"qty":total_qty,"cost":first["cost"],"receipt":first["receipt"],
                 "initial":first["initial"],"source_cxid":first.get("source_cxid")}]
    return segments

def map_members(segments,members):
    if len(segments)>len(members):
        mapped=[]
        for mem,seg in zip(members,segments):
            mapped.append({"member":mem,"qty":seg["qty"],"cost":seg["cost"],"receipt":seg["receipt"],
                           "initial":seg.get("initial",False),"value":money(seg["qty"]*seg["cost"]),"create":False})
        creates=[]
        for seg in segments[len(members):]:
            creates.append({"qty":seg["qty"],"cost":seg["cost"],"receipt":seg["receipt"],
                            "initial":seg.get("initial",False),"value":money(seg["qty"]*seg["cost"]),"create":True})
        return mapped,creates
    counts=[1 for a in segments]
    extra=len(members)-len(segments)
    for i in range(len(segments)-1,-1,-1):
        while extra and segments[i]["qty"]>=STEP*ExactNumber(counts[i]+1):
            counts[i]+=1
            extra-=1
    if extra:
        fail("Prea multe randuri existente fata de cantitatea disponibila")
    mapped,offset=[],0
    for a,count in zip(segments,counts):
        left=a["qty"]
        for j in range(count):
            mem=members[offset]
            take=left if j==count-1 else min(mem["old_qty"],left-STEP*ExactNumber(count-j-1))
            if take<STEP or ExactNumber(take.fixed(3))!=take:
                fail("Cantitate nereprezentabila cu trei zecimale")
            mapped.append({"member":mem,"qty":take,"cost":a["cost"],"receipt":a["receipt"],
                           "initial":a.get("initial",False),"value":money(take*a["cost"]),"create":False})
            left-=take
            offset+=1
    return mapped,[]

def layer_balance(query,receipt_id,actual_key,self_id,self_qty,pending):
    rs,receipts=query("MATRECTRANS","MATRECTRANSID=%s" % receipt_id,2)
    if len(receipts)!=1:
        fail("Receptie FIFO %s lipsa sau neunica" % receipt_id)
    total=number(receipts[0],"QUANTITY")
    ms,uses=query("MATUSETRANS","MATRECTRANSID=%s AND ISSUETYPE IN ('ISSUE','RETURN')" % receipt_id)
    seen=set()
    for m in uses:
        mid=m.getLong("MATUSETRANSID")
        d=datekey(m.getDate("ACTUALDATE"))
        if d>actual_key or (d==actual_key and mid>self_id):
            continue
        seen.add(mid)
        total+=self_qty if mid==self_id else number(m,"QUANTITY")
    if self_id not in seen:
        total+=self_qty
    for mid,qty,d,rid in pending:
        if rid!=receipt_id or mid==self_id:
            continue
        if d>actual_key or (d==actual_key and mid>self_id):
            continue
        if mid in seen:
            continue
        total+=qty
    return total

def ledger(journal,changes):
    books,opening,movement,result={},set(),set(),{}
    for r in sorted(journal,key=order):
        c=changes.get(r["id"],{})
        cost,qty=c.get("cost",r["cost"]),c.get("qty",r["qty"])
        if not r["date"]:
            fail("Data lipsa la recalcul sold")
        if r["kind"]=="INITIAL":
            if cost in opening or cost in movement or r["balance"] is None:
                fail("INITIAL ambiguu la recalcul sold")
            opening.add(cost)
            books[cost]=r["balance"]
        else:
            if qty is None:
                fail("Cantitate lipsa la recalcul sold")
            movement.add(cost)
            books[cost]=books.get(cost,ZERO)+qty
        result[r["id"]]=books[cost]
    return result

def select_write_sets(planned_tables,sets_by_name):
    unexpected=set(planned_tables).difference(set(WRITE_TABLES))
    if unexpected:
        fail("Obiecte nepermise in plan: "+", ".join(sorted(unexpected)))
    return [(n,sets_by_name[n]) for n in WRITE_TABLES if n in planned_tables]

def stock_signature(user,context,itemset,opened):
    result=[]
    for name,fields in (
        ("INVBALANCES",("INVBALANCESID","CURBAL","BINNUM","LOTNUM","CONDITIONCODE")),
        ("INVLIFOFIFOCOST",("INVLIFOFIFOCOSTID","QUANTITY","UNITCOST","COSTDATE","REFOBJECT","REFOBJECTID"))
    ):
        ms=open_readonly(user,name,scope_where(context,name,itemset))
        opened.append(ms)
        result.append((name,sorted(tuple(m.getString(f) for f in fields) for m in readrows(ms))))
    return result

def document_values(doc,line):
    return (doc.getString("STATUS"),doc.getString("CXTOTALCOST"),
            line.getString("QUANTITY"),line.getString("UNITCOST"),line.getString("LINECOST"))

def split_monitor(user,lineid,service):
    ms=None
    try:
        ms=open_readonly(user,"INVUSELINESPLIT","INVUSELINEID=%s" % lineid)
        return sorted((m.getLong("INVUSELINESPLITID"),m.getString("QUANTITY"),m.getString("UNITCOST")) for m in readrows(ms,MAX_SPLITS))
    except Exception as exc:
        service.log_info("CXFIFOFIXISSUE control split indisponibil: "+text(exc))
        return None
    finally:
        close(ms)

def screen_rows(context):
    found={}
    ms=context.getThisMboSet()
    i=0
    row=ms.getMbo(i)
    while row is not None:
        found[row.getLong("CXSTOCURIID")]=row
        i+=1
        if i>MAX_ROWS:
            fail("Limita de volum depasita")
        row=ms.getMbo(i)
    return found

def bind_screen_journal(context, rows):
    ui=screen_rows(context)
    for row in rows:
        other=ui.get(row["id"])
        if other is None:
            continue
        if text(other.getRowStamp())!=text(row["mbo"].getRowStamp()):
            fail("Jurnalul de pe ecran e invechit pentru CXSTOCURIID=%s; redeschide articolul" % row["id"])
        row["mbo"]=other

def owns(plans):
    from java.lang import System
    ordered=[]
    seen=set()
    for m,f,k,v,old in plans:
        ms=m.getThisMboSet()
        marker=System.identityHashCode(ms)
        if marker in seen:
            continue
        seen.add(marker)
        ordered.append((m.getName().upper(),ms))
    rank={"INVUSELINESPLIT":0,"MATUSETRANS":1,"MATRECTRANS":2,"CXSTOCURI":3}
    ordered.sort(key=lambda pair: rank.get(pair[0],9))
    return ordered

def refresh_table(context=None):
    from psdi.common.context import UIContext
    ui=UIContext.getCurrentContext()
    session=ui.getWebClientSession() if ui else None
    if session is None:
        return False
    ok=False
    bean=session.getDataBean(TABLE_ID)
    if bean is not None:
        bean.reset()
        bean.refreshTable()
        ok=True
    try:
        app=session.getCurrentApp()
        if app is not None:
            for name in ("INVUSELINESPLIT","INVUSELINE","INVUSE","MATUSETRANS","MATRECTRANS"):
                try:
                    b=app.getDataBean(name)
                    if b is not None:
                        b.reset()
                except Exception:
                    pass
    except Exception:
        pass
    return ok

def apply_journal_overrides(journal,changes):
    out=[]
    for r in journal:
        if r["id"] in changes:
            nr=dict(r)
            ch=changes[r["id"]]
            if "qty" in ch and ch["qty"] is not None:
                nr["qty"]=ch["qty"]
            if "cost" in ch and ch["cost"] is not None:
                nr["cost"]=ch["cost"]
            out.append(nr)
        else:
            out.append(r)
    return out

def cascade_following_issues(journal,start_pos,group,changes,query,max_n=None):
    if max_n is None:
        max_n=CASCADE_MAX_ISSUES
    fixed=[]
    stop=None
    planned=[]
    by_id=dict((r["id"],i) for i,r in enumerate(journal))
    for r in journal[start_pos+1:]:
        if len(fixed)>=max_n:
            stop="limita max %s ISSUE" % max_n
            break
        if r.get("kind")!="ISSUE" or r.get("refmbo")!="MATUSETRANS":
            stop="intrerupt de %s RefID=%s" % (r.get("kind"),r.get("ref"))
            break
        if r.get("qty") is None or r["qty"]>=ZERO or r.get("cost") is None:
            stop="date incomplete RefID=%s" % r.get("ref")
            break
        working=apply_journal_overrides(journal,changes)
        pos_r=by_id.get(r["id"])
        if pos_r is None:
            stop="rand jurnal lipsa RefID=%s" % r.get("ref")
            break
        prior=working[:pos_r]
        try:
            layers=replay(prior,issue_of_returns(prior,query))
            allocation,short=consume(layers,-r["qty"])
        except FixError as exc:
            stop="RefID=%s: %s" % (r.get("ref"),text(exc))
            break
        if short>EPS:
            stop="stoc insuficient RefID=%s" % r.get("ref")
            break
        costs=[]
        for a in allocation:
            if not any(not different(a["cost"],c,PRICE_EPS) for c in costs):
                costs.append(a["cost"])
        if len(costs)!=1:
            stop="necesita line split RefID=%s" % r.get("ref")
            break
        cost=costs[0]
        if cost<ZERO or ExactNumber(cost.fixed(3))!=cost:
            stop="pret invalid RefID=%s" % r.get("ref")
            break
        ms,rows=query("MATUSETRANS","MATUSETRANSID=%s" % r["ref"],2)
        if len(rows)!=1:
            stop="MATUSETRANS %s lipsa/neunic" % r.get("ref")
            break
        mm=rows[0]
        if mm.getString("ISSUETYPE")!="ISSUE" or number(mm,"QUANTITY")>=ZERO:
            stop="MATUSETRANS %s nu e ISSUE negativ" % r.get("ref")
            break
        qty_abs=-number(mm,"QUANTITY")
        if different(qty_abs,-r["qty"]):
            stop="cantitate jurnal≠sursa RefID=%s" % r.get("ref")
            break
        first=allocation[0]
        if first.get("refmbo")=="MATRECTRANS" and first.get("ref") is not None:
            receipt=first["ref"]
        elif first.get("initial"):
            receipt=None
        else:
            receipt=first.get("ref")
        changes[r["id"]]={"qty":r["qty"],"cost":cost}
        planned.append({"ref":r["ref"],"mbo":mm,"qty":qty_abs,"cost":cost,
                        "value":money(qty_abs*cost),"receipt":receipt,"journal_id":r["id"]})
        fixed.append(r["ref"])
    return fixed,stop,planned

def single_fifo_cost(prior,exit_qty,links=None):
    if exit_qty is None or exit_qty>=ZERO:
        fail("Iesirea trebuie sa aiba cantitate negativa")
    layers=replay(prior,links)
    allocation,short=consume(layers,-exit_qty)
    if short>EPS:
        fail("Stoc anterior insuficient")
    costs=set(a["cost"] for a in allocation)
    if len(costs)!=1:
        fail("Multi-pret pe MATRECTRANS transfer: split refuzat")
    cost=allocation[0]["cost"]
    if cost<ZERO or ExactNumber(cost.fixed(3))!=cost:
        fail("Pretul FIFO nu poate fi scris")
    return cost,allocation

def check_matrectrans_exit_cost():
    def row(ident,date,ref,kind,qty,cost,balance,mbo="MATRECTRANS"):
        return {"id":ident,"group":"G","date":date,"ref":ref,"refmbo":mbo,"kind":kind,
                "qty":ExactNumber(qty),"cost":ExactNumber(cost),
                "balance":None if balance is None else ExactNumber(balance)}
    cost,allocation=single_fifo_cost([
        row(1,"2026-06-01 00:00:00.000000000",300,"SHIPTRANSFER","-10","9.098","-10"),
        row(2,"2026-06-08 00:00:00.000000000",100,"SHIPRECEIPT","10","9.098","0"),
        row(3,"2026-09-07 00:00:00.000000000",400,"SHIPRECEIPT","20","9.846","20"),
    ],ExactNumber("-1"))
    if different(cost,ExactNumber("9.846"),PRICE_EPS) or not allocation or allocation[0].get("ref")!=400:
        raise ValueError("self-check: SHIPTRANSFER FIFO")
    merged=layer_segments([
        {"qty":ExactNumber("10"),"cost":ExactNumber("8.320"),"ref":100,"refmbo":"MATRECTRANS","cxid":1,"initial":False},
        {"qty":ExactNumber("10"),"cost":ExactNumber("8.320"),"ref":200,"refmbo":"MATRECTRANS","cxid":2,"initial":False}])
    if len(merged)!=1 or merged[0]["receipt"]!=100:
        raise ValueError("self-check: merge same-cost")
    if len(layer_segments([
        {"qty":ExactNumber("10"),"cost":ExactNumber("8.320"),"ref":100,"refmbo":"MATRECTRANS","cxid":1,"initial":False},
        {"qty":ExactNumber("10"),"cost":ExactNumber("9.360"),"ref":200,"refmbo":"MATRECTRANS","cxid":2,"initial":False}]))!=2:
        raise ValueError("self-check: keep multi-cost")
    try:
        single_fifo_cost([row(1,"2026-06-01 00:00:00.000000000",1,"SHIPTRANSFER","-1","9","-1")],ExactNumber("-1"))
        raise ValueError("self-check: no-stock")
    except FixError:
        pass
    cost,allocation=single_fifo_cost([
        row(1,"2026-06-01 00:00:00.000000000",10,"RECEIPT","100","9.501","100"),
        row(2,"2026-06-18 00:00:00.000000000",20,"RECEIPT","200","9.099","300"),
        row(3,"2026-06-18 00:03:00.000000000",30,"VOIDRECEIPT","-200","9.099","100"),
        row(4,"2026-06-18 00:04:00.000000000",40,"RECEIPT","200","9.099","300"),
    ],ExactNumber("-50"))
    if different(cost,ExactNumber("9.501"),PRICE_EPS) or not allocation or allocation[0].get("ref")!=10:
        raise ValueError("self-check: VOIDRECEIPT prior")
    cost,allocation=single_fifo_cost([
        row(1,"2017-06-01 01:00:00.000000000",1,"INITIAL","1","5.590","1","CXSTOCURI"),
        row(2,"2026-01-20 00:00:00.000000000",2,"SHIPRECEIPT","1","7.500","1"),
    ],ExactNumber("-1"))
    if different(cost,ExactNumber("5.590"),PRICE_EPS):
        raise ValueError("self-check: RECEIPT negativ pe INITIAL")
    # ISSUE dupa RECEIPT negativ: RECEIPT consuma INITIAL@70, ISSUE ia SHIPRECEIPT@58.
    cost,allocation=single_fifo_cost([
        row(1,"2025-12-01 00:00:00.000000000",1,"INITIAL","1000","70","1000","CXSTOCURI"),
        row(2,"2026-01-21 00:00:00.000000000",2,"SHIPRECEIPT","4000","58","4000"),
        row(3,"2026-06-24 00:01:00.000000000",3,"RECEIPT","-1000","70","0"),
    ],ExactNumber("-1"))
    if different(cost,ExactNumber("58"),PRICE_EPS) or not allocation or allocation[0].get("ref")!=2:
        raise ValueError("self-check: ISSUE dupa RECEIPT negativ trebuie 58")
    layers=replay([
        row(1,"2026-01-01 00:00:00.000000000",1,"INITIAL","100","2.630","100","CXSTOCURI"),
        row(2,"2026-01-01 00:00:00.000000000",2,"INITIAL","1000","2.960","1000","CXSTOCURI"),
        row(3,"2026-02-01 00:00:00.000000000",154452,"ISSUE","-100","2.630","0","MATUSETRANS"),
        row(4,"2026-03-01 00:00:00.000000000",20,"ISSUE","-50","2.960","950","MATUSETRANS"),
        row(5,"2026-04-22 10:41:00.000000000",30,"RETURN","30","2.630","980","MATUSETRANS"),
    ],{30:154452})
    allocation,short=consume(layers,ExactNumber("40"))
    if short>EPS or len(allocation)<2:
        raise ValueError("self-check: RETURN multi-cost")
    if different(allocation[0]["cost"],ExactNumber("2.630"),PRICE_EPS) or different(allocation[0]["qty"],ExactNumber("30")):
        raise ValueError("self-check: seg1")
    if different(allocation[1]["cost"],ExactNumber("2.960"),PRICE_EPS) or different(allocation[1]["qty"],ExactNumber("10")):
        raise ValueError("self-check: seg2")


EXEC_SCRIPT="CXFIFOFIXEXEC"

def bind_execute(user):
    ms=open_readonly(user,"AUTOSCRIPT","AUTOSCRIPT='%s'" % EXEC_SCRIPT)
    try:
        rows=readrows(ms,2)
    finally:
        close(ms)
    if len(rows)!=1:
        fail("Lipseste %s. Script jython fara launch point, sub 100000 caractere." % EXEC_SCRIPT)
    src=rows[0].getString("SOURCE")
    if src is None or "def execute(context):" not in src:
        fail("%s nu defineste execute(context)" % EXEC_SCRIPT)
    ns=bind_execute.func_globals
    try:
        exec src in ns
    except:
        fail("%s nu se compileaza: %s" % (EXEC_SCRIPT, text(__import__("sys").exc_info()[1])))
    if not callable(ns.get("execute")):
        fail("%s nu a definit execute" % EXEC_SCRIPT)

if "mbo" in globals() and "service" in globals():
    try:
        bind_execute(mbo.getUserInfo())
        result=bind_execute.func_globals["execute"](mbo)
    except FixError as exc:
        result="CXFIFOFIXISSUE: "+text(exc)
    except:
        result="CXFIFOFIXISSUE: "+text(__import__("sys").exc_info()[1])
    service.error(MESSAGE_GROUP,MESSAGE_KEY,[result])
