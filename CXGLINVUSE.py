from psdi.mbo import SqlFormat
from psdi.server import MXServer


def validate_gl_accounts(document):
    lines = document.getMboSet("INVUSELINE")
    line = lines.getMbo(0)
    if line is None:
        return

    org_id = document.getString("ORGID")
    verified_accounts = set()
    fields = (
        ("GLDEBITACCT", "Cont de debit GL"),
        ("GLCREDITACCT", "Cont de credit GL"),
    )

    server = MXServer.getMXServer()
    accounts = server.getMboSet("CHARTOFACCOUNTS", server.getSystemUserInfo())
    try:
        index = 0
        while line is not None:
            if not line.toBeDeleted():
                for attribute, label in fields:
                    account = line.getString(attribute)
                    if not account.strip() or account in verified_accounts:
                        continue

                    query = SqlFormat("orgid = :1 and glaccount = :2")
                    query.setObject(1, "CHARTOFACCOUNTS", "ORGID", org_id)
                    query.setObject(2, "CHARTOFACCOUNTS", "GLACCOUNT", account)
                    accounts.setWhere(query.format())
                    accounts.reset()

                    if accounts.isEmpty():
                        service.error("cfrinvuse", "glaccountmissing", [
                            document.getString("INVUSENUM"),
                            line.getString("INVUSELINENUM"),
                            label,
                            account,
                            org_id,
                        ])

                    verified_accounts.add(account)

            index += 1
            line = lines.getMbo(index)
    finally:
        try:
            accounts.cleanup()
        finally:
            accounts.close()


validate_gl_accounts(mbo)
