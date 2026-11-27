from psdi.mbo import SqlFormat
from psdi.server import MXServer


def validate_gl_accounts(line):
    fields = (
        ("GLDEBITACCT", "Cont de debit GL"),
        ("GLCREDITACCT", "Cont de credit GL"),
    )
    org_id = line.getString("ORGID")
    server = MXServer.getMXServer()
    accounts = server.getMboSet("CHARTOFACCOUNTS", server.getSystemUserInfo())
    try:
        for attribute, label in fields:
            account = line.getString(attribute)
            if not account.strip():
                continue

            query = SqlFormat("orgid = :1 and glaccount = :2")
            query.setObject(1, "CHARTOFACCOUNTS", "ORGID", org_id)
            query.setObject(2, "CHARTOFACCOUNTS", "GLACCOUNT", account)
            accounts.setWhere(query.format())
            accounts.reset()

            if accounts.isEmpty():
                service.error("cfrinvuse", "glaccountmissing", [
                    line.getString("INVUSENUM"),
                    line.getString("INVUSELINENUM"),
                    label,
                    account,
                    org_id,
                ])
    finally:
        try:
            accounts.cleanup()
        finally:
            accounts.close()


validate_gl_accounts(mbo)