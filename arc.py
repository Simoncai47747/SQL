##
## **************************************************
## Author:  Simon Cai (s53cai@uwaterloo.ca)
## Purpose: To automate archiving units from the previous submission when a new
##              submission comes into YorkTrax. Finds the previous submission's
##              Active units in the ArcGIS Pro unit layer, exports a Data Loader
##              CSV (and a backup CSV) for Salesforce, and optionally archives the
##              units in the GIS layer.
## Created: 2026-11-17
## **************************************************
##
## How to run:
##   Option A - ArcGIS Pro script tool (recommended):
##       Catalog > Toolbox > New > Script, point it at this file, and add these
##       parameters in order:
##           0  Application Id or Reg File Number   (String, required)
##           1  New submission number                (Long, required)
##           2  Also update the GIS layer            (Boolean, optional)
##   Option B - ArcGIS Pro Python window:
##       Fill in the DEFAULT_* values in the config section and run the file.
##
## Nothing in the GIS layer is edited unless "Also update the GIS layer" is True.
## By default the script only previews the units and writes the CSVs.
##

import csv
import datetime
import os

import arcpy


## **************************************************
## Config - check these against the unit layer before first use
## **************************************************

# Layer name as it appears in the Contents pane, OR a full path to the
#   feature class (e.g. r"C:\...\YorkTrax.sde\GIS.Units")
UNIT_LAYER = "Units"                                    # TODO: confirm

# Folder where the CSVs get saved
OUTPUT_FOLDER = r"C:\YorkTrax\DataLoads"                # TODO: confirm

# Field names IN THE GIS LAYER (these may differ from the Salesforce API names)
FIELDS = {
    "sfId":       "Id",                     # Salesforce Statistic record Id   TODO
    "appId":      "Application__c",         # Salesforce Application Id        TODO
    "regFile":    "Reg_File_Number",        # Reg File Number                  TODO
    "submission": "Submission_Number__c",   # Submission number on the unit    TODO
    "status":     "Record_Status__c",       # Active / Archived                TODO
    "gisId":      "GIS_ID__c",              # GIS ID (for reference only)      TODO
}

# Field types left out of the CSVs - they can't be written as text
SKIP_FIELD_TYPES = ("Geometry", "Blob", "Raster")

ACTIVE = "Active"
ARCHIVED = "Archived"

# Set to True if the unit layer is in a VERSIONED enterprise geodatabase
IS_VERSIONED = False                                    # TODO: confirm

# Only used when running from the Python window (Option B)
DEFAULT_SEARCH_VALUE = ""        # e.g. "a0X5x000001AbCd" or a Reg File Number
DEFAULT_NEW_SUBMISSION = 0       # e.g. 5
DEFAULT_UPDATE_LAYER = False


## **************************************************
## Helper Functions
## **************************************************

def logMsg(msg):
    '''
    Consumes msg: a String message. Prints msg to the geoprocessing messages
        (script tool) and the console, returns None.

    Effects: Prints to the screen.

    logMsg: Str -> None
    '''
    arcpy.AddMessage(msg)
    print(msg)


def warnMsg(msg):
    '''
    Consumes msg: a String message. Prints msg as a warning to the
        geoprocessing messages and the console, returns None.

    Effects: Prints to the screen.

    warnMsg: Str -> None
    '''
    arcpy.AddWarning(msg)
    print("WARNING: " + msg)


def getFieldType(dataset, fieldName):
    '''
    Consumes dataset: a Path to a feature class, and fieldName: a String field
        name. Returns the arcpy field type of fieldName (e.g. 'String', 'Integer').

    Requires: fieldName exists in dataset, otherwise raises a ValueError.

    getFieldType: Path Str -> Str
    '''
    for field in arcpy.ListFields(dataset):
        if field.name.lower() == fieldName.lower():
            return field.type
    raise ValueError(f"Field '{fieldName}' not found in {dataset}. "
                     f"Fix the FIELDS dictionary in the config section.")


def toSqlValue(dataset, fieldName, value):
    '''
    Consumes dataset: a Path to a feature class, fieldName: a String field name,
        and value: the value to compare against. Returns value formatted for a
        WHERE clause - text fields get quotes (with single quotes escaped),
        number fields do not. This lets the script work whether the submission
        number is stored as text or as a number.

    toSqlValue: Path Str Any -> Str
    '''
    if getFieldType(dataset, fieldName) in ("String", "Guid", "GlobalID"):
        return "'" + str(value).replace("'", "''") + "'"
    return str(int(value))


def findWorkspace(dataset):
    '''
    Consumes dataset: a Path to a feature class. Walks up the path until it
        reaches the geodatabase, returns the geodatabase Path (needed to start
        an edit session).

    Requires: dataset is inside a geodatabase, otherwise raises a RuntimeError.

    findWorkspace: Path -> Path
    '''
    path = dataset
    while path:
        if arcpy.Describe(path).dataType == "Workspace":
            return path
        path = os.path.dirname(path)
    raise RuntimeError(f"Could not find the geodatabase for {dataset}")


def getInputs():
    '''
    Reads the script tool parameters, or falls back to the DEFAULT_* values when
        run from the Python window. Returns a Tuple of the search value (String),
        new submission number (Int), and whether to update the layer (Bool).

    Requires: a search value is given and the new submission number is >= 2,
        otherwise raises a ValueError.

    getInputs: None -> (Str, Int, Bool)
    '''
    searchValue = arcpy.GetParameterAsText(0) or DEFAULT_SEARCH_VALUE

    newSubText = arcpy.GetParameterAsText(1)
    newSubmission = int(newSubText) if newSubText else DEFAULT_NEW_SUBMISSION

    updateText = arcpy.GetParameterAsText(2)
    updateLayer = (updateText.lower() == "true") if updateText else DEFAULT_UPDATE_LAYER

    if not searchValue.strip():
        raise ValueError("Enter an Application Id or Reg File Number.")
    if newSubmission < 2:
        raise ValueError("New submission number must be 2 or higher "
                         "(there is no previous submission to archive).")

    return searchValue.strip(), newSubmission, updateLayer


def getAllFields(dataset):
    '''
    Consumes dataset: a Path to a feature class. Returns a List of every field
        name in dataset, except geometry/blob/raster fields (e.g. Shape) which
        can't be written to a CSV.

    getAllFields: Path -> (Listof Str)
    '''
    return [field.name for field in arcpy.ListFields(dataset)
            if field.type not in SKIP_FIELD_TYPES]


def countRows(dataset, whereClause):
    '''
    Consumes dataset: a Path to a feature class, and whereClause: a String SQL
        filter. Returns the number of rows in dataset that match whereClause.

    countRows: Path Str -> Int
    '''
    count = 0
    with arcpy.da.SearchCursor(dataset, ["OID@"], whereClause) as cursor:
        for _ in cursor:
            count += 1
    return count


def writeDataLoadCsv(rows, fieldNames, outfile):
    '''
    Consumes rows: a List of Dicts (one per unit), fieldNames: a List of the
        field names to write as columns, and outfile: a Path for the CSV.
        Writes a Data Loader file with ALL fields, where the status field is
        set to Archived, returns None. Units without a Salesforce Id are
        skipped since Data Loader can't match them.

    Effects: Writes a CSV file to outfile.

    writeDataLoadCsv: (Listof Dict) (Listof Str) Path -> None
    '''
    with open(outfile, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldNames)
        writer.writeheader()
        for row in rows:
            if row[FIELDS["sfId"]]:
                archivedRow = dict(row)                 # Copy so the backup keeps the original
                archivedRow[FIELDS["status"]] = ARCHIVED
                writer.writerow(archivedRow)


def writeBackupCsv(rows, fieldNames, outfile):
    '''
    Consumes rows: a List of Dicts (one per unit), fieldNames: a List of the
        field names to write as columns, and outfile: a Path for the CSV.
        Writes a backup of each unit's ORIGINAL values (all fields), returns
        None. To undo an archive, load this file with Data Loader - it sets
        the status back to what it was.

    Effects: Writes a CSV file to outfile.

    writeBackupCsv: (Listof Dict) (Listof Str) Path -> None
    '''
    with open(outfile, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldNames)
        writer.writeheader()
        writer.writerows(rows)


def archiveInLayer(dataset, whereClause):
    '''
    Consumes dataset: a Path to a feature class, and whereClause: a String SQL
        filter. Sets the status field to Archived for every matching unit inside
        an edit session, returns the number of units updated (Int). If anything
        fails, the edits are discarded.

    Effects: Edits the GIS layer.

    archiveInLayer: Path Str -> Int
    '''
    edit = arcpy.da.Editor(findWorkspace(dataset))
    edit.startEditing(False, IS_VERSIONED)
    edit.startOperation()

    try:
        updated = 0
        with arcpy.da.UpdateCursor(dataset, [FIELDS["status"]], whereClause) as cursor:
            for row in cursor:
                row[0] = ARCHIVED
                cursor.updateRow(row)
                updated += 1

        edit.stopOperation()
        edit.stopEditing(True)      # True = save edits
        return updated

    except Exception:
        edit.abortOperation()
        edit.stopEditing(False)     # False = discard edits
        raise


## **************************************************
## Main
## **************************************************

def main():
    '''
    Runs the full archive process: finds the previous submission's Active units,
        selects them in the map, writes the Data Loader and backup CSVs, and
        optionally archives them in the GIS layer. Returns None.

    Effects: Writes CSV files to OUTPUT_FOLDER, selects features in the map,
        prints progress, and (if updateLayer is True) edits the GIS layer.

    main: None -> None
    '''
    searchValue, newSubmission, updateLayer = getInputs()
    prevSubmission = newSubmission - 1

    # Use the underlying feature class, not the map layer - a layer's current
    #   selection or definition query would silently filter the cursors
    dataset = arcpy.Describe(UNIT_LAYER).catalogPath

    def fld(key):
        return arcpy.AddFieldDelimiters(dataset, FIELDS[key])

    # Build the WHERE clauses
    #   Match the application by EITHER identifier, then filter by submission
    whereApp = (f"({fld('appId')} = {toSqlValue(dataset, FIELDS['appId'], searchValue)}"
                f" OR {fld('regFile')} = {toSqlValue(dataset, FIELDS['regFile'], searchValue)})")

    wherePrev = (f"{whereApp}"
                 f" AND {fld('submission')} = {toSqlValue(dataset, FIELDS['submission'], prevSubmission)}"
                 f" AND {fld('status')} = '{ACTIVE}'")

    whereNew = (f"{whereApp}"
                f" AND {fld('submission')} = {toSqlValue(dataset, FIELDS['submission'], newSubmission)}")

    logMsg(f"Application: {searchValue}")
    logMsg(f"New submission: {newSubmission} -> archiving submission {prevSubmission}")
    logMsg(f"Filter: {wherePrev}")

    # Safety check - if the new submission's units aren't in the layer yet,
    #   archiving the old ones would leave the application with no Active units
    if countRows(dataset, whereNew) == 0:
        warnMsg(f"No units found for submission {newSubmission}. Make sure the "
                f"new submission's units are loaded before archiving the old ones.")

    # Read the units to archive into a List of Dicts - every field is kept
    cursorFields = getAllFields(dataset)
    rows = []
    with arcpy.da.SearchCursor(dataset, cursorFields, wherePrev) as cursor:
        for row in cursor:
            rows.append(dict(zip(cursorFields, row)))

    if not rows:
        warnMsg("No Active units found on the previous submission. Nothing to do.")
        return

    logMsg(f"Found {len(rows)} Active unit(s) on submission {prevSubmission}.")

    # Units without a Salesforce Id can't be updated by Data Loader
    missingId = [row for row in rows if not row[FIELDS["sfId"]]]
    if missingId:
        warnMsg(f"{len(missingId)} unit(s) have no Salesforce Id and will NOT be in "
                f"the load file. GIS IDs: "
                + ", ".join(str(row[FIELDS["gisId"]]) for row in missingId))

    # Select the units in the map for a visual check
    try:
        arcpy.management.SelectLayerByAttribute(UNIT_LAYER, "NEW_SELECTION", wherePrev)
        logMsg("Units are selected in the map for review.")
    except arcpy.ExecuteError:
        pass    # Running outside a map (e.g. a full path) - skip selecting

    # Write the CSVs
    os.makedirs(OUTPUT_FOLDER, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    safeName = "".join(c if c.isalnum() else "_" for c in searchValue)
    baseName = f"{safeName}_sub{prevSubmission}_{stamp}"

    loadOutfile = f"{OUTPUT_FOLDER}/{baseName}_DATALOAD.csv"
    backupOutfile = f"{OUTPUT_FOLDER}/{baseName}_BACKUP.csv"

    writeDataLoadCsv(rows, cursorFields, loadOutfile)
    writeBackupCsv(rows, cursorFields, backupOutfile)

    logMsg(f"Data Loader file: {loadOutfile}")
    logMsg(f"Backup file:      {backupOutfile}")

    # Optionally archive in the GIS layer
    if not updateLayer:
        logMsg("Preview only - the GIS layer was NOT changed. "
               "Re-run with 'Also update the GIS layer' checked to archive there too.")
        return

    updated = archiveInLayer(dataset, wherePrev)
    logMsg(f"Archived {updated} unit(s) in the GIS layer.")
    logMsg("Done Archiving")


if __name__ == "__main__":
    main()