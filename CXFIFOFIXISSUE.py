# SCRIPT: CXFIFOFIXISSUE
# AUTOR: Cristian Grosu
# VERSIUNE: 3.12-INITIAL-MULTI
# Corecteaza randul CXSTOCURI apasat + tranzactia sursa (MATUSETRANS/MATRECTRANS).
# ISSUE pe mai multe straturi FIFO: 3 pasi (commit in script; NU Save pe ecran intre pasi).
# PAS 1 = INVUSELINESPLIT lipsa; PAS 2 = MATUSETRANS nou (ACTUALDATE +1 min);
# PAS 3 = CXSTOCURI nou + corectie CXQTY/CXCURBAL. Info FIFO dupa fiecare pas.
# Save pe ecran dupa commit pe INVUSELINESPLIT = BMXAA8229W (ROWSTAMP stale).
# Cale normala (fara creates): NU atinge INVUSELINESPLIT — doar MATUSETRANS+CXSTOCURI.
# SHIPTRANSFER/TRANSFER de iesire din MATRECTRANS: doar MATRECTRANS+CXSTOCURI (fara split).
# Strat INITIAL e provenienta legitima (MATRECTRANSID null pe linia corespunzatoare).
# Mai multe INITIAL pe aceeasi data cu preturi diferite = OK (straturi de deschidere).
# Daca INVUSELINE lipseste, corecteaza totusi pretul tranzactiei si jurnalul.
# RETURN preia acelasi pret FIFO al consumului.
# VOIDRECEIPT anterior: anulare pe pret (newest-first), ca in CXINVAUDIT — nu blocheaza ISSUE.
# Dupa corectie: recalculeaza CXCURBAL pe TOT jurnalul grupei (nu doar pretul afectat),
# ca BADFIFO=Y pe sold sa fie reparat odata cu / chiar fara diferenta de pret.
# NU modifica INVUSE/INVUSELINE, receptii, stoc fizic, INVLIFOFIFOCOST ori ROWSTAMP.
# Necesita protectia CXADDTOCXSTOCURI si teste fara concurenta in TEST.
# Calcule Java BigDecimal; fara decimal/json/re si fara filtre de pilot.

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

VERSION="3.12-INITIAL-MULTI"
APP="INVENTOR"
OPTION="CXFIFOFIXISSUE"
TABLE_ID="1792055730066"
MESSAGE_GROUP="CXFIFO"
MESSAGE_KEY="FIXISSUERESULT"
MAX_ROWS=5000
MAX_SPLITS=50
ZERO=ExactNumber("0")
ONE=ExactNumber("1")
STEP=ExactNumber("0.001")
EPS=ExactNumber("0.000001")
PRICE_EPS=ExactNumber("0.0005")
FLAGS=MboConstants.NOACCESSCHECK | MboConstants.NOVALIDATION_AND_NOACTION
ENTRIES=("RECEIPT","SHIPRECEIPT","TRANSFER")
EXITS=("ISSUE","SHIPTRANSFER","TRANSFER")
VOID_TYPES=("VOIDRECEIPT",)
MATREC_EXITS=("SHIPTRANSFER","TRANSFER")
WRITE_TABLES=("INVUSELINESPLIT","MATUSETRANS","MATRECTRANS","CXSTOCURI")
SPLIT_COPY=("INVUSENUM","ORGID","SITEID","INVUSELINEID","FROMLOT","ROTASSETNUM","FROMBIN",
            "PHYSCNT","PHYSCNTDATE","SENDERSYSID","INVUSELINENUM","ITEMNUM","ITEMSETID",
            "FROMSTORELOC","FROMCONDITIONCODE","STAGINGBIN","STAGINGLOT","PLSTATE","RETURNBIN","RETURNQTY")
MATUSE_COPY=("ITEMNUM","STORELOC","ACTUALDATE","CURBAL","PHYSCNT","PONUM","CONVERSION","ASSETNUM",
             "IT1","IT2","IT3","IT4","IT5","MEMO","OUTSIDE","ISSUETO","PACKINGSLIPNUM","POLINENUM",
             "ROLLUP","ITIN1","ITIN2","ITIN3","BINNUM","LOTNUM","ISSUETYPE","GLDEBITACCT","GLCREDITACCT",
             "FINANCIALPERIOD","CURRENCYCODE","ROTASSETNUM","LOCATION","DESCRIPTION","EXCHANGERATE",
             "SPAREPARTADDED","EXCHANGERATE2","MRNUM","MRLINENUM","IT6","IT7","IT8","IT9","IT10",
             "ITIN4","ITIN5","ITIN6","ITIN7","ORGID","SITEID","REFWO","ENTEREDASTASK","LINETYPE",
             "ITEMSETID","CONDITIONCODE","CONDRATE","COMMODITYGROUP","COMMODITY","TOSITEID","LANGCODE",
             "POREVISIONNUM","INVUSELINEID","INVUSEID","CONSIGNMENT","ISSUEUNIT","WPITEMID","INVPICKLISTID")

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
            "group":m.getString("COMMODITYGROUP"),"mbo":m}

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
    # VOIDRECEIPT anuleaza pe pret; newest_first leaga de receptia recenta anulata.
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

def restore(layers,qty,cost,prior=None):
    for layer in layers:
        if not different(layer["cost"],cost,PRICE_EPS):
            layer["qty"]+=qty
            return
    ref=refmbo=cxid=None
    is_initial=True
    if prior:
        ordered=list(reversed(sorted(prior,key=order)))
        for p in ordered:
            if different(p.get("cost"),cost,PRICE_EPS):
                continue
            if p.get("qty") is not None and p["qty"]>ZERO and p.get("refmbo")=="MATRECTRANS" and p.get("ref") is not None:
                ref,refmbo,cxid=p["ref"],p["refmbo"],p["id"]
                is_initial=False
                break
        else:
            for p in ordered:
                if p.get("kind")=="INITIAL" and not different(p.get("cost"),cost,PRICE_EPS):
                    ref,refmbo,cxid=p.get("ref"),p.get("refmbo"),p["id"]
                    break
    # ponytail: stratul epuizat revine in fata. Pozitia FIFO originala cere pastrarea stratului gol.
    layers.insert(0,{"qty":qty,"cost":cost,"ref":ref,"refmbo":refmbo,"cxid":cxid,"initial":is_initial})

def replay(prior,links=None):
    layers=[]
    initial=any(r["kind"]=="INITIAL" for r in prior)
    prices,opening=set(),set()
    opening_dates={}
    movement,started,recovering=False,False,False
    for r in sorted(prior,key=order):
        if not r["date"] or r["cost"]<ZERO:
            fail("Data lipsa/pret negativ in istoricul anterior")
        kind,qty,cost=r["kind"],r["qty"],r["cost"]
        if kind=="INITIAL":
            # Mai multe INITIAL aceeasi data / preturi diferite = straturi deschidere OK.
            if movement or cost in opening or r["balance"] is None or r["balance"]<ZERO:
                fail("INITIAL ambiguu")
            opening.add(cost)
            opening_dates[r["date"]]=cost
            if r["balance"]>EPS:
                layers.append({"qty":r["balance"],"cost":cost,"ref":r["ref"],"refmbo":r["refmbo"],"cxid":r["id"],"initial":True})
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
            restore(layers,qty,matches[0]["cost"],prior)
            started=True
            continue
        if kind in VOID_TYPES:
            if qty>=-EPS:
                fail("VOIDRECEIPT anterior fara cantitate negativa RefID=%s" % r["ref"])
            required=-qty
            available=sum((l["qty"] for l in layers if not different(l["cost"],cost,PRICE_EPS)),ZERO)
            if available+EPS<required:
                fail("Stoc pe pret insuficient pentru VOIDRECEIPT anterior RefID=%s" % r["ref"])
            allocations,short=consume_at_cost(layers,required,cost,newest_first=True)
            if short>EPS or not allocations:
                fail("VOIDRECEIPT anterior nu a putut anula stocul pe pret RefID=%s" % r["ref"])
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
                layers.append({"qty":available,"cost":cost,"ref":r["ref"],"refmbo":r["refmbo"],"cxid":r["id"],"initial":False})
                # CXCURBAL>=0 pe intrare reface baza locala; gap-ul anterior nu blocheaza iesirea curenta.
                if r["balance"] is not None and r["balance"]>=ZERO:
                    recovering=False
        else:
            if kind not in EXITS:
                fail("Iesire/retur anterior netratat: "+kind)
            if not initial and not started:
                recovering=True
                continue
            available=sum((l["qty"] for l in layers),ZERO)
            covered=available+EPS>=-qty
            # Soldul negativ e pe pretul curent; stratul de la alt pret poate acoperi iesirea.
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

def split_contentuid(source,index):
    tag="cgFIA2026"
    src=text(source)
    base=tag+src[len(tag):] if len(src)>=len(tag) else tag+src
    if index<=0:
        return base
    mark=text(index)
    if len(base)<=len(tag)+len(mark):
        return base+mark
    return base[:len(tag)]+mark+base[len(tag)+len(mark):]

def add_minutes(value,minutes):
    from java.util import Calendar
    cal=Calendar.getInstance()
    cal.setTime(value)
    cal.add(Calendar.MINUTE,int(minutes))
    return cal.getTime()

def audit_info(message):
    # CXINVAUDIT generated_compact_info: o linie, prefix OK/DIFERENTA/NEVERIFICAT..., | BADFIFO=*
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

def layer_segments(allocations):
    segments=[]
    for a in allocations:
        # INITIAL e provenienta legitima (sold deschidere / RETURN pe cost INITIAL).
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
    # ponytail: randul deja incarcat in tabel trebuie scris o singura data.
    # A doua instanta CXSTOCURI produce BMXAA8229W pe ROWSTAMP.
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

def refresh_table():
    # Commit-ul e deja in DB. Refresh UI ca sa nu mai fie nevoie de Save
    # (Save pe INVUSELINESPLIT stale = BMXAA8229W).
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
    # ponytail: incearca si alte bean-uri care tin INVUSELINESPLIT in sesiune
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

def blocked_finance(m):
    try:
        if not m.isNull("FINCNTRLID"):
            return True
    except Exception:
        pass
    try:
        return m.getBoolean("CXSENTEBS")
    except Exception:
        return False

def single_fifo_cost(prior,exit_qty,links=None):
    if exit_qty is None or exit_qty>=ZERO:
        fail("Iesirea trebuie sa aiba cantitate negativa")
    layers=replay(prior,links)
    allocation,short=consume(layers,-exit_qty)
    if short>EPS:
        fail("Stoc anterior insuficient; receptiile viitoare nu autorizeaza update")
    costs=set(a["cost"] for a in allocation)
    if len(costs)!=1:
        fail("Iesirea are mai multe preturi FIFO; corectia automata refuza splitul pe MATRECTRANS")
    cost=allocation[0]["cost"]
    if cost<ZERO or ExactNumber(cost.fixed(3))!=cost:
        fail("Pretul FIFO nu poate fi scris")
    return cost,allocation

def check_matrectrans_exit_cost():
    def row(ident,date,ref,kind,qty,cost,balance,group="G"):
        return {"id":ident,"group":group,"date":date,"ref":ref,"refmbo":"MATRECTRANS",
                "kind":kind,"qty":ExactNumber(qty),"cost":ExactNumber(cost),
                "balance":None if balance is None else ExactNumber(balance)}
    prior=[
        row(1,"2026-06-01 00:00:00.000000000",300,"SHIPTRANSFER","-10","9.098","-10"),
        row(2,"2026-06-08 00:00:00.000000000",100,"SHIPRECEIPT","10","9.098","0"),
        row(3,"2026-09-07 00:00:00.000000000",400,"SHIPRECEIPT","20","9.846","20"),
    ]
    cost,allocation=single_fifo_cost(prior,ExactNumber("-1"))
    if different(cost,ExactNumber("9.846"),PRICE_EPS):
        raise ValueError("self-check: SHIPTRANSFER nu preia pretul receptiei anterioare")
    if not allocation or allocation[0].get("ref")!=400:
        raise ValueError("self-check: sursa FIFO gresita pentru SHIPTRANSFER")
    try:
        single_fifo_cost([
            row(1,"2026-06-01 00:00:00.000000000",1,"SHIPTRANSFER","-1","9","-1"),
        ],ExactNumber("-1"))
        raise ValueError("self-check: iesirea fara stoc trebuia respinsa")
    except FixError:
        pass
    # Speta 206686: VOIDRECEIPT OK pe pret anuleaza receptia recenta; ISSUE ulterior pe FIFO vechi.
    void_prior=[
        row(1,"2026-06-01 00:00:00.000000000",10,"RECEIPT","100","9.501","100"),
        row(2,"2026-06-18 00:00:00.000000000",20,"RECEIPT","200","9.099","300"),
        row(3,"2026-06-18 00:03:00.000000000",30,"VOIDRECEIPT","-200","9.099","100"),
        row(4,"2026-06-18 00:04:00.000000000",40,"RECEIPT","200","9.099","300"),
    ]
    cost,allocation=single_fifo_cost(void_prior,ExactNumber("-50"))
    if different(cost,ExactNumber("9.501"),PRICE_EPS):
        raise ValueError("self-check: ISSUE dupa VOIDRECEIPT trebuie sa preia 9.501")
    if not allocation or allocation[0].get("ref")!=10:
        raise ValueError("self-check: VOIDRECEIPT trebuie sa lase stratul vechi FIFO")

def execute(context):
    check_matrectrans_exit_cost()
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
            fail("Pentru MATRECTRANS selecteaza SHIPTRANSFER sau TRANSFER de iesire")
        if number(context,"CXQTY")>=ZERO:
            fail("Selecteaza randul de iesire (cantitate negativa) din jurnal")
    else:
        fail("Selecteaza ISSUE/RETURN din MATUSETRANS sau SHIPTRANSFER/TRANSFER din MATRECTRANS")
    if context.isNull("CXREFID"):
        fail("CXREFID lipsa")
    if "MOTIV=ORDINE_DATE" in context.getString("DESCRIPTION_LONGDESCRIPTION"):
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
            rmset,receipts=query("MATRECTRANS","MATRECTRANSID=%s" % context.getLong("CXREFID"),2)
            if len(receipts)!=1:
                fail("MATRECTRANS tinta lipsa/neunic")
            rm=receipts[0]
            if rm.getString("ISSUETYPE")!=kind:
                fail("ISSUETYPE pe MATRECTRANS difera de CXREF")
            if number(rm,"QUANTITY")<=ZERO:
                fail("MATRECTRANS %s nu are cantitate pozitiva de expediere/transfer" % rm.getLong("MATRECTRANSID"))
            if blocked_finance(rm):
                fail("Document transmis sau cu FINCNTRLID; corectie automata refuzata")
            if number(rm,"CONVERSION")!=ONE or number(rm,"EXCHANGERATE")!=ONE:
                fail("Conversie unitati/valuta diferita de 1")
            rate2=number(rm,"EXCHANGERATE2",True)
            if (rate2 is not None and rate2!=ONE) or (not rm.isNull("LINECOST2") and rate2!=ONE):
                fail("Conversie moneda secundara netratata")
            if rm.isNull("ACTUALDATE") or rm.isNull("TRANSDATE"):
                fail("Data sursa lipsa")
            if rm.getString("ITEMNUM")!=context.getString("ITEMNUM"):
                fail("Articol diferit fata de randul apasat")
            if rm.getString("FROMSITEID")!=context.getString("SITEID"):
                fail("Site sursa neconform")
            if rm.isNull("FROMSTORELOC") or rm.getString("FROMSTORELOC")!=context.getString("LOCATION"):
                fail("Gestiune sursa neconforma")
            qty_doc=number(rm,"QUANTITY")
            qty_journal=-qty_doc
            cxwhere=scope_where(context,"CXSTOCURI")
            cxset,raw=query("CXSTOCURI",cxwhere)
            all_journal=[journal_row(m) for m in raw]
            bind_screen_journal(context,all_journal)
            if any(m.getString("CURRENCYCODE")!=rm.getString("CURRENCYCODE") for m in raw if not m.isNull("CURRENCYCODE")):
                fail("Monede diferite intre jurnal si MATRECTRANS")
            journal=sorted([r for r in all_journal if r["group"]==context.getString("COMMODITYGROUP")],key=order)
            positions=[i for i,r in enumerate(journal)
                       if r["refmbo"]=="MATRECTRANS" and r["ref"]==rm.getLong("MATRECTRANSID")
                       and r["kind"]==kind and r["qty"] is not None and r["qty"]<ZERO]
            if len(positions)!=1:
                fail("Iesirea %s nu are un singur rand negativ in jurnalul local" % rm.getLong("MATRECTRANSID"))
            pos=positions[0]
            ij=journal[pos]
            if ij["id"]!=context.getLong("CXSTOCURIID") or text(ij["mbo"].getRowStamp())!=text(context.getRowStamp()):
                fail("Rand apasat schimbat; refresh necesar")
            if ij["date"]!=datekey(rm.getDate("ACTUALDATE")) or different(ij["qty"],qty_journal):
                fail("Cantitatea sau data din jurnal difera de MATRECTRANS; nu le modificam in acest pas")
            cost,allocation=single_fifo_cost(journal[:pos],ij["qty"],issue_of_returns(journal[:pos],query))
            value=money(qty_doc*cost)
            changes={ij["id"]:{"qty":qty_journal,"cost":cost}}
            after=ledger(journal,changes)
            plans=[]
            def plan_number(m,field,value):
                old=number(m,field,True)
                if old is None or old!=value:
                    plans.append((m,field,"NUMBER",value,text(old)))
            for f in ("UNITCOST","ACTUALCOST","CURRENCYUNITCOST"):
                plan_number(rm,f,cost)
            for f in ("LINECOST","CURRENCYLINECOST"):
                plan_number(rm,f,value)
            if not rm.isNull("LINECOST2"):
                plan_number(rm,"LINECOST2",value)
            for r in journal:
                if r["id"] in changes:
                    plan_number(r["mbo"],"UNITCOST",changes[r["id"]]["cost"])
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
                receipt=allocation[0].get("ref")
                message="SALVAT %s MATRECTRANS %s la %s, valoare %s; sursa FIFO %s." % (
                    kind,rm.getLong("MATRECTRANSID"),fmt(cost),fmt(value),
                    "INITIAL" if allocation[0].get("initial") or receipt is None else text(receipt))
                message+="\nNu modifica receptia/destinatia legata din acest pas."
                message+="\nRuleaza Check FIFO. Reconcilierea INVLIFOFIFOCOST ramane separata."
            try:
                if not refresh_table():
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
            if rm.getBoolean("CXSENTEBS") or not rm.isNull("FINCNTRLID"):
                fail("Retur transmis sau cu FINCNTRLID; corectie automata refuzata")
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
            journal=sorted([r for r in all_journal if r["group"]==context.getString("COMMODITYGROUP")],key=order)
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
                if not refresh_table():
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
            if first.getBoolean("CXSENTEBS") or not first.isNull("FINCNTRLID"):
                fail("Consum transmis sau cu FINCNTRLID; corectie automata refuzata")
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
            journal=sorted([r for r in all_journal if r["group"]==context.getString("COMMODITYGROUP")],key=order)
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
                fail("Stoc anterior insuficient; receptiile viitoare nu autorizeaza update")
            costs=set(a["cost"] for a in allocation)
            if len(costs)!=1:
                fail("Consumul %s are mai multe preturi FIFO; corectia fara linie nu se face automat" % first.getLong("MATUSETRANSID"))
            cost=allocation[0]["cost"]
            if cost<ZERO or ExactNumber(cost.fixed(3))!=cost:
                fail("Pretul FIFO nu poate fi scris")
            value=money((-qty)*cost)
            changes={ij["id"]:{"qty":qty,"cost":cost}}
            after=ledger(journal,changes)
            plans=[]
            def plan_number(m,field,value):
                old=number(m,field,True)
                if old is None or old!=value:
                    plans.append((m,field,"NUMBER",value,text(old)))
            for f in ("UNITCOST","ACTUALCOST","CURRENCYUNITCOST"):
                plan_number(first,f,cost)
            for f in ("LINECOST","CURRENCYLINECOST"):
                plan_number(first,f,value)
            if not first.isNull("LINECOST2"):
                plan_number(first,"LINECOST2",value)
            for r in journal:
                if r["id"] in changes:
                    plan_number(r["mbo"],"UNITCOST",changes[r["id"]]["cost"])
                plan_number(r["mbo"],"CXCURBAL",after[r["id"]])
            if not plans:
                message="Consumul %s este deja la pretul FIFO %s; nimic modificat. Linia de utilizare lipseste." % (first.getLong("MATUSETRANSID"),fmt(cost))
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
                    put_number(m,f,value)
                tx.save()
                for m,f,k,value,old in plans:
                    if different(number(m,f),value):
                        fail("Logica de salvare a suprascris planul pe %s.%s; rollback" % (m.getName(),f))
                commit_started=True
                tx.commit()
                committed=True
                message="SALVAT consum %s la %s, valoare %s. Linia de utilizare lipseste si nu a fost recreata." % (first.getLong("MATUSETRANSID"),fmt(cost),fmt(value))
            try:
                if not refresh_table():
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
            if m.getBoolean("CXSENTEBS"):
                fail("CXSENTEBS=1 pe MATUSETRANSID=%s; corectie automata refuzata" % mid)
            if not m.isNull("FINCNTRLID"):
                fail("FINCNTRLID completat pe MATUSETRANSID=%s; corectie automata refuzata" % mid)
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
        if different(total,number(line,"QUANTITY")):
            fail("Total MATUSETRANS diferit de cantitatea liniei; nu se forteaza documentul")
        if currency!=doc.getString("CURRENCYCODE") or number(doc,"EXCHANGERATE")!=ONE:
            fail("Moneda/conversie document neconforma")
        members.sort(key=lambda m:(m["date"],m["id"]))
        cxwhere=scope_where(context,"CXSTOCURI")
        cxset,raw=query("CXSTOCURI",cxwhere)
        all_journal=[journal_row(m) for m in raw]
        bind_screen_journal(context,all_journal)
        if any(m.getString("CURRENCYCODE")!=currency for m in raw):
            fail("Monede diferite intre jurnal si consum")
        journal=sorted([r for r in all_journal if r["group"]==context.getString("COMMODITYGROUP")],key=order)
        mids=set(m["id"] for m in members)
        targets=[r for r in journal if r["refmbo"]=="MATUSETRANS" and r["ref"] in mids]
        jbyref=dict((r["ref"],r) for r in targets)
        missing_journal=[mem for mem in members if mem["id"] not in jbyref]
        sset,splitrows=query("INVUSELINESPLIT","INVUSELINEID=%s" % lineid,MAX_SPLITS)
        splits=dict((m.getLong("INVUSELINESPLITID"),m) for m in splitrows)
        if not targets:
            fail("Niciun CXSTOCURI pentru consumurile liniei; nu pot determina FIFO")
        clicked=next((r for r in targets if r["id"]==context.getLong("CXSTOCURIID")),None)
        if clicked is None or text(clicked["mbo"].getRowStamp())!=text(context.getRowStamp()):
            fail("Rand apasat schimbat; refresh necesar")
        tids=set(r["id"] for r in targets)
        positions=[i for i,r in enumerate(journal) if r["id"] in tids]
        if any(r["id"] not in tids for r in journal[min(positions):max(positions)+1]):
            fail("Alte miscari intercalate intre consumurile cu jurnal")
        prior=journal[:min(positions)]
        layers=replay(prior,issue_of_returns(prior,query))
        allocation,short=consume(layers,total)
        if short>EPS:
            fail("Stoc anterior insuficient; receptiile viitoare nu autorizeaza update")
        segments=layer_segments(allocation)
        template=members[0]["mbo"]
        template_j=targets[0]
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
        # PAS 3: MATUSETRANS exista, CXSTOCURI lipseste
        if missing_journal:
            for mem in missing_journal:
                jm=cxset.addAtEnd(FLAGS)
                for f in ("ITEMNUM","LOCATION","ORGID","SITEID","COMMODITYGROUP","CURRENCYCODE",
                          "DESCRIPTION","GLCREDITACCT","GLDEBITACCT","ISSUETO","ROTASSETNUM"):
                    copy_value(template_j["mbo"],jm,f)
                put_number(jm,"CXQTY",-mem["old_qty"])
                put_number(jm,"UNITCOST",mem["old_cost"])
                jm.setValue("CXDOCUMENTDATE",mem["mbo"].getDate("ACTUALDATE"),FLAGS)
                jm.setValue("CXREF","ISSUE",FLAGS)
                jm.setValue("CXREFMBO","MATUSETRANS",FLAGS)
                jm.setValue("CXREFID",long(mem["id"]),FLAGS)
                jm.setValue("HASLD",1,FLAGS)
                if mem["mbo"].isNull("MATRECTRANSID"):
                    # INITIAL: fara receptie; CURBAL de pe tranzactie daca exista
                    bal=number(mem["mbo"],"CURBAL",True)
                    if bal is not None:
                        put_number(jm,"CXCURBAL",bal)
                else:
                    receipt=mem["mbo"].getLong("MATRECTRANSID")
                    bal=layer_balance(query,receipt,mem["date"],mem["id"],-mem["old_qty"],[])
                    put_number(jm,"CXCURBAL",bal)
                set_info(jm,"CXFIFOFIX PAS 3/3: CXSTOCURI creat pentru MATUSETRANS %s. Ruleaza Check FIFO." % mem["id"])
                service.log_info("CXFIFOFIXISSUE PAS3 create CXSTOCURI for MATUSETRANS %s qty=%s cost=%s" % (
                    mem["id"],fmt(-mem["old_qty"]),fmt(mem["old_cost"])))
            for mem in members:
                if mem["id"] not in jbyref:
                    continue
                jr=jbyref[mem["id"]]
                plan_number(jr["mbo"],"CXQTY",-mem["old_qty"])
                plan_number(jr["mbo"],"UNITCOST",mem["old_cost"])
                if not mem["mbo"].isNull("MATRECTRANSID"):
                    bal=layer_balance(query,mem["mbo"].getLong("MATRECTRANSID"),mem["date"],mem["id"],-mem["old_qty"],[])
                    plan_number(jr["mbo"],"CXCURBAL",bal)
            info=set_info(clicked["mbo"],"CXFIFOFIX PAS 3/3: jurnal completat pentru %s MATUSETRANS. Ruleaza Check FIFO." % len(missing_journal))
            plans.append((clicked["mbo"],"DESCRIPTION_LONGDESCRIPTION","TEXT",info,""))
            documents_before=document_values(doc,line)
            operation="PAS3 INVUSEID=%s INVUSELINEID=%s" % (invuseid,lineid)
            service.log_info("CXFIFOFIXISSUE PLAN "+VERSION+" "+operation)
            tx=MXServer.getMXServer().createMXTransaction()
            cxset.setFlag(MboConstants.NOSAVE,False)
            cxset.setMXTransaction(tx)
            tx.add(cxset)
            for m,f,kind,value,old in plans:
                apply_plan(m,f,kind,value)
            tx.save()
            if document_values(doc,line)!=documents_before or doc.isModified() or line.isModified():
                fail("Document/linie modificate in memorie de alta logica; rollback")
            commit_started=True
            tx.commit()
            committed=True
            message="PAS 3/3 SALVAT: create %s randuri CXSTOCURI pentru MATUSETRANS fara jurnal.\nNu apasa Save pe ecran (deja comis). Ruleaza Check FIFO." % len(missing_journal)
            for mem in missing_journal:
                message+="\nCXSTOCURI nou pentru MATUSETRANS %s: %s la %s." % (mem["id"],fmt(-mem["old_qty"]),fmt(mem["old_cost"]))
            service.log_info("CXFIFOFIXISSUE COMMIT "+VERSION+" "+message.replace("\n"," | "))
            try:
                if not refresh_table():
                    message+="\nRedeschide articolul pentru refresh."
            except Exception:
                message+="\nRefresh nereusit; redeschide articolul."
            return message
        if len(targets)!=len(members) or set(r["ref"] for r in targets)!=mids:
            fail("Lipseste randul unic CXSTOCURI pentru fiecare MATUSETRANS")
        recovery=False
        for mem in members:
            r=jbyref[mem["id"]]
            if r["kind"]!="ISSUE" or r["qty"] is None or r["qty"]>=ZERO or r["date"]!=mem["date"]:
                fail("Tip/directie/data neconforme RefID=%s; recuperarea nu schimba date" % mem["id"])
            recovery=recovery or different(r["qty"],-mem["old_qty"]) or different(r["cost"],mem["old_cost"],PRICE_EPS)
        mapped,creates=map_members(segments,members)
        new_total=sum((a["value"] for a in mapped),ZERO)+sum((c["value"] for c in creates),ZERO)
        if different(sum((a["qty"] for a in mapped),ZERO)+sum((c["qty"] for c in creates),ZERO),total):
            fail("Suma cantitatilor pe straturi difera de consumul original")
        used_splits=set()
        for mem in members:
            if not mem["mbo"].isNull("INVUSELINESPLITID"):
                used_splits.add(mem["mbo"].getLong("INVUSELINESPLITID"))
        free_splits=sorted([m for m in splitrows if m.getLong("INVUSELINESPLITID") not in used_splits],
                           key=lambda m: m.getLong("INVUSELINESPLITID"))
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
        source_base=number(members[0]["mbo"],"CURBAL",True)
        if source_base is None and any(not m["mbo"].isNull("CURBAL") for m in members):
            fail("CURBAL sursa partial: prima baza lipseste")
        running=source_base
        for a in mapped:
            a["source_balance"]=running
            if running is not None:
                running-=a["qty"]
        for c in creates:
            c["source_balance"]=running
            if running is not None:
                running-=c["qty"]
        # PAS 1: doar INVUSELINESPLIT noi/ajustate
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
                sm.setValue("CONTENTUID",split_contentuid(src_uid,new_split_idx),FLAGS)
                new_split_idx+=1
                created_split_ids.append(sm.getLong("INVUSELINESPLITID"))
                service.log_info("CXFIFOFIXISSUE PAS1 create split=%s qty=%s cost=%s" % (
                    sm.getLong("INVUSELINESPLITID"),fmt(c["qty"]),fmt(c["cost"])))
            info=set_info(clicked["mbo"],"CXFIFOFIX PAS 1/3: INVUSELINESPLIT actualizat (%s noi). Fara Save; reapeasa butonul 2." % len(created_split_ids))
            plans.append((clicked["mbo"],"DESCRIPTION_LONGDESCRIPTION","TEXT",info,""))
            documents_before=document_values(doc,line)
            operation="PAS1 INVUSEID=%s INVUSELINEID=%s" % (invuseid,lineid)
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
            message="PAS 1/3 SALVAT: INVUSELINESPLIT. Splituri noi: %s.\nNu apasa Save (deja comis; Save da BMXAA8229W). Reapeasa butonul 2 (PAS 2)." % (
                ",".join(text(i) for i in created_split_ids) if created_split_ids else "-")
            service.log_info("CXFIFOFIXISSUE COMMIT "+VERSION+" "+message.replace("\n"," | "))
            try:
                if not refresh_table():
                    message+="\nRedeschide articolul pentru refresh."
            except Exception:
                message+="\nRefresh nereusit; redeschide articolul."
            return message
        # PAS 2: creeaza MATUSETRANS, fara CXSTOCURI
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
                if a["source_balance"] is not None:
                    plan_number(m,"CURBAL",a["source_balance"])
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
            for idx,c in enumerate(creates):
                sm=c["split_mbo"]
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
                if c["source_balance"] is not None:
                    put_number(mm,"CURBAL",c["source_balance"])
                if c["receipt"] is None:
                    mm.setValueNull("MATRECTRANSID",FLAGS)
                else:
                    mm.setValue("MATRECTRANSID",long(c["receipt"]),FLAGS)
                mm.setValue("INVUSELINESPLITID",long(c["split_id"]),FLAGS)
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
                service.log_info("CXFIFOFIXISSUE PAS2 create MATUSETRANS=%s split=%s qty=%s cost=%s actualdate=+%smin" % (
                    c["new_id"],c["split_id"],fmt(-c["qty"]),fmt(c["cost"]),idx+1))
            ids=",".join(text(c["new_id"]) for c in created_rows)
            info=set_info(clicked["mbo"],"CXFIFOFIX PAS 2/3: MATUSETRANS noi %s (ACTUALDATE +N min). Fara Save; reapeasa butonul 2 pentru PAS 3." % ids)
            plans.append((clicked["mbo"],"DESCRIPTION_LONGDESCRIPTION","TEXT",info,""))
            documents_before=document_values(doc,line)
            operation="PAS2 INVUSEID=%s INVUSELINEID=%s" % (invuseid,lineid)
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
            message="PAS 2/3 SALVAT: MATUSETRANS noi %s.\nACTUALDATE = original + N minute.\nNu apasa Save (deja comis). Reapeasa butonul 2 (PAS 3 = CXSTOCURI)." % ids
            for c in created_rows:
                message+="\nMATUSETRANS %s: %s la %s; receptie %s; split %s." % (
                    c["new_id"],fmt(-c["qty"]),fmt(c["cost"]),receipt_label(c["receipt"]),c["split_id"])
            service.log_info("CXFIFOFIXISSUE COMMIT "+VERSION+" "+message.replace("\n"," | "))
            try:
                if not refresh_table():
                    message+="\nRedeschide articolul pentru refresh."
            except Exception:
                message+="\nRefresh nereusit; redeschide articolul."
            return message
        # cale normala: un strat / deja suficiente MATUSETRANS
        changes={}
        for a in mapped:
            jr=jbyref[a["member"]["id"]]
            changes[jr["id"]]={"qty":-a["qty"],"cost":a["cost"]}
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
            if a["source_balance"] is not None:
                plan_number(m,"CURBAL",a["source_balance"])
            plan_receipt(m,a["receipt"])
            # ponytail: fara creates nu atingem INVUSELINESPLIT (evita BMXAA8229W);
            # pretul pe split ramane eventual desincronizat pana la un PAS de split real.
        for r in journal:
            if r["id"] in changes:
                plan_number(r["mbo"],"CXQTY",changes[r["id"]]["qty"])
                plan_number(r["mbo"],"UNITCOST",changes[r["id"]]["cost"])
            plan_number(r["mbo"],"CXCURBAL",after[r["id"]])
        if not plans:
            return "MATUSETRANS si CXSTOCURI sunt deja conforme planului local; nimic modificat."
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
        operation="INVUSEID=%s INVUSELINEID=%s user=%s" % (invuseid,lineid,user.getUserName())
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
        message="SALVAT: INVUSE=%s; linie=%s; cantitate consum=%s; valoare FIFO=%s; actualizari=%s." % (
            doc.getString("INVUSENUM"),lineid,fmt(total),fmt(new_total),len(plans))
        if recovery:
            message+="\nSincronizare stare partiala: s-au completat numai diferentele fata de plan."
        for a in mapped:
            message+="\nMATUSETRANS %s: %s la %s; receptie %s." % (a["member"]["id"],fmt(-a["qty"]),fmt(a["cost"]),receipt_label(a["receipt"]))
        message+="\nReturul se corecteaza cand selectezi randul lui."
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
        message+="\nRuleaza Check FIFO. Reconcilierea INVLIFOFIFOCOST ramane separata."
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
    try:
        if not refresh_table():
            message+="\nRedeschide articolul pentru refresh."
    except Exception:
        message+="\nRefresh nereusit; redeschide articolul."
    return message

if "mbo" in globals() and "service" in globals():
    try:
        result=execute(mbo)
    except FixError as exc:
        result="CXFIFOFIXISSUE: "+text(exc)
    service.error(MESSAGE_GROUP,MESSAGE_KEY,[result])