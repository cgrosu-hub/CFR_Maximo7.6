# -*- coding: utf-8 -*-
# SCRIPT: CXSTOCURIUPDATECURBAL
# AUTORI ORIGINALI: Fernando Prajitura / Cristian Grosu
# REVIZIE: 2026.11.13-RECEIPT-LEDGER
# Cron task aliniat la cele trei scripturi FIFO: sold pe grupa, pret si receptie.
# Pastreaza setarile cfr.inventory.updateAllCxStocuri / numHistoryDaysToUpdate.
# Provenienta ambigua: partitia este sarita, fara cumulare artificiala pe pret.

from java.math import BigDecimal
from java.text import NumberFormat, ParsePosition, SimpleDateFormat
from java.util import Locale, TimeZone
from psdi.server import MXServer
from psdi.mbo import MboConstants, SqlFormat
from psdi.util import MaxType

ZERO = BigDecimal("0")
TOL = BigDecimal("0.000001")
MAX_ROWS = 50000  # ponytail: peste prag partitia e sarita; se ridica plafonul daca un articol il depaseste
FLAGS = MboConstants.NOACCESSCHECK | MboConstants.NOVALIDATION_AND_NOACTION
SKIP_LOG_LIMIT = 50


class Skip(Exception):
    pass



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




def running_balances(rows):
    ordered = sorted(rows, key=lambda r: (r["date"], 0 if r["ref"] is None else r["ref"], r["id"]))
    running = ZERO
    initial_seen = False
    movement_seen = False
    expected = {}
    for r in ordered:
        if not r["date"]:
            raise ValueError("CXDOCUMENTDATE lipsa pe CXSTOCURIID=%s" % r["id"])
        if r["kind"] == "INITIAL":
            if initial_seen or movement_seen or r["balance"] is None:
                raise ValueError("INITIAL ambiguu sau fara CXCURBAL pe CXSTOCURIID=%s" % r["id"])
            running = r["balance"]
            initial_seen = True
        else:
            if r["qty"] is None:
                raise ValueError("CXQTY lipsa pe CXSTOCURIID=%s" % r["id"])
            running = running.add(r["qty"])
            movement_seen = True
        expected[r["id"]] = running
    return expected


def datekey(value):
    if value is None:
        return None
    stamp = SimpleDateFormat("yyyy-MM-dd HH:mm:ss")
    stamp.setTimeZone(TimeZone.getTimeZone("UTC"))
    nanos = value.getNanos() if hasattr(value, "getNanos") else (value.getTime() % 1000) * 1000000
    return stamp.format(value) + ".%09d" % nanos


def read_number(mbo, field):
    if mbo.isNull(field):
        return None
    raw = mbo.getMboValue(field).getCurrentValue().asString().strip()
    if raw == "":
        return None
    try:
        return BigDecimal(raw)
    except Exception:
        parser = NumberFormat.getNumberInstance(mbo.getUserInfo().getLocale())
        parser.setParseBigDecimal(True)
        pos = ParsePosition(0)
        value = parser.parse(raw, pos)
        if value is None or pos.getIndex() != len(raw):
            raise ValueError("Numar neinterpretabil %s=%s" % (field, raw))
        return value


def write_balance(mbo, value):
    current = read_number(mbo, "CXCURBAL")
    if current is not None and current.subtract(value).abs().compareTo(TOL) <= 0:
        return False
    mv = mbo.getMboValue("CXCURBAL")
    typed = MaxType.createMaxType(Locale.US, TimeZone.getTimeZone("UTC"), mv.getType())
    typed.setScale(mv.getScale())
    typed.setValue(value.toPlainString())
    written = BigDecimal(typed.asString())
    if written.subtract(value).abs().compareTo(TOL) > 0:
        raise Skip("precizia CXCURBAL nu pastreaza %s pe CXSTOCURIID=%s" % (
            value.toPlainString(), mbo.getUniqueIDValue()))
    mbo.setValue("CXCURBAL", typed, FLAGS)
    return True


def close_set(ms):
    if ms is None:
        return
    try:
        ms.cleanup()
    except Exception:
        pass
    try:
        ms.close()
    except Exception:
        pass


def snapshot(mbo):
    when = None if mbo.isNull("CXDOCUMENTDATE") else mbo.getDate("CXDOCUMENTDATE")
    return {
        "id": mbo.getUniqueIDValue(),
        "date": None if when is None else datekey(when),
        "ref": None if mbo.isNull("CXREFID") else mbo.getLong("CXREFID"),
        "kind": mbo.getString("CXREF"),
        "refmbo": mbo.getString("CXREFMBO"),
        "cost": read_number(mbo,"UNITCOST"),
        "group": mbo.getString("COMMODITYGROUP"),
        "item": mbo.getString("ITEMNUM"),"site":mbo.getString("SITEID"),"location":mbo.getString("LOCATION"),
        "qty": read_number(mbo, "CXQTY"),
        "balance": read_number(mbo, "CXCURBAL"),
        "mbo": mbo,
    }


def read_rows(ms):
    rows = []
    current = ms.moveFirst()
    while current is not None:
        rows.append(snapshot(current))
        if len(rows) > MAX_ROWS:
            raise Skip("peste %s randuri" % MAX_ROWS)
        current = ms.moveNext()
    return rows


def open_partition(user, item, site, location, group, cost):
    clauses = []
    binds = []
    index = 1
    for attr, value in (
        ("ITEMNUM", item), ("SITEID", site), ("LOCATION", location),
        ("COMMODITYGROUP", group), ("UNITCOST", cost),
    ):
        if value is None:
            clauses.append(attr + " is null")
        else:
            clauses.append("%s=:%s" % (attr, index))
            binds.append((index, attr, value))
            index += 1
    ms = MXServer.getMXServer().getMboSet("CXSTOCURI", user)
    try:
        sql = SqlFormat(" and ".join(clauses))
        for idx, attr, value in binds:
            sql.setObject(idx, "CXSTOCURI", attr, value)
        ms.setWhere(sql.format())
        ms.reset()
        return ms
    except Exception:
        close_set(ms)
        raise


def process_partition(user, seed):
    ms = open_partition(user, *seed)
    try:
        rows = read_rows(ms)
        if not rows:
            raise Skip("partitia nu a fost regasita")
        sources=[]
        def query(name,where):
            source_set=MXServer.getMXServer().getMboSet(name,user)
            sources.append(source_set)
            source_set.setFlag(MboConstants.NOSAVE,True)
            source_set.setWhere(where)
            source_set.reset()
            found=[]
            source=source_set.moveFirst()
            while source is not None:
                found.append(source)
                if len(found)>MAX_ROWS:
                    raise Skip("Limita de surse depasita")
                source=source_set.moveNext()
            return source_set,found
        try:
            cx_enrich_receipts(rows,query)
            expected,keys,errors=cx_receipt_balances(rows,ZERO)
            if errors:
                raise Skip("Provenienta pe receptie lipsa/ambigua; corecteaza intai sursele")
        finally:
            for source_set in reversed(sources):
                close_set(source_set)
        changed = 0
        for row in rows:
            if row["kind"] == "INITIAL":
                continue
            if write_balance(row["mbo"], expected[row["id"]]):
                changed += 1
        if changed:
            ms.save()
        return changed
    finally:
        close_set(ms)


def positive_days(value):
    if value is None:
        return None
    text = str(value).strip()
    if text == "" or text.lower() == "none":
        return None
    if not text.isdigit():
        raise ValueError("cfr.inventory.numHistoryDaysToUpdate nu e un intreg: %s" % text)
    number = int(text)
    if number <= 0:
        return None
    return number


def seed_where(full, days):
    if full:
        return "1=1"
    where = "cxcurbal is null"
    if days is not None:
        where += " and cxdocumentdate > current timestamp - %s days" % days
    return where


def clean_text(value):
    if value is None:
        return None
    text = value.strip()
    return text if text != "" else None


def clean_cost(value):
    text = clean_text(value)
    if text is None:
        return None
    try:
        return BigDecimal(text).stripTrailingZeros().toPlainString()
    except Exception:
        return text


def load_seeds(user, where):
    db = MXServer.getMXServer().getDBManager()
    key = user.getConnectionKey()
    con = None
    stmt = None
    rs = None
    try:
        con = db.getConnection(key)
        stmt = con.createStatement()
        rs = stmt.executeQuery(
            "select itemnum, siteid, location, commoditygroup, unitcost "
            "from cxstocuri where %s "
            "group by itemnum, siteid, location, commoditygroup, unitcost" % where
        )
        seeds = []
        while rs.next():
            seeds.append((
                clean_text(rs.getString(1)), clean_text(rs.getString(2)),
                clean_text(rs.getString(3)), clean_text(rs.getString(4)),
                clean_cost(rs.getString(5)),
            ))
        return seeds
    finally:
        for resource in (rs, stmt):
            if resource is not None:
                try:
                    resource.close()
                except Exception:
                    pass
        if con is not None:
            db.freeConnection(key)


def label_of(seed):
    item, site, location, group, cost = seed
    return "%s | %s | %s | %s | %s" % (item, site, location, group, cost)


def main():
    user = globals().get("runAsUserInfo")
    if user is None:
        service.log_error("CXSTOCURIUPDATECURBAL: runAsUserInfo lipsa")
        raise ValueError("runAsUserInfo lipsa")
    server = MXServer.getMXServer()
    full = str(server.getProperty("cfr.inventory.updateAllCxStocuri")).strip().lower() in ("true", "1", "yes")
    days = None if full else positive_days(server.getProperty("cfr.inventory.numHistoryDaysToUpdate"))
    where = seed_where(full, days)
    service.log_error("CXSTOCURIUPDATECURBAL start mod=%s filtru=%s" % (
        "complet" if full else "null", where))
    seeds = load_seeds(user, where)
    written = 0
    skipped = 0
    failed = 0
    logged = 0
    for seed in seeds:
        try:
            written += process_partition(user, seed)
        except Skip as exc:
            skipped += 1
            if logged < SKIP_LOG_LIMIT:
                service.log_error("CXSTOCURIUPDATECURBAL sarit %s: %s" % (label_of(seed), exc))
                logged += 1
        except Exception as exc:
            failed += 1
            if logged < SKIP_LOG_LIMIT:
                service.log_error("CXSTOCURIUPDATECURBAL eroare %s: %s" % (label_of(seed), exc))
                logged += 1
    service.log_error(
        "CXSTOCURIUPDATECURBAL gata partitii=%s randuri=%s sarite=%s erori=%s" % (
            len(seeds), written, skipped, failed))


if globals().get("service") is not None:
    main()
