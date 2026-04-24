#!/home/RSCAP/.virtualenvs/myvenv/bin/python
import os
import json
import pandas as pd
import numpy as np
import re

CDCR_LABEL_PATTERN = re.compile(
    r"(?:CDCR|CDC)\s*(?:NO\.?|#|NUMBER)?\s*[:\-]?\s*([A-Z]{1,2}\d{4,5})",
    re.IGNORECASE,
)
CASE_LABEL_PATTERN = re.compile(r"CASE\s*(?:NO\.?|#)?\s*[:\-]?\s*(.+)", re.IGNORECASE)
SENTENCE_LABEL_PATTERN = re.compile(r"DATE\s*OF\s*SENTENCE\s*[:\-]?\s*(.+)", re.IGNORECASE)
RE_NAME_PATTERN = re.compile(r"RE\s*[:;]\s*(.+)", re.IGNORECASE)


def _clean(s):
    return " ".join((s or "").replace("\n", " ").split())


def _extract_primary_fields(text, filename, months):
    outputdict = {"filename": filename.replace(".txt", ".pdf")}
    for linenumber, _line in enumerate(text):
        if "Honorable" in text[linenumber] or "Honorabie" in text[linenumber]:
            if linenumber > 0:
                for month in months:
                    if month in text[linenumber - 1]:
                        outputdict["DATE STAMPED"] = text[linenumber - 1].strip()
                        break

            outputstring = text[linenumber].replace("The", "")
            outputstring = outputstring.replace("Honorable", "").replace("Honorabie", "")
            outputdict["JUDGE"] = _clean(outputstring)

            if linenumber + 2 < len(text):
                county = text[linenumber + 2].replace("County", "").replace("of", "")
                outputdict["COUNTY"] = _clean(county)

            if linenumber + 4 < len(text):
                address = text[linenumber + 3].replace("\n", ", ") + text[linenumber + 4].strip()
                outputdict["ADDRESS"] = _clean(address)

            if linenumber + 5 < len(text):
                outputstring = text[linenumber + 5].replace("Re: ", "").replace("Re; ", "").strip()
                outputarray = outputstring.split()
                reverseorder = False
                for index in range(len(outputarray)):
                    if "," in outputarray[index]:
                        outputarray[index] = outputarray[index].replace(",", "")
                        if index == 0:
                            reverseorder = True
                if outputarray:
                    if reverseorder:
                        if len(outputarray) > 2:
                            formattedname = " ".join(outputarray[1:])
                            outputdict["CNAME"] = " ".join([formattedname, outputarray[0]])
                        else:
                            outputdict["CNAME"] = " ".join([outputarray[1], outputarray[0]])
                    else:
                        outputdict["CNAME"] = " ".join(outputarray)

            # Filename-derived fallback CDCR
            filenamesplit = re.split(r"[\.\_\-\s\(]", filename)
            for string in filenamesplit:
                token = string.strip().upper()
                if bool(re.search(r"\d", token)) and len(token) == 6 and bool(re.search(r"[A-Z]", token)):
                    outputdict["CDCR NO"] = token
                    break

            if linenumber + 7 < len(text):
                outputdict["CASE NO"] = (
                    text[linenumber + 7].replace("Case", "").replace("No:", "").replace("No.:", "").strip()
                )
            if linenumber + 8 < len(text):
                outputdict["SENTENCE DATE"] = (
                    text[linenumber + 8]
                    .replace("Date", "")
                    .replace("of", "")
                    .replace("Sentence:", "")
                    .strip()
                )
            print("Extracted metadata for: " + filename)
            break
    return outputdict


def _extract_batch_candidates(text, base_outputdict):
    candidates = []
    # Always keep primary candidate first.
    candidates.append(base_outputdict.copy())

    seen_cdcr = set()
    if base_outputdict.get("CDCR NO"):
        seen_cdcr.add(base_outputdict["CDCR NO"].upper())

    for idx, line in enumerate(text):
        m = CDCR_LABEL_PATTERN.search(line or "")
        if not m:
            continue
        cdcr = m.group(1).upper().strip()
        if cdcr in seen_cdcr:
            continue
        seen_cdcr.add(cdcr)

        cand = base_outputdict.copy()
        cand["CDCR NO"] = cdcr

        # Pull nearby "Re:" name if present
        for i in range(max(0, idx - 6), min(len(text), idx + 1)):
            name_match = RE_NAME_PATTERN.search(text[i] or "")
            if name_match:
                cand["CNAME"] = _clean(name_match.group(1))

        # Pull nearby Case No / Date of Sentence if present
        for i in range(idx, min(len(text), idx + 8)):
            case_match = CASE_LABEL_PATTERN.search(text[i] or "")
            if case_match and not cand.get("CASE NO"):
                cand["CASE NO"] = _clean(case_match.group(1))
            sent_match = SENTENCE_LABEL_PATTERN.search(text[i] or "")
            if sent_match and not cand.get("SENTENCE DATE"):
                cand["SENTENCE DATE"] = _clean(sent_match.group(1))

        candidates.append(cand)

    # Deduplicate by CDCR+CASE combination
    uniq = []
    seen = set()
    for c in candidates:
        key = (c.get("CDCR NO", "").upper().strip(), c.get("CASE NO", "").upper().strip())
        if key not in seen:
            uniq.append(c)
            seen.add(key)
    return uniq


def _split_case_numbers(raw_case_value, fallback_case):
    raw = (raw_case_value or "").strip()
    fallback = (fallback_case or "").strip()
    if not raw:
        return [fallback] if fallback else [""]

    # Handle common delimiters seen in the 1170(d) log.
    normalized = re.sub(r"\s+(?:and|AND)\s+", "|", raw)
    normalized = re.sub(r"\s*(?:,|;|/|&)\s*", "|", normalized)
    parts = [p.strip() for p in normalized.split("|") if p.strip()]
    return parts if parts else ([fallback] if fallback else [raw])


def extract_metadata_from_text_files(input_folder, output_file):
    """
    Extracts metadata from text files in the input folder and saves it in JSON format.
    """
    months = ["January", "February", "March", "April", "May", "June", "July", "August",
              "September", "October", "November", "December"]

    RandE_excel=None
    openwb=None
    default_excel_dir = "/home/RSCAP/mysite/Excel"
    excel_dir = os.getenv("OCR_EXCEL_DIR", default_excel_dir)
    if not os.path.isdir(excel_dir):
        # Local fallback when running from repo root or alternate cwd.
        module_excel_dir = os.path.join(os.path.dirname(__file__), "Excel")
        cwd_excel_dir = os.path.join(os.getcwd(), "Excel")
        if os.path.isdir(module_excel_dir):
            excel_dir = module_excel_dir
        elif os.path.isdir(cwd_excel_dir):
            excel_dir = cwd_excel_dir
        else:
            excel_dir = "./Excel"
    enable_batch_expansion = os.getenv("ENABLE_BATCH_METADATA_EXPANSION", "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    for f in os.listdir(excel_dir):
        if "Race_Data" in f:
            RandE_excel=pd.read_excel(os.path.join(excel_dir, f))
        else:
            openwb=pd.read_excel(os.path.join(excel_dir, f),sheet_name='1170(d)(1)') #will need to change this line if the sheet name in the excel sheet changes in the future

    print(openwb.columns)

    missedentry=open("./logs/Missedentries.json","a",encoding="utf-8")
    tagsjson=open(output_file,"w",encoding="utf-8")
    jsonarray=[]

    for filename in os.listdir(input_folder):
        if filename.endswith(".txt"):
            file_path = os.path.join(input_folder, filename)
            with open(file_path, "r", encoding="utf-8") as textfile:
                text = textfile.readlines()

            outputdict = _extract_primary_fields(text, filename, months)
            source_pdf_name = filename.replace(".txt", ".pdf")
            if enable_batch_expansion:
                candidate_dicts = _extract_batch_candidates(text, outputdict)
            else:
                # Safe default: preserve prior single-record behavior unless explicitly enabled.
                candidate_dicts = [outputdict]

        # Save Excel metadata for each candidate (supports batch PDFs).
        for candidate in candidate_dicts:
            try:
                cdcr_no = (candidate.get("CDCR NO") or "").strip().upper()
                if not cdcr_no:
                    missedentry.write(json.dumps(candidate, indent=3, default=str))
                    continue

                RandE_entry = RandE_excel[RandE_excel.iloc[:, 0] == cdcr_no]
                series = openwb.loc[openwb["CDC #"] == cdcr_no]
                if series.empty:
                    print("cannot find the CDCR # " + cdcr_no)
                    missedentry.write(json.dumps(candidate, indent=3, default=str))
                    continue

                excel_case_numbers = str(series.iat[0, 6]) if pd.notna(series.iat[0, 6]) else ""
                case_number_list = _split_case_numbers(excel_case_numbers, candidate.get("CASE NO", ""))
                if len(case_number_list) > 1:
                    print(f"Found multiple case numbers for CDC {cdcr_no}: {case_number_list}")

                for case_num in case_number_list:
                    case_outputdict = candidate.copy()
                    if not (case_outputdict.get("filename") or "").strip():
                        # Defensive fallback: keep a stable source filename for batch entries.
                        case_outputdict["filename"] = source_pdf_name
                    case_outputdict["CDCR NO"] = cdcr_no
                    case_outputdict["CASE NO"] = case_num

                    # Add Excel metadata
                    case_outputdict["COHORT"] = series.iat[0, 0]
                    case_outputdict["PID NO"] = series.iat[0, 3]
                    case_outputdict["INSTITUTION"] = series.iat[0, 4]
                    case_outputdict["COUNTY"] = str(series.iat[0, 5]).replace("*", "")
                    case_outputdict["OLD RELEASE DATE"] = series.iat[0, 7]
                    case_outputdict["DOCUMENTS PRINTED DATE"] = series.iat[0, 8]
                    case_outputdict["LETTER CREATION DATE"] = series.iat[0, 9]
                    case_outputdict["SECRETARY SEND DATE"] = series.iat[0, 10]
                    case_outputdict["SEC DECISION"] = series.iat[0, 11]
                    case_outputdict["COURT MAIL DATE"] = series.iat[0, 12]
                    case_outputdict["COURT RESPONSE DATE"] = series.iat[0, 13]
                    case_outputdict["RESENTENCING HEARING DATE"] = series.iat[0, 14]
                    case_outputdict["ACTION TAKEN"] = series.iat[0, 15]
                    case_outputdict["DAYS REDUCED"] = series.iat[0, 16]
                    case_outputdict["YEARS REDUCED"] = series.iat[0, 17]
                    case_outputdict["COST SAVINGS"] = series.iat[0, 18]
                    case_outputdict["NOTES"] = series.iat[0, 19]
                    case_outputdict["COMPLETION DATE"] = series.iat[0, 20]
                    case_outputdict["POST RELEASE"] = series.iat[0, 21]
                    case_outputdict["ISL DSL"] = series.iat[0, 22]
                    case_outputdict["PAROLE ELIGIBILITY DATE"] = series.iat[0, 23]

                    if not RandE_entry.empty:
                        case_outputdict["RACE"] = RandE_entry.iloc[0, 2]
                        case_outputdict["ETHNICITY"] = RandE_entry.iloc[0, 3]

                    jsonarray.append(case_outputdict)
                    print(f"Added metadata entry for CDC {cdcr_no} / case number: {case_num}")
            except Exception:
                print("Could not find related tags in the letter writing.  logging...")
                missedentry.write(json.dumps(candidate, indent=3, default=str))

    tagjsonobject=json.dumps(jsonarray,indent=3,default=str)#writes to the jsonfile
    tagsjson.write(tagjsonobject)
    missedentry.close()
    tagsjson.close()

if __name__ == "__main__":
    input_folder = "./OCRextractions"  # Folder containing text files
    output_file = "./Jsontags/outputarrays.json"  # JSON output file
    extract_metadata_from_text_files(input_folder, output_file)
