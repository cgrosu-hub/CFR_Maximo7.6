#-------------------------------------------------------------
# AUTOSCRIPT:			CXSTOCURIUPDATECURBAL
# DESCRIPTION:			recalculate CXCURBAL pentru CXSTOCURI ordonat dupa CXDOCUMENTDATE. Porneste de la prima inregistrare XXREF = 'INITIAL' ce are valoare in CXCURBAL; else pleaca de la 0
#                       Using system properties for parameters to update all or only Items that where changed in the last X days.
#                       Running a full recalculation will take longer with time. Should be done only seldom when reinitializing.
# AUTHOR:				Fernando Prajitura
# Created:				12-12-2023
# LOGLEVEL:				ERROR
#-------------------------------------------------------------

from psdi.mbo import Mbo, MboConstants
from psdi.server import MXServer
from psdi.security import UserInfo
from psdi.mbo import SqlFormat
from java.io import FileOutputStream


currentDate = MXServer.getMXServer().getDate()
mxServer = MXServer.getMXServer()
#   properties for runtime. Running a full recalculation will take longer with time. Should be done only seldom when reinitializing. 
#   get update for X last number of days
numHistoryDaysToUpdate = mxServer.getProperty("cfr.inventory.numHistoryDaysToUpdate")
#   get flag to update all items or only items that were changed in the interval 
#   0 or 1
updateAllCxStocuri = mxServer.getProperty("cfr.inventory.updateAllCxStocuri")

#service.log_info('*** updateAllCxStocuri = '+ str(updateAllCxStocuri) +' ***')
service.log_info('*** Starting Script CXSTOCURIUPDATECURBAL ***')

#####################################
# Define functions
#####################################

column1Name = "ITEMNUM"
column2Name = "LOCATION"
column3Name = "SITEID"
column4Name = "COMMODITYGROUP"
column5Name = "UNITCOST"

#//////////////////////////////////////////////////////////////////
# update curbal for the record
def updateCurbalForRow(stocRowId, curbalValue):
    con = cxStocMbo.getMboServer().getDBConnection(runAsUserInfo.getConnectionKey())
    # Get a schema name of the server to know from which instance it is running
    schema = cxStocMbo.getMboServer().getSchemaOwner()
    schema = schema.upper()
    # add to PTW exceptions flag
    updateQueryForStocuriRowId = "update CXSTOCURI set CXCURBAL = " + str(curbalValue) + " where CXSTOCURIID = " + str(stocRowId)
    s= con.createStatement()
    try:
        s.execute(updateQueryForStocuriRowId)
        #s.close()
        con.commit()
        #con.close()
    except:
        # for any error close the conn
        s.close()
        con.commit()
        con.close()


#####################################
# Running Code
#####################################

#service.log_info('CXSTOCURIUPDATECURBAL script is running ')

cxStocuriMboSet = mxServer.getMboSet("CXSTOCURI",mxServer.getUserInfo("MAXADMIN"))
#   set where clause if updating only Items that have new rows in the interval. Else, will get all the table
if updateAllCxStocuri == 'false':
    #service.log_info('Looking at newly added items in the last '+ numHistoryDaysToUpdate + ' days.')
    whereClauseStocuriSet = "cxcurbal is null and cxdocumentdate > (NOW() - " + str(numHistoryDaysToUpdate) + ")"
    cxStocuriMboSet.setWhere(whereClauseStocuriSet)    
    cxStocuriMboSet.reset()  


#####################################
# get distinct itemnum/location/site/commodityGroup/unitCost 
allRecordsMbo = cxStocuriMboSet.moveFirst()
distinctValues = set()

while allRecordsMbo:
    # Concatenate the values of the three columns into a unique identifier
    uniqueIdentifier = allRecordsMbo.getString(column1Name) + "_" + allRecordsMbo.getString(column2Name) + "_" + allRecordsMbo.getString(column3Name) + "_" + allRecordsMbo.getString(column4Name) + "_" + str(allRecordsMbo.getDouble(column5Name))
    # Add the unique identifier to the set (automatically removes duplicates)
    distinctValues.add(uniqueIdentifier)
    allRecordsMbo = cxStocuriMboSet.moveNext()

# Close the MboSet to release resources
cxStocuriMboSet.close()

# Convert the set to a list for easier iteration
distinctList = list(distinctValues)

# Iterate through the distinct values
for uniqueIdentifier in distinctList:
    # Extract individual column values from the unique identifier
    itemnumValue, locationValue, siteIdValue, commodityGroupValue, unitCostValue = uniqueIdentifier.split("_")

    #service.log_info("Distinct Values: " + itemnumValue + " ," + locationValue + " ," + siteIdValue + " ," + commodityGroupValue+ " ," + str(unitCostValue))
    #   print("Distinct Values:", itemnumValue, locationValue, siteIdValue)
   
    # for each distinct row, get all transactions ordered by cxdocumentdate
    filteredMboSet = mxServer.getMboSet("CXSTOCURI",mxServer.getUserInfo("MAXADMIN"))
    whereClauseStocuriSet = "itemnum = '" + itemnumValue + "' and location = '" + locationValue + "'and siteid = '" + siteIdValue + "' and commoditygroup = '" + commodityGroupValue + "' and unitCost = '" + str(unitCostValue) + "'"
    filteredMboSet.setWhere(whereClauseStocuriSet)
    filteredMboSet.setOrderBy("CXDOCUMENTDATE, CXREFID")
    filteredMboSet.reset()    

    cxStocMbo = filteredMboSet.moveFirst()
    # reset running values
    crtCurBal = 0
    cxRefType = ""
    while cxStocMbo:
        # get initial curbal value
        # could be 0 if no "INITIAL" is found and cxcurbal for the row with "INITIAL"
        cxRefType = cxStocMbo.getString("CXREF")
        StocRowId = cxStocMbo.getLong("CXSTOCURIID")
        #service.log_info("Updating for: " + itemnumValue + " ," + locationValue + " ," + siteIdValue + " ," + commodityGroupValue+ " ," + unitCostValue)
        #service.log_info("Curbal Before update: " + str(crtCurBal))
        if cxRefType== "INITIAL":
            crtCurBal = cxStocMbo.getDouble("CXCURBAL")
            # do not change curbal for this record
        else:
            cxQty = cxStocMbo.getDouble("CXQTY")
            # update cxcurbal for each row through SQL 
            crtCurBal += cxQty
            #service.log_info("Qty to add: " + str(cxQty))
            updateCurbalForRow(StocRowId, crtCurBal)            
            #service.log_info("CxCurbal updated to: " + str(crtCurBal))
        cxStocMbo=filteredMboSet.moveNext()