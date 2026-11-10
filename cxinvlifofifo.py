################################################
#
# script CXINVLIFOFIFO
#   on add/update before save
# seteaza COSTDATE pe baza 
#   MATRECTRANS.ACTUALDATE
#   MATUSETRANS.ACTUALDATE
#   INVUSELINE.ACTUALDATE
#   INVTRANS.TRANSDATE
#
################################################


from java.util import Date
from java.text import SimpleDateFormat
from psdi.util import MXApplicationException
from java.util import Calendar
from java.text import SimpleDateFormat
sdf = SimpleDateFormat ("yyyy-MM-dd-HH.mm.ss.sss")

userInfo = mbo.getThisMboSet().getUserInfo()


service.log_info('*** Starting Script CXINVLIFOFIFO ***')


# running code

###########
# select case REFOBJECT
##########
refObj = mbo.getString("REFOBJECT")

if not mbo.isNull("REFOBJECT"):
    # select case refobject
    service.log_info('*** Avem refobject ***' + refObj)
    service.log_info('*** Avem refobjectid ***' + str(mbo.getLong("REFOBJECTID")))
    # get owner tr object as INVENTORY.OBJ
    parentMboObj = mbo.getOwner().getOwner()
    service.log_info('*** Avem refobject ***' + str(parentMboObj))
    
    # case MATRECTRANS
    if refObj =="MATRECTRANS":
        service.log_info('*** Avem matrectrans record***')
        try:
            if parentMboObj.getString("ISSUETYPE") != 'ISSUE':
                mbo.setValue("COSTDATE", parentMboObj.getDate("ACTUALDATE"))
        except:
            service.log_info('*** Err set costdate from matrectrans***')

    # case MATUSETRANS
    if refObj =="MATUSETRANS":
        service.log_info('*** Avem MATUSETRANS record***')
        # do not change costdate for issues
        try:
            if parentMboObj.getString("USETYPE") != 'ISSUE':
                mbo.setValue("COSTDATE",parentMboObj.getDate("ACTUALDATE"))
        except:
            service.log_info('*** Err set costdate from matrectrans***')       
                
    # case INVUSELINE
    if refObj =="INVUSELINE":
        lRelObject = mbo.getMboSet('$CXINVUSELINETEMP', 'INVUSELINE', "invuselineid = '" + str(mbo.getLong("REFOBJECTID")) + "'").getMbo(0)
        service.log_info('*** Avem refobject ***' + str(lRelObject))
        service.log_info('*** Avem INVUSELINE record***')
        # do not change costdate for issues
        try:
            if lRelObject.getString("USETYPE") != 'ISSUE':
                mbo.setValue("COSTDATE",lRelObject.getDate("ACTUALDATE"))
        except:
            service.log_info('*** Err set costdate from matrectrans***')