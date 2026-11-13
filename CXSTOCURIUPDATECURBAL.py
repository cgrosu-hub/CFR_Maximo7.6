# SCRIPT: CXSTOCURIUPDATECURBAL
# AUTOR: Fernando Prajitura; aliniat la ledger-ul FIFO de Cristian Grosu
# VERSIUNE: 2026.11.04-FIFO-LEDGER
# Completeaza CXCURBAL pe partitiile care inca il au null.
# Partitia e cea din CXUPDFIFOROW / CXFIFOFIXISSUE:
#   ITEMNUM, SITEID, LOCATION, COMMODITYGROUP, UNITCOST
# Ordinea e cea din ledger: CXDOCUMENTDATE, CXREFID (null = 0), CXSTOCURIID.
# INITIAL, daca exista, e prima inregistrare din partitie si isi pastreaza soldul.
# Celelalte randuri: sold = sold anterior + CXQTY.
# Nu rescrie un sold care coincide deja. Nu atinge o partitie ambigua.
#
# cfr.inventory.updateAllCxStocuri = true  -> toate partitiile
# altfel -> doar partitiile cu cel putin un CXCURBAL null
# cfr.inventory.numHistoryDaysToUpdate = N -> in modul null, doar documentele
# din ultimele N zile pornesc recalculul (partitia intreaga e recalculata)

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


def self_check():
    def row(ident, date, ref, kind, qty, balance):
        return {
            "id": ident, "date": date, "ref": ref, "kind": kind,
            "qty": None if qty is None else BigDecimal(qty),
            "balance": None if balance is None else BigDecimal(balance),
        }

    def expect(got, ident, text):
        if got[ident].compareTo(BigDecimal(text)) != 0:
            raise ValueError("self-check id %s: %s != %s" % (ident, got[ident].toPlainString(), text))

    def must_fail(rows):
        try:
            running_balances(rows)
        except ValueError:
            return
        raise ValueError("self-check trebuia sa respinga partida")

    # CXREFID null se sorteaza ca 0, deci receptia e inaintea ISSUE la aceeasi data
    got = running_balances([
        row(1, "2026-02-09 00:00:00.000000000", None, "INITIAL", None, "10"),
        row(2, "2026-02-09 01:00:00.000000000", 5, "ISSUE", "-2", None),
        row(3, "2026-02-09 01:00:00.000000000", None, "RECEIPT", "4", None),
    ])
    expect(got, 1, "10")
    expect(got, 3, "14")
    expect(got, 2, "12")

    got = running_balances([
        row(1, "2026-03-01 00:00:00.000000000", 1, "RECEIPT", "8.52", None),
        row(2, "2026-03-02 00:00:00.000000000", 2, "ISSUE", "-8.52", None),
    ])
    expect(got, 1, "8.52")
    expect(got, 2, "0")

    must_fail([
        row(1, "2026-03-01 00:00:00.000000000", 1, "RECEIPT", "1", None),
        row(2, "2026-03-02 00:00:00.000000000", None, "INITIAL", None, "5"),
    ])
    must_fail([
        row(1, "2026-01-01 00:00:00.000000000", None, "INITIAL", None, "1"),
        row(2, "2026-01-02 00:00:00.000000000", None, "INITIAL", None, "2"),
    ])
    must_fail([
        row(1, "2026-01-01 00:00:00.000000000", 1, "ISSUE", None, None),
    ])
    must_fail([
        row(1, "2026-01-01 00:00:00.000000000", None, "INITIAL", None, None),
    ])


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
        expected = running_balances(rows)
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
    self_check()
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
