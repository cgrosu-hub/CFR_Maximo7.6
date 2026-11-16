# SCRIPT: CXSTOCURIUPDATECURBAL
# AUTOR: Fernando Prajitura; aliniat la ledger-ul FIFO de Cristian Grosu
# VERSIUNE: 2026.11.16-PU-RECEPTIE
# ISSUE legat de MATRECTRANS: diferenta de pret de 0.001 si LINECOST egal cu
# valoarea receptiei -> UNITCOST din jurnal devine pretul receptiei.
# Urma: DESCRIPTION_LONGDESCRIPTION, linie "PU-RECEPTIE:". Apoi se recalculeaza
# ambele partitii de pret, chiar daca CXCURBAL nu mai e null.
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


def _milli(text):
    # Identic in CXADDTOCXSTOCURI. Preturile sunt la 3 zecimale.
    s = str(text).strip()
    sign = -1 if s.startswith("-") else 1
    if s[:1] in "-+":
        s = s[1:]
    if "." not in s:
        s += ".000"
    whole, frac = s.split(".", 1)
    frac = (frac + "0000")[:4]
    base = int(whole or "0") * 1000 + int(frac[:3])
    if int(frac[3]) >= 5:
        base += 1
    return sign * base


def plain_milli(value):
    sign = "-" if value < 0 else ""
    value = abs(int(value))
    return "%s%d.%03d" % (sign, value // 1000, value % 1000)


def snap_issue_cost(issue_cost, receipt_cost, qty, line_cost):
    # Identic in CXADDTOCXSTOCURI. Doar rotunjirea Maximo de 0.001.
    if issue_cost is None or receipt_cost is None or qty is None or line_cost is None:
        return None
    issue = _milli(issue_cost)
    receipt = _milli(receipt_cost)
    gap = abs(issue - receipt)
    if gap == 0 or gap > 1:
        return None
    value = (abs(_milli(qty)) * abs(receipt) + 500) // 1000
    if abs(_milli(line_cost)) != value:
        return None
    return plain_milli(receipt)


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
    if snap_issue_cost("43.281", "43.280", "-0.520", "-22.506") != "43.280":
        raise ValueError("self-check snap 43.281")
    if snap_issue_cost("43.281", "43.270", "-0.520", "-22.500") is not None:
        raise ValueError("self-check snap diferenta mare")
    if snap_issue_cost("24.589", "24.590", "-0.185", "-4.426") is not None:
        raise ValueError("self-check snap linecost")
    if snap_issue_cost("43.280", "43.280", "-0.520", "-22.506") is not None:
        raise ValueError("self-check snap egal")


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


def plain_from_mbo(mbo, field):
    if mbo is None or mbo.isNull(field):
        return None
    raw = mbo.getMboValue(field).getCurrentValue().asString().strip()
    if raw == "":
        return None
    try:
        return BigDecimal(raw).stripTrailingZeros().toPlainString()
    except Exception:
        parser = NumberFormat.getNumberInstance(mbo.getUserInfo().getLocale())
        parser.setParseBigDecimal(True)
        pos = ParsePosition(0)
        value = parser.parse(raw, pos)
        if value is None or pos.getIndex() != len(raw):
            return None
        return value.stripTrailingZeros().toPlainString()


def remember_price(mbo, line):
    old = ""
    try:
        if not mbo.isNull("DESCRIPTION_LONGDESCRIPTION"):
            old = mbo.getString("DESCRIPTION_LONGDESCRIPTION") or ""
    except Exception:
        old = ""
    if line in old:
        return
    text = line if not old.strip() else old.rstrip() + "\n" + line
    mbo.setValue("DESCRIPTION_LONGDESCRIPTION", text, FLAGS)
    try:
        mbo.setValue("HASLD", 1, FLAGS)
    except Exception:
        pass


def write_cost(mbo, value):
    mv = mbo.getMboValue("UNITCOST")
    typed = MaxType.createMaxType(Locale.US, TimeZone.getTimeZone("UTC"), mv.getType())
    typed.setScale(mv.getScale())
    typed.setValue(value)
    written = BigDecimal(typed.asString())
    if written.compareTo(BigDecimal(value)) != 0:
        raise Skip("precizia UNITCOST nu pastreaza %s pe CXSTOCURIID=%s" % (
            value, mbo.getUniqueIDValue()))
    mbo.setValue("UNITCOST", typed, FLAGS)


def field_text(mbo, field):
    if mbo.isNull(field):
        return None
    return clean_text(mbo.getString(field))


def load_snap_ids(user):
    db = MXServer.getMXServer().getDBManager()
    key = user.getConnectionKey()
    con = None
    stmt = None
    rs = None
    try:
        con = db.getConnection(key)
        stmt = con.createStatement()
        rs = stmt.executeQuery(
            "select c.cxstocuriid from cxstocuri c, matusetrans u, matrectrans r "
            "where c.cxrefmbo='MATUSETRANS' and c.cxref='ISSUE' and c.cxrefid=u.matusetransid "
            "and u.issuetype='ISSUE' and u.matrectransid is not null "
            "and u.matrectransid=r.matrectransid "
            "and abs(u.unitcost-r.unitcost)>0 and abs(u.unitcost-r.unitcost)<=0.001 "
            "and abs(c.unitcost-u.unitcost)<=0.0000001"
        )
        ids = []
        while rs.next():
            ids.append(rs.getLong(1))
        return ids
    finally:
        for resource in (rs, stmt):
            if resource is not None:
                try:
                    resource.close()
                except Exception:
                    pass
        if con is not None:
            db.freeConnection(key)


def snap_existing(user):
    # Randurile deja mutate nu mai au UNITCOST = pretul din MATUSETRANS.
    seeds = []
    changed = 0
    for row_id in load_snap_ids(user):
        ms = None
        try:
            ms = MXServer.getMXServer().getMboSet("CXSTOCURI", user)
            ms.setWhere("CXSTOCURIID=%s" % row_id)
            ms.reset()
            row = ms.moveFirst()
            if row is None:
                continue
            issue = row.getMboSet("$CXPU_ISSUE", "MATUSETRANS", "MATUSETRANSID=:CXREFID").moveFirst()
            receipt = None
            if issue is not None and not issue.isNull("MATRECTRANSID"):
                receipt = issue.getMboSet("$CXPU_REC", "MATRECTRANS", "MATRECTRANSID=:MATRECTRANSID").moveFirst()
            issue_cost = plain_from_mbo(issue, "UNITCOST")
            journal_cost = plain_from_mbo(row, "UNITCOST")
            if issue_cost is None or _milli(journal_cost) != _milli(issue_cost):
                continue
            snapped = snap_issue_cost(
                issue_cost, plain_from_mbo(receipt, "UNITCOST"),
                plain_from_mbo(issue, "QUANTITY"), plain_from_mbo(issue, "LINECOST"))
            if snapped is None:
                continue
            old_cost = clean_cost(journal_cost)
            write_cost(row, snapped)
            remember_price(row, "PU-RECEPTIE: %s -> %s MATRECTRANS %s" % (
                plain_milli(_milli(issue_cost)), snapped, issue.getLong("MATRECTRANSID")))
            ms.save()
            base = (
                field_text(row, "ITEMNUM"), field_text(row, "SITEID"),
                field_text(row, "LOCATION"), field_text(row, "COMMODITYGROUP"))
            seeds.append(base + (old_cost,))
            seeds.append(base + (clean_cost(snapped),))
            changed += 1
            service.log_error("CXSTOCURIUPDATECURBAL pret CXSTOCURIID=%s %s -> %s" % (
                row_id, old_cost, snapped))
        except Exception as exc:
            service.log_error("CXSTOCURIUPDATECURBAL pret CXSTOCURIID=%s neschimbat: %s" % (row_id, exc))
        finally:
            close_set(ms)
    return seeds, changed


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
    extra, snapped = snap_existing(user)
    seeds = load_seeds(user, where)
    seen = set(seeds)
    for seed in extra:
        if seed not in seen:
            seeds.append(seed)
            seen.add(seed)
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
        "CXSTOCURIUPDATECURBAL gata partitii=%s randuri=%s sarite=%s erori=%s preturi=%s" % (
            len(seeds), written, skipped, failed, snapped))


if globals().get("service") is not None:
    main()
