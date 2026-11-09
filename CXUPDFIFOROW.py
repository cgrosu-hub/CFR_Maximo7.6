# SCRIPT: CXUPDFIFOROW
# AUTOR: Cristian Grosu
# VERSIUNE: 3.3-AFTER-RECEIPT
# Implicit: muta la maximul orelor din aceeasi zi (acelasi site/gestiune) + 1 minut.
# RETURN inainte de ISSUE (ISSUEID): data = ISSUE + 1 minut (MATUSETRANS+CXSTOCURI).
# ISSUE datat gresit inaintea unei intrari, DOAR daca |qty| < suma stoc pe toate
# intrarile FIFO (acelasi site/gestiune/grupa) si stocul anterior e insuficient:
# data = prima intrare ulterioara + 1 minut.
# INITIAL: doar CXDOCUMENTDATE. INVTRANS netratat.

from java.math import BigDecimal
from java.util import Calendar, Date
from java.text import SimpleDateFormat
from psdi.server import MXServer
from psdi.mbo import MboConstants, SqlFormat

DRY_RUN = False
APP = "INVENTOR"
OPTION = "CXUPDFIFOROW"
TABLE_ID = "1792055730066"
MAX_ROWS = 10000
SHIFT_MS = 60000
ZERO = BigDecimal("0")
TOL = BigDecimal("0.000001")
SUPPORTED = {
    "MATRECTRANS": ("MATRECTRANSID", "ACTUALDATE", ("RECEIPT", "TRANSFER", "SHIPTRANSFER", "SHIPRECEIPT", "RETURN", "VOIDRECEIPT", "SHIPRETURN", "SHIPCANCEL")),
    "MATUSETRANS": ("MATUSETRANSID", "ACTUALDATE", ("ISSUE", "RETURN"))
}

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
    return BigDecimal.valueOf(row.getDouble(field))

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
        if stamp(r) > tms or (stamp(r) == tms and r.getUniqueIDValue() >= tid):
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

def first_later_inbound(all_rows, target, after_ms):
    later = []
    for r in all_rows:
        if not same_fifo_book(r, target):
            continue
        if stamp(r) <= after_ms:
            continue
        if not is_inbound(r):
            continue
        if r.getString("CXREF") == "INITIAL":
            continue
        later.append(r)
    if not later:
        return None
    later.sort(key=lambda x: (stamp(x), x.getUniqueIDValue()))
    return later[0]

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

def check_shipment_order(source, new_ms):
    if source.getName() != "MATRECTRANS":
        return
    if not source.isNull("RECEIPTREF"):
        parent_id = source.getLong("RECEIPTREF")
        parent_set = source.getMboSet("$CXFIFO_PARENTDATE", "MATRECTRANS", "MATRECTRANSID=%s" % parent_id)
        parents = rows_of(parent_set)
        if len(parents) != 1 or parents[0].isNull("ACTUALDATE"):
            fail("Tranzactia-parinte lipsa sau fara ACTUALDATE")
        if parents[0].getDate("ACTUALDATE").getTime() > new_ms:
            fail("Noua data ar fi anterioara tranzactiei-parinte")
    if source.getString("ISSUETYPE") == "SHIPTRANSFER":
        children = source.getMboSet("$CXFIFO_CHILDDATES", "MATRECTRANS", "RECEIPTREF=%s" % source.getLong("MATRECTRANSID"))
        for child in rows_of(children):
            if child.isNull("ACTUALDATE") or child.getDate("ACTUALDATE").getTime() < new_ms:
                fail("Noua data a expedierii ar depasi o receptie/anulare legata")

def plan_balances(all_rows, linked, new_ms, require_before=True):
    moved_ids = set(r.getUniqueIDValue() for r in linked)
    affected = set(partition(r) for r in linked)
    scopes = set(scope(x) for x in linked)
    groups = dict((key, []) for key in affected)
    for r in all_rows:
        if scope(r) in scopes:
            key = partition(r)
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

def apply_dates_and_balances(linked, changed, after, new_ms, source=None, date_field=None):
    new_date = Date(new_ms)
    if source is not None and date_field is not None:
        source.setValue(date_field, new_date, MboConstants.NOACCESSCHECK)
    for r in linked:
        r.setValue("CXDOCUMENTDATE", new_date, MboConstants.NOACCESSCHECK)
        if stamp(r) != new_ms:
            fail("Validarile au schimbat data jurnalului")
    for r in changed:
        expected = after[r.getUniqueIDValue()]
        r.setValue("CXCURBAL", expected.doubleValue(), MboConstants.NOACCESSCHECK)
        if different(number(r, "CXCURBAL"), expected):
            fail("Precizia CXCURBAL nu pastreaza rezultatul")
    if source is not None and date_field is not None:
        if source.getDate(date_field).getTime() != new_ms:
            fail("Validarile au schimbat data sursei")

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
            root.save()
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
            # ISSUE inaintea unei receptii, doar daca |qty| < stoc total pe intrari
            # si stocul cronologic anterior e insuficient (data gresita, nu lipsa reala).
            if date_mode == "DAYMAX" and kind == "ISSUE" and table == "MATUSETRANS":
                consumed = number(target, "CXQTY").abs()
                inbound = total_inbound_stock(all_rows, target)
                prior = stock_before(all_rows, target)
                if consumed.compareTo(inbound) < 0 and prior.compareTo(consumed) < 0:
                    nxt = first_later_inbound(all_rows, target, old_ms)
                    if nxt is not None:
                        new_ms = stamp(nxt) + SHIFT_MS
                        date_mode = "AFTER_RECEIPT"
                        daymax_blocked = False
                        require_before = False
            if date_mode == "DAYMAX" and daymax_blocked:
                fail("Maximul zilei + un minut depaseste ziua curenta; nimic modificat")
            check_shipment_order(source, new_ms)
            for r in linked:
                if stamp(r) != old_ms:
                    fail("Randurile aceleiasi surse au date diferite")
            after, changed = plan_balances(all_rows, linked, new_ms, require_before)
            formatter = SimpleDateFormat("dd.MM.yyyy HH:mm:ss")
            formatter.setTimeZone(timezone)
            mode_txt = {"AFTER_ISSUE": "ISSUE+1min", "AFTER_RECEIPT": "receptie+1min"}.get(date_mode, "zi+1min")
            message = "%s/%s RefID=%s (%s): %s -> %s; jurnal date=%s; solduri=%s; sursa %s.%s" % (
                table, kind, refid, mode_txt, formatter.format(Date(old_ms)), formatter.format(Date(new_ms)),
                len(linked), len(changed), table, date_field)
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
            apply_dates_and_balances(linked, changed, after, new_ms, source, date_field)
            root.save()
            service.log_info("CXUPDFIFOROW user=%s CXSTOCURIID=%s; %s" % (
                context.getUserInfo().getUserName(), target_id, message))
    finally:
        close_set(verify)
        close_set(root)

    try:
        if not refresh_table():
            return "SALVAT. " + message + ". Redeschide articolul si ruleaza Check FIFO"
    except Exception:
        return "SALVAT. " + message + ". Refresh nereusit; redeschide articolul si ruleaza Check FIFO"
    return "SALVAT. " + message + ". Ruleaza Check FIFO"

try:
    result = execute(mbo)
except ValueError as exc:
    result = "Actiune oprita: " + str(exc)
service.error("CXFIFO", "ROWRESULT", [result])
