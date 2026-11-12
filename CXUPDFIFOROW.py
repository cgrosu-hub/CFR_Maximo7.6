# -*- coding: utf-8 -*-
# SCRIPT: CXUPDFIFOROW
# AUTOR ORIGINAL: Cristian Grosu; revizie 3.8-ATOMIC-SAME-DAY
# Reordonare in aceeasi zi locala, pe minute libere; data sursei si jurnalului concorda.
# Acoperirea se calculeaza pe stocul net disponibil, inclusiv receptii cumulative.
# CXCURBAL se recalculeaza pe grupa, pret si receptie. Fara conversie prin double.
# Sursa, receptiile legate si jurnalul se salveaza atomic; rollback la eroare.
# Nu apasa Save dupa rezultat. Check FIFO dupa corectiile de data.

from java.math import BigDecimal
from java.util import Calendar, Date
from java.text import SimpleDateFormat
from psdi.server import MXServer
from psdi.mbo import MboConstants, SqlFormat
from psdi.util import MaxType
from java.util import Locale,TimeZone
from java.text import NumberFormat,ParsePosition

DRY_RUN = False
APP = "INVENTOR"
OPTION = "CXUPDFIFOROW"
TABLE_ID = "1792055730066"
MAX_ROWS = 10000
SHIFT_MS = 60000
ZERO = BigDecimal("0")
TOL = BigDecimal("0.000001")
VERSION = "3.8-ATOMIC-SAME-DAY"
COVERING_RECEIPT = ("RECEIPT", "SHIPRECEIPT", "TRANSFER")
DATE_FLAGS = MboConstants.NOACCESSCHECK | MboConstants.NOVALIDATION_AND_NOACTION
SUPPORTED = {
    "MATRECTRANS": ("MATRECTRANSID", "ACTUALDATE", ("RECEIPT", "TRANSFER", "SHIPTRANSFER", "SHIPRECEIPT", "RETURN", "VOIDRECEIPT", "SHIPRETURN", "SHIPCANCEL")),
    "MATUSETRANS": ("MATUSETRANSID", "ACTUALDATE", ("ISSUE", "RETURN"))
}


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


def after_receipt_exit(kind, table):
    return ((kind == "ISSUE" and table == "MATUSETRANS") or
            (kind == "SHIPTRANSFER" and table == "MATRECTRANS"))

def fail(message):
    raise ValueError(message)

def close_set(ms):
    if ms is not None:
        try:
            ms.cleanup()
        finally:
            ms.close()

def number(row, field):
    if row.isNull(field):
        fail("Camp numeric lipsa: " + field)
    raw=row.getMboValue(field).getCurrentValue().asString().strip()
    try:
        return BigDecimal(raw)
    except Exception:
        parser=NumberFormat.getNumberInstance(row.getUserInfo().getLocale())
        parser.setParseBigDecimal(True)
        pos=ParsePosition(0)
        value=parser.parse(raw,pos)
        if value is None or pos.getIndex()!=len(raw):
            fail("Numar neinterpretabil: "+field)
        return value

def canonical(value):
    return str(value.stripTrailingZeros().toPlainString())

def different(a, b):
    return a.subtract(b).abs().compareTo(TOL) > 0

def rows_of(ms):
    rows = []
    r = ms.moveFirst()
    while r is not None:
        rows.append(r)
        if len(rows) > MAX_ROWS:
            fail("Selectia depaseste limita de %s randuri" % MAX_ROWS)
        r = ms.moveNext()
    return rows

def open_item(context):
    ms = MXServer.getMXServer().getMboSet("CXSTOCURI", context.getUserInfo())
    try:
        sql = SqlFormat("ITEMNUM=:1")
        sql.setObject(1, "CXSTOCURI", "ITEMNUM", context.getString("ITEMNUM"))
        ms.setWhere(sql.format())
        ms.reset()
        return ms
    except Exception:
        close_set(ms)
        raise

def signature(rows):
    return sorted((r.getUniqueIDValue(), str(r.getRowStamp())) for r in rows)

def partition(r):
    return (r.getString("ITEMNUM"), r.getString("SITEID"), r.getString("LOCATION"),
            r.getString("COMMODITYGROUP"), canonical(number(r, "UNITCOST")))

def scope(r):
    return (r.getString("SITEID"), r.getString("LOCATION"))

def same_fifo_book(r, target):
    return (scope(r) == scope(target) and
            r.getString("COMMODITYGROUP") == target.getString("COMMODITYGROUP"))

def is_inbound(r):
    if r.getString("CXREF") == "INITIAL":
        return True
    if r.isNull("CXQTY"):
        return False
    return number(r, "CXQTY").compareTo(ZERO) > 0

def total_inbound_stock(all_rows, target):
    # suma soldurilor de pe toate intrarile FIFO din cartea locala
    total = ZERO
    for r in all_rows:
        if not same_fifo_book(r, target):
            continue
        if r.getString("CXREF") == "INITIAL":
            if r.isNull("CXCURBAL"):
                fail("INITIAL fara CXCURBAL; nu pot evalua stocul total pe intrari")
            total = total.add(number(r, "CXCURBAL"))
        elif is_inbound(r):
            total = total.add(number(r, "CXQTY"))
    return total

def stock_before(all_rows, target):
    tid = target.getUniqueIDValue()
    tms = stamp(target)
    bal = ZERO
    rows = [r for r in all_rows if same_fifo_book(r, target)]
    for r in sorted(rows, key=lambda x: (stamp(x), 0 if x.isNull("CXREFID") else x.getLong("CXREFID"), x.getUniqueIDValue())):
        if journal_key(r) >= journal_key(target):
            break
        if r.getString("CXREF") == "INITIAL":
            if r.isNull("CXCURBAL"):
                fail("INITIAL fara CXCURBAL inaintea consumului")
            bal = bal.add(number(r, "CXCURBAL"))
        else:
            if r.isNull("CXQTY"):
                fail("CXQTY lipsa pe CXSTOCURIID=%s" % r.getUniqueIDValue())
            bal = bal.add(number(r, "CXQTY"))
    return bal

def journal_key(r):
    # Ordine jurnal: data, CXREFID, CXSTOCURIID (aceeasi ora => receptia de dupa e eligibila).
    return (stamp(r),
            0 if r.isNull("CXREFID") else r.getLong("CXREFID"),
            r.getUniqueIDValue())

def first_covering_inbound(all_rows, target, after_ms, needed):
    bal=stock_before(all_rows,target)
    for r in sorted([x for x in all_rows if same_fifo_book(x,target) and journal_key(x)>journal_key(target)],key=journal_key):
        if r.getString("CXREF")=="INITIAL":
            fail("INITIAL dupa miscari; reordonare nesigura")
        bal=bal.add(number(r,"CXQTY"))
        if r.getString("CXREF") in COVERING_RECEIPT and is_inbound(r) and bal.compareTo(needed)>=0:
            return r
    return None

def stamp(r):
    if r.isNull("CXDOCUMENTDATE"):
        fail("CXDOCUMENTDATE lipsa pentru CXSTOCURIID=%s" % r.getUniqueIDValue())
    return r.getDate("CXDOCUMENTDATE").getTime()

def day_limits(date, timezone):
    cal = Calendar.getInstance(timezone)
    cal.setTime(date)
    cal.set(Calendar.HOUR_OF_DAY, 0)
    cal.set(Calendar.MINUTE, 0)
    cal.set(Calendar.SECOND, 0)
    cal.set(Calendar.MILLISECOND, 0)
    start = cal.getTimeInMillis()
    cal.add(Calendar.DATE, 1)
    return start, cal.getTimeInMillis()

def ledger(rows, moved_ids=None, new_ms=None):
    moved_ids = moved_ids or set()
    def key(r):
        return (new_ms if r.getUniqueIDValue() in moved_ids else stamp(r),
                0 if r.isNull("CXREFID") else r.getLong("CXREFID"),
                r.getUniqueIDValue())
    result = {}
    running = ZERO
    initial_seen = False
    movement_seen = False
    for r in sorted(rows, key=key):
        if r.getString("CXREF") == "INITIAL":
            if initial_seen or movement_seen:
                fail("INITIAL multiplu sau dupa miscari; recalcul oprit")
            running = number(r, "CXCURBAL")
            initial_seen = True
        else:
            running = running.add(number(r, "CXQTY"))
            movement_seen = True
        result[r.getUniqueIDValue()] = running
    return result

def validate_source(source, rows, table):
    if source.isNull("ACTUALDATE"):
        fail("ACTUALDATE lipsa pe tranzactia-sursa")
    source_date = source.getDate("ACTUALDATE").getTime()
    source_qty = number(source, "QUANTITY")
    for r in rows:
        if source.getString("ITEMNUM") != r.getString("ITEMNUM") or source.getString("ISSUETYPE") != r.getString("CXREF"):
            fail("Articol/tip diferit intre jurnal si sursa")
        if stamp(r) != source_date:
            fail("Data jurnalului difera deja de ACTUALDATE; analiza separata necesara")
        if different(number(r, "UNITCOST"), number(source, "UNITCOST")):
            fail("Pretul jurnalului difera de sursa")
        if table == "MATUSETRANS":
            if (source.getString("SITEID"), source.getString("STORELOC")) != scope(r):
                fail("Site/gestiune diferite fata de MATUSETRANS")
            if different(number(r, "CXQTY"), source_qty):
                fail("Cantitate diferita fata de MATUSETRANS")
        else:
            src = (source.getString("FROMSITEID"), source.getString("FROMSTORELOC"))
            dst = (source.getString("SITEID"), source.getString("TOSTORELOC"))
            if scope(r) not in (src, dst) or src == dst:
                fail("Ruta MATRECTRANS lipsa sau ambigua")
            if different(number(r, "CXQTY").abs(), source_qty.abs()):
                fail("Cantitate absoluta diferita fata de MATRECTRANS")
        if "CXFIFO_FIX1|" in r.getString("DESCRIPTION_LONGDESCRIPTION"):
            fail("Exista istoric de corectie de pret pe un rand legat; data nu se schimba automat")

def check_shipment_parent(source, new_ms):
    if source.getName() != "MATRECTRANS" or source.isNull("RECEIPTREF"):
        return
    parent_id = source.getLong("RECEIPTREF")
    parent_set = source.getMboSet("$CXFIFO_PARENTDATE", "MATRECTRANS", "MATRECTRANSID=%s" % parent_id)
    parents = rows_of(parent_set)
    if len(parents) != 1 or parents[0].isNull("ACTUALDATE"):
        fail("Tranzactia-parinte lipsa sau fara ACTUALDATE")
    if parents[0].getDate("ACTUALDATE").getTime() > new_ms:
        fail("Noua data ar fi anterioara tranzactiei-parinte")

def linked_shipment_children_to_bump(source, new_ms):
    # Receptii/anulari cu RECEIPTREF pe acest SHIPTRANSFER, datate inaintea noii expedieri.
    if source.getName() != "MATRECTRANS" or source.getString("ISSUETYPE") != "SHIPTRANSFER":
        return []
    children = source.getMboSet("$CXFIFO_CHILDDATES", "MATRECTRANS",
                                "RECEIPTREF=%s" % source.getLong("MATRECTRANSID"))
    bump = []
    for child in rows_of(children):
        if child.isNull("ACTUALDATE"):
            fail("Receptie/anulare legata fara ACTUALDATE MATRECTRANSID=%s" % child.getUniqueIDValue())
        if child.getDate("ACTUALDATE").getTime() < new_ms:
            bump.append(child)
    return bump

def journal_rows_for_refs(all_rows, table, ref_ids):
    if not ref_ids:
        return []
    wanted = set(ref_ids)
    found = []
    for r in all_rows:
        if r.getString("CXREFMBO") != table or r.isNull("CXREFID"):
            continue
        if r.getLong("CXREFID") in wanted:
            found.append(r)
    return found


def receipt_partitions(all_rows):
    opened=[]
    def query(name,where):
        ms=MXServer.getMXServer().getMboSet(name,all_rows[0].getUserInfo())
        opened.append(ms)
        ms.setFlag(MboConstants.NOSAVE,True)
        ms.setWhere(where)
        ms.reset()
        return ms,rows_of(ms)
    try:
        norm=[]
        for m in all_rows:
            norm.append({"id":m.getUniqueIDValue(),"ref":None if m.isNull("CXREFID") else m.getLong("CXREFID"),
                "refmbo":m.getString("CXREFMBO"),"kind":m.getString("CXREF"),"date":stamp(m),
                "qty":None if m.isNull("CXQTY") else number(m,"CXQTY"),"cost":number(m,"UNITCOST"),
                "balance":None if m.isNull("CXCURBAL") else number(m,"CXCURBAL"),
                "group":m.getString("SITEID")+"/"+m.getString("LOCATION")+"/"+m.getString("COMMODITYGROUP"),
                "item":m.getString("ITEMNUM"),"site":m.getString("SITEID"),"location":m.getString("LOCATION")})
        cx_enrich_receipts(norm,query)
        balances,keys,errors=cx_receipt_balances(norm,ZERO)
        if errors:
            fail("Provenienta pe receptie nedeterminabila; corecteaza consumurile inaintea datei")
        return keys
    finally:
        for ms in reversed(opened):
            close_set(ms)


def plan_balances(all_rows, linked, new_ms, require_before=True):
    moved_ids = set(r.getUniqueIDValue() for r in linked)
    receipt_keys=receipt_partitions(all_rows)
    def receipt_partition(r):
        return partition(r)[:4]+receipt_keys[r.getUniqueIDValue()][2:]
    affected = set(receipt_partition(r)+(canonical(number(r,"UNITCOST")),) for r in linked)
    scopes = set(scope(x) for x in linked)
    groups = dict((key, []) for key in affected)
    for r in all_rows:
        if scope(r) in scopes:
            key = receipt_partition(r)+(canonical(number(r,"UNITCOST")),)
            if key in groups:
                groups[key].append(r)
    after = {}
    for key, group_rows in groups.items():
        if require_before:
            before = ledger(group_rows)
            for r in group_rows:
                if different(number(r, "CXCURBAL"), before[r.getUniqueIDValue()]):
                    fail("Sold existent neconform CXSTOCURIID=%s; nimic salvat" % r.getUniqueIDValue())
        after.update(ledger(group_rows, moved_ids, new_ms))
    changed = [r for group_rows in groups.values() for r in group_rows
               if different(number(r, "CXCURBAL"), after[r.getUniqueIDValue()])]
    return after, changed

def apply_dates_and_balances(linked, changed, after, new_ms, source=None, date_field=None, extra_sources=None):
    new_date = Date(new_ms)
    if source is not None and date_field is not None:
        source.setValue(date_field, new_date, DATE_FLAGS)
    for extra in (extra_sources or []):
        extra.setValue("ACTUALDATE", new_date, DATE_FLAGS)
        if extra.getDate("ACTUALDATE").getTime() != new_ms:
            fail("Validarile au schimbat data receptiei/anularii legate")
    for r in linked:
        r.setValue("CXDOCUMENTDATE", new_date, DATE_FLAGS)
        if stamp(r) != new_ms:
            fail("Validarile au schimbat data jurnalului")
    for r in changed:
        expected = after[r.getUniqueIDValue()]
        mv=r.getMboValue("CXCURBAL")
        typed=MaxType.createMaxType(Locale.US,TimeZone.getTimeZone("UTC"),mv.getType())
        typed.setScale(mv.getScale())
        typed.setValue(canonical(expected))
        if BigDecimal(typed.asString()).compareTo(expected)!=0:
            fail("Precizia CXCURBAL nu pastreaza rezultatul")
        r.setValue("CXCURBAL", typed, DATE_FLAGS)
        if different(number(r, "CXCURBAL"), expected):
            fail("Precizia CXCURBAL nu pastreaza rezultatul")
    if source is not None and date_field is not None:
        if source.getDate(date_field).getTime() != new_ms:
            fail("Validarile au schimbat data sursei")

def verify_saved_dates(linked,changed,after,new_ms,sources=None):
    for r in linked:
        if stamp(r)!=new_ms:
            fail("Data jurnalului suprascrisa la save")
    for r in changed:
        if number(r,"CXCURBAL").compareTo(after[r.getUniqueIDValue()])!=0:
            fail("Sold suprascris la save")
    for m in sources or []:
        if m.getDate("ACTUALDATE").getTime()!=new_ms:
            fail("Data sursei suprascrisa la save")

def refresh_table():
    from psdi.common.context import UIContext
    ui = UIContext.getCurrentContext()
    session = ui.getWebClientSession() if ui else None
    bean = session.getDataBean(TABLE_ID) if session else None
    if bean is None:
        return False
    bean.reset()
    bean.refreshTable()
    return True

def execute(context):
    if context is None or context.getName() != "CXSTOCURI":
        fail("Butonul trebuie sa transmita randul CXSTOCURI")
    if not context.getProfile().hasAppOption(APP, OPTION):
        fail("Lipseste dreptul " + APP + "/" + OPTION)
    if context.toBeAdded() or context.isModified() or context.toBeDeleted() or context.getThisMboSet().toBeSaved():
        fail("Salveaza sau renunta la modificarile nesalvate din jurnal")
    owner = context.getOwner()
    if owner is not None and (owner.toBeAdded() or owner.isModified()):
        fail("Inregistrarea parinte are modificari nesalvate")

    table = context.getString("CXREFMBO")
    kind = context.getString("CXREF")
    is_initial = kind == "INITIAL"

    if is_initial:
        for field in ("ITEMNUM", "SITEID", "LOCATION", "CXDOCUMENTDATE"):
            if context.isNull(field):
                fail("Camp obligatoriu lipsa: " + field)
        if context.isNull("CXCURBAL"):
            fail("CXCURBAL lipsa pe INITIAL")
    else:
        if table not in SUPPORTED:
            fail("Sursa netratata: %s/%s; INVTRANS nu este modificat" % (table, kind))
        pk, date_field, kinds = SUPPORTED[table]
        if kind not in kinds:
            fail("Tip netratat: " + kind)
        for field in ("ITEMNUM", "SITEID", "LOCATION", "CXREFID", "CXDOCUMENTDATE"):
            if context.isNull(field):
                fail("Camp obligatoriu lipsa: " + field)
        if number(context, "CXQTY").compareTo(ZERO) == 0:
            fail("Tranzactie cu cantitate zero; reordonarea nu este aplicata")

    root = None
    verify = None
    tx = None
    committed = False
    commit_started = False
    try:
        root = open_item(context)
        all_rows = rows_of(root)
        original_signature = signature(all_rows)
        target_id = context.getUniqueIDValue()
        target_list = [r for r in all_rows if r.getUniqueIDValue() == target_id]
        if len(target_list) != 1:
            fail("Rand tinta lipsa sau duplicat")
        target = target_list[0]
        if str(target.getRowStamp()) != str(context.getRowStamp()):
            fail("Rand schimbat concurent; reimprospateaza tabelul")
        if "CXFIFO_FIX1|" in target.getString("DESCRIPTION_LONGDESCRIPTION"):
            fail("Exista istoric de corectie de pret pe rand; data nu se schimba automat")

        timezone = context.getUserInfo().getTimeZone()
        old_ms = stamp(target)
        start_ms, end_ms = day_limits(target.getDate("CXDOCUMENTDATE"), timezone)
        same_day = [r for r in all_rows if scope(r) == scope(target) and start_ms <= stamp(r) < end_ms]
        maximum_ms = max(stamp(r) for r in same_day)
        new_ms = maximum_ms + SHIFT_MS
        date_mode = "DAYMAX"
        if new_ms >= end_ms:
            # RETURN-before-ISSUE poate sari peste sfarsitul zilei; DAYMAX nu.
            daymax_blocked = True
        else:
            daymax_blocked = False

        if is_initial:
            if daymax_blocked:
                fail("Maximul zilei + un minut depaseste ziua curenta; nimic modificat")
            # INITIAL nu are tabel-sursa; mutam doar randul de jurnal selectat.
            linked = [target]
            # Nu permite INITIAL dupa miscari in acelasi partition dupa mutare.
            part = partition(target)
            peers = [r for r in all_rows if partition(r) == part]
            def eff(r):
                return new_ms if r.getUniqueIDValue() == target_id else stamp(r)
            ordered = sorted(peers, key=lambda r: (eff(r), 0 if r.isNull("CXREFID") else r.getLong("CXREFID"), r.getUniqueIDValue()))
            seen_move = False
            for r in ordered:
                if r.getString("CXREF") == "INITIAL":
                    if seen_move:
                        fail("Noua data ar pune INITIAL dupa miscari pe acelasi pret; nimic modificat")
                else:
                    seen_move = True
            after, changed = plan_balances(all_rows, linked, new_ms)
            formatter = SimpleDateFormat("dd.MM.yyyy HH:mm:ss")
            formatter.setTimeZone(timezone)
            message = "INITIAL CXSTOCURIID=%s: %s -> %s; jurnal date=1; solduri=%s; doar CXDOCUMENTDATE" % (
                target_id, formatter.format(Date(old_ms)), formatter.format(Date(new_ms)), len(changed))
            if DRY_RUN:
                return "SIMULARE; nimic salvat. " + message
            verify = open_item(context)
            if signature(rows_of(verify)) != original_signature:
                fail("Jurnal modificat concurent; nimic salvat")
            close_set(verify)
            verify = None
            apply_dates_and_balances(linked, changed, after, new_ms)
            tx=MXServer.getMXServer().createMXTransaction()
            root.setMXTransaction(tx)
            tx.add(root)
            tx.save()
            verify_saved_dates(linked,changed,after,new_ms)
            commit_started=True
            tx.commit()
            committed=True
            service.log_info("CXUPDFIFOROW user=%s CXSTOCURIID=%s; %s" % (
                context.getUserInfo().getUserName(), target_id, message))
        else:
            refid = target.getLong("CXREFID")
            linked = [r for r in all_rows if r.getString("CXREFMBO") == table and
                      not r.isNull("CXREFID") and r.getLong("CXREFID") == refid]
            if not linked:
                fail("Nu exista randuri de jurnal pentru sursa selectata")
            source_set = target.getMboSet("$CXFIFO_DATESOURCE", table, "%s=%s" % (pk, refid))
            sources = rows_of(source_set)
            if len(sources) != 1:
                fail("Tranzactia-sursa nu este unica/accesibila")
            source = sources[0]
            source_rowstamp = str(source.getRowStamp())
            validate_source(source, linked, table)
            require_before = True
            # RETURN inainte de ISSUE: ancora pe ACTUALDATE consum + 1 minut
            if kind == "RETURN" and table == "MATUSETRANS":
                if source.isNull("ISSUEID"):
                    fail("Returul nu are ISSUEID; nu pot ancora data pe consum")
                issue_id = source.getLong("ISSUEID")
                issue_set = source.getMboSet("$CXFIFO_RETURNISSUE", "MATUSETRANS", "MATUSETRANSID=%s" % issue_id)
                issues = rows_of(issue_set)
                if len(issues) != 1 or issues[0].isNull("ACTUALDATE"):
                    fail("Consumul %s lipsa sau fara ACTUALDATE" % issue_id)
                issue_ms = issues[0].getDate("ACTUALDATE").getTime()
                if old_ms < issue_ms:
                    new_ms = issue_ms + SHIFT_MS
                    date_mode = "AFTER_ISSUE"
                    daymax_blocked = False
            # ISSUE/SHIPTRANSFER: stoc anterior insuficient -> dupa prima receptie care acopera |qty|.
            if date_mode == "DAYMAX" and after_receipt_exit(kind, table):
                consumed = number(target, "CXQTY").abs()
                inbound = total_inbound_stock(all_rows, target)
                prior = stock_before(all_rows, target)
                if prior.compareTo(consumed) < 0:
                    if consumed.compareTo(inbound) > 0:
                        fail("Stoc total pe intrari (%s) < |iesire| %s; nu pot muta dupa o receptie" % (
                            canonical(inbound), canonical(consumed)))
                    nxt = first_covering_inbound(all_rows, target, old_ms, consumed)
                    if nxt is None:
                        fail("Nu exista receptie ulterioara (RECEIPT/SHIPRECEIPT/TRANSFER) cu cantitate >= %s" %
                             canonical(consumed))
                    new_ms = stamp(nxt) + SHIFT_MS
                    date_mode = "AFTER_RECEIPT"
                    daymax_blocked = False
                    require_before = False
                    service.log_info("CXUPDFIFOROW AFTER_RECEIPT cover CXREF=%s RefID=%s qty=%s -> +1min" % (
                        nxt.getString("CXREF"),
                        "" if nxt.isNull("CXREFID") else str(nxt.getLong("CXREFID")),
                        canonical(number(nxt, "CXQTY"))))
            if date_mode == "DAYMAX" and daymax_blocked:
                fail("Maximul zilei + un minut depaseste ziua curenta; nimic modificat")
            if not start_ms<=new_ms<end_ms:
                fail("Reordonarea ar schimba ziua tranzactiei; analiza manuala necesara")
            occupied=set(stamp(r)//SHIFT_MS for r in all_rows if scope(r)==scope(target) and r not in linked)
            new_ms=(new_ms//SHIFT_MS)*SHIFT_MS
            while new_ms//SHIFT_MS in occupied:
                new_ms+=SHIFT_MS
            if new_ms>=end_ms:
                fail("Nu exista minut liber in aceeasi zi")
            if after_receipt_exit(kind,table):
                available=ZERO
                for r in sorted(all_rows,key=journal_key):
                    if r in linked or not same_fifo_book(r,target) or stamp(r)>=new_ms:
                        continue
                    available=available.add(number(r,"CXCURBAL") if r.getString("CXREF")=="INITIAL" else number(r,"CXQTY"))
                if available.compareTo(number(target,"CXQTY").abs())<0:
                    fail("Minutul liber ales nu mai are stoc anterior suficient; nicio data salvata")
            check_shipment_parent(source, new_ms)
            child_sources = linked_shipment_children_to_bump(source, new_ms)
            for child in child_sources:
                cstart,cend=day_limits(child.getDate("ACTUALDATE"),timezone)
                if not cstart<=new_ms<cend:
                    fail("Mutarea receptiei legate ar schimba ziua ei")
            child_ids = [c.getLong("MATRECTRANSID") for c in child_sources]
            child_journal = journal_rows_for_refs(all_rows, "MATRECTRANS", child_ids)
            moved = list(linked)
            for r in child_journal:
                if r.getUniqueIDValue() not in set(x.getUniqueIDValue() for x in moved):
                    moved.append(r)
            for r in linked:
                if stamp(r) != old_ms:
                    fail("Randurile aceleiasi surse au date diferite")
            after, changed = plan_balances(all_rows, moved, new_ms, require_before)
            formatter = SimpleDateFormat("dd.MM.yyyy HH:mm:ss")
            formatter.setTimeZone(timezone)
            mode_txt = {"AFTER_ISSUE": "ISSUE+1min", "AFTER_RECEIPT": "receptie+1min"}.get(date_mode, "zi+1min")
            message = "%s/%s RefID=%s (%s): %s -> %s; jurnal date=%s; solduri=%s; receptii legate=%s; sursa %s.%s" % (
                table, kind, refid, mode_txt, formatter.format(Date(old_ms)), formatter.format(Date(new_ms)),
                len(moved), len(changed), len(child_sources), table, date_field)
            if DRY_RUN:
                return "SIMULARE; nimic salvat. " + message
            verify = open_item(context)
            if signature(rows_of(verify)) != original_signature:
                fail("Jurnal modificat concurent; nimic salvat")
            close_set(verify)
            verify = MXServer.getMXServer().getMboSet(table, context.getUserInfo())
            verify.setWhere("%s=%s" % (pk, refid))
            verify.reset()
            fresh = rows_of(verify)
            if len(fresh) != 1 or str(fresh[0].getRowStamp()) != source_rowstamp:
                fail("Sursa modificata concurent; nimic salvat")
            close_set(verify)
            verify = None
            apply_dates_and_balances(moved, changed, after, new_ms, source, date_field, child_sources)
            tx=MXServer.getMXServer().createMXTransaction()
            saved_sets=[root]
            for mbo_src in [source]+list(child_sources):
                ms=mbo_src.getThisMboSet()
                if ms not in saved_sets:
                    saved_sets.append(ms)
            for ms in saved_sets:
                ms.setMXTransaction(tx)
                tx.add(ms)
            tx.save()
            verify_saved_dates(moved,changed,after,new_ms,[source]+list(child_sources))
            commit_started=True
            tx.commit()
            committed=True
            service.log_info("CXUPDFIFOROW user=%s CXSTOCURIID=%s; %s" % (
                context.getUserInfo().getUserName(), target_id, message))
    except Exception as exc:
        if not committed:
            cx_rollback(tx)
        if commit_started and not committed:
            fail("Rezultat COMMIT incert; reciteste datele inainte de repetare: "+str(exc))
        if committed:
            fail("Datele AU FOST SALVATE; eroare ulterioara: "+str(exc))
        raise
    finally:
        close_set(verify)
        close_set(root)

    try:
        if not refresh_table():
            return "SALVAT. " + message + ". Redeschide articolul si ruleaza Check FIFO"
    except Exception:
        return "SALVAT. " + message + ". Refresh nereusit; redeschide articolul si ruleaza Check FIFO"
    return "SALVAT. " + message + ". Ruleaza Check FIFO"

if "mbo" in globals() and "service" in globals():
    try:
        result = execute(mbo)
    except ValueError as exc:
        result = "Actiune oprita: " + str(exc)
    service.error("CXFIFO", "ROWRESULT", [result])
