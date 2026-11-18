# SCRIPT: CXSTOCURIUPDATECURBAL
# AUTOR: Fernando Prajitura; aliniat la ledger-ul FIFO de Cristian Grosu
# VERSIUNE: 2026.11.18-SAME-DAY-ON
# ISSUE legat de MATRECTRANS: diferenta de pret de 0.001 si LINECOST egal cu
# valoarea receptiei -> UNITCOST din jurnal devine pretul receptiei.
# Urma: DESCRIPTION_LONGDESCRIPTION, linie "PU-RECEPTIE:". Apoi se recalculeaza
# ambele partitii de pret, chiar daca CXCURBAL nu mai e null.
# Completeaza CXCURBAL pe partitiile care inca il au null.
# Same-day (implicit ON, validat pe Check FIFO): iesiri inaintea intrarilor
# din aceeasi zi => SQL CXDOCUMENTDATE/ACTUALDATE la max(intrari)+1..N min,
# apoi CXCURBAL. Partitia: ITEMNUM, SITEID, LOCATION, COMMODITYGROUP, UNITCOST
# Ordine ledger: CXDOCUMENTDATE, CXREFID (null=0), CXSTOCURIID.
#
# cfr.inventory.updateAllCxStocuri = true  -> toate partitiile
# altfel -> doar partitiile cu cel putin un CXCURBAL null
# cfr.inventory.numHistoryDaysToUpdate = N -> in modul null, ultimele N zile
# cfr.inventory.sameDayReorder = false -> opreste reordonarea same-day
# cfr.inventory.sameDayReorderMax = N -> plafon mutari / rulare (default 500)

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
DEFAULT_SAME_DAY_MAX = 500


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
        "date_ms": None if when is None else long(when.getTime()),
        "ref": None if mbo.isNull("CXREFID") else mbo.getLong("CXREFID"),
        "ref_id": None if mbo.isNull("CXREFID") else mbo.getLong("CXREFID"),
        "ref_mbo": None if mbo.isNull("CXREFMBO") else mbo.getString("CXREFMBO"),
        "kind": mbo.getString("CXREF"),
        "qty": read_number(mbo, "CXQTY"),
        "cost": read_number(mbo, "UNITCOST"),
        "balance": read_number(mbo, "CXCURBAL"),
        "group": None if mbo.isNull("COMMODITYGROUP") else clean_text(mbo.getString("COMMODITYGROUP")),
        "item": None if mbo.isNull("ITEMNUM") else clean_text(mbo.getString("ITEMNUM")),
        "site": None if mbo.isNull("SITEID") else clean_text(mbo.getString("SITEID")),
        "location": None if mbo.isNull("LOCATION") else clean_text(mbo.getString("LOCATION")),
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


def prop_true(server, name, default=False):
    raw = server.getProperty(name)
    if raw is None or str(raw).strip() == "":
        return default
    text = str(raw).strip().lower()
    if text in ("false", "0", "no"):
        return False
    if text in ("true", "1", "yes"):
        return True
    return default


def prop_positive(server, name, default):
    raw = server.getProperty(name)
    if raw is None or str(raw).strip() == "":
        return default
    text = str(raw).strip()
    if not text.isdigit():
        return default
    value = int(text)
    return value if value > 0 else default


def chrono_exit(row):
    kind, qty, ref_mbo = row.get("kind"), row.get("qty"), row.get("ref_mbo")
    if qty is None or qty.compareTo(ZERO) >= 0:
        return False
    if kind == "ISSUE" and ref_mbo == "MATUSETRANS":
        return True
    if ref_mbo != "MATRECTRANS":
        return False
    if kind == "SHIPTRANSFER":
        return True
    return kind in ("TRANSFER", "RECEIPT", "SHIPRECEIPT")


def chrono_entry(row):
    if chrono_exit(row):
        return False
    if row.get("kind") == "INITIAL":
        return False
    qty = row.get("qty")
    return qty is not None and qty.compareTo(ZERO) > 0


def second_bucket(row):
    d = row.get("date")
    return None if not d else str(d)[:19]


def day_bucket(row):
    d = row.get("date")
    return None if not d else str(d)[:10]


def plan_same_day_shifts(rows):
    by_day = {}
    for r in rows:
        day = day_bucket(r)
        if day is None or r.get("date_ms") is None:
            continue
        by_day.setdefault(day, []).append(r)
    shifts = []
    for day, group in sorted(by_day.items()):
        entries = [r for r in group if chrono_entry(r)]
        exits = [r for r in group if chrono_exit(r)]
        if not entries or not exits:
            continue
        base_ms = max(r["date_ms"] for r in entries)
        entry_secs = set(second_bucket(r) for r in entries if second_bucket(r))
        to_move = [r for r in exits
                   if r["date_ms"] <= base_ms or second_bucket(r) in entry_secs]
        if not to_move:
            continue
        to_move.sort(key=lambda r: (r["date_ms"], r.get("ref_id") or 0, r["id"]))
        for i, r in enumerate(to_move):
            new_ms = long(base_ms) + (i + 1) * 60000
            if r["date_ms"] != new_ms:
                shifts.append({"row": r, "new_ms": new_ms, "day": day, "step": i + 1})
    return shifts


def sql_update_timestamp(user, table, pk_field, pk_value, field, new_ms):
    from java.sql import Timestamp
    db = MXServer.getMXServer().getDBManager()
    key = user.getConnectionKey()
    con = ps = None
    try:
        con = db.getConnection(key)
        ps = con.prepareStatement("UPDATE %s SET %s=? WHERE %s=?" % (table, field, pk_field))
        ps.setTimestamp(1, Timestamp(long(new_ms)))
        ps.setLong(2, long(pk_value))
        n = ps.executeUpdate()
        if n != 1:
            raise ValueError("UPDATE %s.%s %s=%s: %s randuri" % (table, field, pk_field, pk_value, n))
        con.commit()
    except Exception:
        if con is not None:
            try:
                con.rollback()
            except Exception:
                pass
        raise
    finally:
        if ps is not None:
            try:
                ps.close()
            except Exception:
                pass
        if con is not None:
            db.freeConnection(key)


def sql_update_cxcurbal_bd(user, cxid, value):
    db = MXServer.getMXServer().getDBManager()
    key = user.getConnectionKey()
    con = ps = None
    try:
        con = db.getConnection(key)
        ps = con.prepareStatement("UPDATE CXSTOCURI SET CXCURBAL=? WHERE CXSTOCURIID=?")
        ps.setBigDecimal(1, value)
        ps.setLong(2, long(cxid))
        n = ps.executeUpdate()
        if n != 1:
            raise ValueError("UPDATE CXCURBAL CXSTOCURIID=%s: %s randuri" % (cxid, n))
        con.commit()
    except Exception:
        if con is not None:
            try:
                con.rollback()
            except Exception:
                pass
        raise
    finally:
        if ps is not None:
            try:
                ps.close()
            except Exception:
                pass
        if con is not None:
            db.freeConnection(key)


def open_scope_journal(user, item, site, location):
    ms = MXServer.getMXServer().getMboSet("CXSTOCURI", user)
    try:
        sql = SqlFormat("ITEMNUM=:1 AND SITEID=:2 AND LOCATION=:3")
        sql.setObject(1, "CXSTOCURI", "ITEMNUM", item)
        sql.setObject(2, "CXSTOCURI", "SITEID", site)
        sql.setObject(3, "CXSTOCURI", "LOCATION", location)
        ms.setWhere(sql.format())
        ms.setOrderBy("CXDOCUMENTDATE,CXREFID,CXSTOCURIID")
        ms.reset()
        return ms
    except Exception:
        close_set(ms)
        raise


def load_sameday_scopes(user, full, days):
    db = MXServer.getMXServer().getDBManager()
    key = user.getConnectionKey()
    con = stmt = rs = None
    where = "1=1" if full else "cxdocumentdate > current timestamp - %s days" % (days or 30)
    try:
        con = db.getConnection(key)
        stmt = con.createStatement()
        rs = stmt.executeQuery(
            "select itemnum, siteid, location from ("
            " select itemnum, siteid, location, date(cxdocumentdate) as d,"
            " max(case when cxqty > 0 then 1 else 0 end) as has_in,"
            " max(case when cxqty < 0 then 1 else 0 end) as has_out"
            " from cxstocuri where %s"
            " group by itemnum, siteid, location, date(cxdocumentdate)"
            ") x where has_in=1 and has_out=1"
            " group by itemnum, siteid, location" % where
        )
        scopes = []
        while rs.next():
            scopes.append((
                clean_text(rs.getString(1)), clean_text(rs.getString(2)),
                clean_text(rs.getString(3)),
            ))
        return scopes
    finally:
        for resource in (rs, stmt):
            if resource is not None:
                try:
                    resource.close()
                except Exception:
                    pass
        if con is not None:
            db.freeConnection(key)


def seed_from_row(row):
    cost = None if row.get("cost") is None else clean_cost(row["cost"].toPlainString())
    return (row.get("item"), row.get("site"), row.get("location"), row.get("group"), cost)


def apply_same_day_scope(user, item, site, location, budget):
    # Returneaza (seeds_extra, mutari, solduri, budget_ramas).
    from java.text import SimpleDateFormat
    from java.util import TimeZone, Date
    ms = open_scope_journal(user, item, site, location)
    try:
        rows = read_rows(ms)
        shifts = plan_same_day_shifts(rows)
        if not shifts:
            return [], 0, 0, budget
        if len(shifts) > budget:
            shifts = shifts[:budget]
        fmt = SimpleDateFormat("yyyy-MM-dd HH:mm:ss")
        fmt.setTimeZone(TimeZone.getTimeZone("UTC"))
        touched = set()
        for item_shift in shifts:
            r = item_shift["row"]
            new_ms = item_shift["new_ms"]
            sql_update_timestamp(user, "CXSTOCURI", "CXSTOCURIID", r["id"], "CXDOCUMENTDATE", new_ms)
            ref_mbo = r.get("ref_mbo")
            ref_id = r.get("ref_id")
            if ref_mbo == "MATUSETRANS" and ref_id is not None:
                sql_update_timestamp(user, "MATUSETRANS", "MATUSETRANSID", ref_id, "ACTUALDATE", new_ms)
            elif ref_mbo == "MATRECTRANS" and ref_id is not None:
                sql_update_timestamp(user, "MATRECTRANS", "MATRECTRANSID", ref_id, "ACTUALDATE", new_ms)
            r["date_ms"] = new_ms
            r["date"] = fmt.format(Date(long(new_ms))) + ".000000000"
            touched.add(seed_from_row(r))
        # CXCURBAL pe partitie UNITCOST+COMMODITYGROUP (ca process_partition).
        partitions = {}
        for r in rows:
            key = (r.get("group"), None if r.get("cost") is None else clean_cost(r["cost"].toPlainString()))
            partitions.setdefault(key, []).append(r)
        bal_changed = 0
        for key, group in partitions.items():
            part_rows = [{
                "id": r["id"], "date": r["date"], "ref": r.get("ref"), "kind": r["kind"],
                "qty": r.get("qty"), "balance": r.get("balance"),
            } for r in group]
            part_exp = running_balances(part_rows)
            for r in group:
                new_bal = part_exp[r["id"]]
                old_bal = r.get("balance")
                if old_bal is None or old_bal.subtract(new_bal).abs().compareTo(TOL) > 0:
                    sql_update_cxcurbal_bd(user, r["id"], new_bal)
                    r["balance"] = new_bal
                    bal_changed += 1
                touched.add(seed_from_row(r))
        return list(touched), len(shifts), bal_changed, budget - len(shifts)
    finally:
        close_set(ms)


def same_day_self_check():
    rows = [
        {"id": 1, "kind": "ISSUE", "qty": BigDecimal("-1"), "ref_mbo": "MATUSETRANS", "ref_id": 10,
         "date": "2026-01-19 09:09:00.000000000", "date_ms": 1000, "cost": BigDecimal("446")},
        {"id": 2, "kind": "ISSUE", "qty": BigDecimal("-1"), "ref_mbo": "MATUSETRANS", "ref_id": 11,
         "date": "2026-01-19 09:09:00.000000000", "date_ms": 1001, "cost": BigDecimal("446")},
        {"id": 3, "kind": "RECEIPT", "qty": BigDecimal("8"), "ref_mbo": "MATRECTRANS", "ref_id": 20,
         "date": "2026-01-19 18:48:00.000000000", "date_ms": 50000, "cost": BigDecimal("446")},
    ]
    shifts = plan_same_day_shifts(rows)
    if len(shifts) != 2 or shifts[0]["new_ms"] != 50000 + 60000:
        raise ValueError("self-check same-day: iesirile dimineata trebuie dupa receptie")


def main():
    self_check()
    same_day_self_check()
    user = globals().get("runAsUserInfo")
    if user is None:
        service.log_error("CXSTOCURIUPDATECURBAL: runAsUserInfo lipsa")
        raise ValueError("runAsUserInfo lipsa")
    server = MXServer.getMXServer()
    full = prop_true(server, "cfr.inventory.updateAllCxStocuri")
    days = None if full else positive_days(server.getProperty("cfr.inventory.numHistoryDaysToUpdate"))
    where = seed_where(full, days)
    # Same-day implicit ON (validat pe Check FIFO); false/0/no il opreste.
    same_day = prop_true(server, "cfr.inventory.sameDayReorder", default=True)
    same_day_max = prop_positive(server, "cfr.inventory.sameDayReorderMax", DEFAULT_SAME_DAY_MAX)
    service.log_error("CXSTOCURIUPDATECURBAL start mod=%s filtru=%s sameDay=%s max=%s" % (
        "complet" if full else "null", where, same_day, same_day_max))
    extra, snapped = snap_existing(user)
    moved = 0
    bal_fixed = 0
    if same_day:
        budget = same_day_max
        for item, site, location in load_sameday_scopes(user, full, days):
            if budget <= 0:
                break
            try:
                seeds_extra, n_move, n_bal, budget = apply_same_day_scope(
                    user, item, site, location, budget)
                moved += n_move
                bal_fixed += n_bal
                for seed in seeds_extra:
                    if seed not in extra:
                        extra.append(seed)
            except Exception as exc:
                service.log_error("CXSTOCURIUPDATECURBAL same-day %s|%s|%s: %s" % (
                    item, site, location, exc))
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
        "CXSTOCURIUPDATECURBAL gata partitii=%s randuri=%s sarite=%s erori=%s preturi=%s sameDayMutari=%s sameDaySold=%s" % (
            len(seeds), written, skipped, failed, snapped, moved, bal_fixed))


if globals().get("service") is not None:
    main()
