#!/home/RSCAP/.virtualenvs/myvenv/bin/python
import os
import json
import pandas as pd
import numpy as np
import re

def extract_metadata_from_text_files(input_folder, output_file):
    """
    Extracts metadata from text files in the input folder and saves it in JSON format.
    """
    months = ["January", "February", "March", "April", "May", "June", "July", "August",
              "September", "October", "November", "December"]

    RandE_excel=None
    openwb=None
    for f in os.listdir("/home/RSCAP/mysite/Excel"):
        if "Race_Data" in f:
            RandE_excel=pd.read_excel("./Excel/"+f)
        else:
            openwb=pd.read_excel("./Excel/"+f,sheet_name='1170(d)(1)') #will need to change this line if the sheet name in the excel sheet changes in the future

    print(openwb.columns)

    missedentry=open("./logs/Missedentries.json","a",encoding="utf-8")
    tagsjson=open(output_file,"w",encoding="utf-8")
    jsonarray=[]

    for filename in os.listdir(input_folder):
        if filename.endswith(".txt"):
            file_path = os.path.join(input_folder, filename)
            with open(file_path, "r", encoding="utf-8") as textfile:
                text = textfile.readlines()

            outputdict = {
                "filename": filename.replace(".txt", ".pdf")
            }

            for linenumber, line in enumerate(text):

                if "Honorable" in text[linenumber] or "Honorabie" in text[linenumber]: #because the date of the letter is a stamp the OCR might not pick up on it.  In that case we use the guaranteed typed judge
                    for month in months:
                        if month in text[linenumber-1]:
                            outputdict["DATE STAMPED"]= text[linenumber-1].strip()
                            break
                    outputstring=text[linenumber].replace("The","")                    #judge
                    outputstring=outputstring.replace("Honorable","").replace("Honorabie","")
                    outputstring=outputstring.strip()
                    outputdict["JUDGE"]=' '.join(outputstring.split())

                    outputstring=text[linenumber+2].replace("County","").replace("of","")                                           #county
                    outputstring=outputstring.strip()
                    outputdict["COUNTY"] = outputstring

                    outputstring = text[linenumber+3].replace('\n',', ')+text[linenumber+4].strip()
                    outputdict["ADDRESS"] = ' '.join(outputstring.split())      #address

                    outputstring=text[linenumber+5].replace("Re: ","").replace("Re; ","").strip()
                    outputarray=outputstring.split()
                    reverseorder=False
                    for index in range(len(outputarray)):
                        if "," in outputarray[index]:
                            outputarray[index]=outputarray[index].replace(",","")
                            if(index == 0):
                                reverseorder=True


                    if reverseorder:
                        if(len(outputarray)>2):
                            formattedname=" ".join(outputarray[1:]) #assuming last name in front we join the string with everything except last name
                            outputdict["CNAME"]=" ".join([formattedname,outputarray[0]]) #then do a final join with the last name
                        else:
                            outputdict["CNAME"]=" ".join([outputarray[1],outputarray[0]])
                    else:
                        outputdict["CNAME"]=" ".join(outputarray)                    #convict name

                    filenamesplit=re.split(r'[\.\_\-\s\(]',filename)
                    for string in filenamesplit:
                        string.strip()
                        if(bool(re.search(r'\d',string)) and (len(string)==6) and bool(re.search(r'[A-Z]',string))): # checks if there is a Capital Letter and digit in the string and checks if the length of the # is 6
                            outputdict['CDCR NO']=string
                            break    # get CDCR number from filename

                    # outputdict["CDCR NO"] = text[linenumber+6].replace("CDCR","").replace("No:","").replace("CDC","").replace("No.:","").strip()     # get CDCR number from letter
                    outputdict["CASE NO"] = text[linenumber+7].replace("Case","").replace("No:","").replace("No.:","").strip()     #Case number
                    outputdict["SENTENCE DATE"] = text[linenumber+8].replace("Date","").replace("of","").replace("Sentence:","").strip()#Original Sentence Date
                    linenumber=linenumber+10
                    print("Extracted metadata for: " + filename)
                    break

                    #This space is reserved for searching more in the letter


        # Save Excel metadata to JSON
        try:
            RandE_entry=RandE_excel[RandE_excel.iloc[:,0] == outputdict["CDCR NO"]]
            series=openwb.loc[openwb['CDC #'] == outputdict["CDCR NO"]]
            if(series.empty):
                print("cannot find the CDCR # " + outputdict["CDCR NO"])
                missedentry.write(json.dumps(outputdict,indent=3,default=str)) #current fix for datetime objects may need to change later is default=str
            else:
                # Check if this Excel entry has multiple case numbers
                excel_case_numbers = str(series.iat[0,6]) if pd.notna(series.iat[0,6]) else ""  # Case # column
                
                # Parse multiple case numbers if they exist (separated by " and ")
                if " and " in excel_case_numbers:
                    case_number_list = [case.strip() for case in excel_case_numbers.split(" and ")]
                    print(f"Found multiple case numbers for CDC {outputdict['CDCR NO']}: {case_number_list}")
                else:
                    case_number_list = [excel_case_numbers] if excel_case_numbers else [outputdict["CASE NO"]]
                
                # Create a separate metadata entry for each case number
                for case_num in case_number_list:
                    # Create a copy of the base metadata
                    case_outputdict = outputdict.copy()
                    case_outputdict["CASE NO"] = case_num
                    
                    # Add Excel metadata
                    case_outputdict["COHORT"]=series.iat[0,0]
                    case_outputdict["PID NO"]=series.iat[0,3]
                    case_outputdict["INSTITUTION"]=series.iat[0,4]
                    case_outputdict["COUNTY"]=series.iat[0,5].replace("*","")
                    case_outputdict["OLD RELEASE DATE"]=series.iat[0,7]
                    case_outputdict["DOCUMENTS PRINTED DATE"]=series.iat[0,8]
                    case_outputdict["LETTER CREATION DATE"]=series.iat[0,9]
                    case_outputdict["SECRETARY SEND DATE"]=series.iat[0,10]
                    case_outputdict["SEC DECISION"]=series.iat[0,11]
                    case_outputdict["COURT MAIL DATE"]=series.iat[0,12]
                    case_outputdict["COURT RESPONSE DATE"]=series.iat[0,13]
                    case_outputdict["RESENTENCING HEARING DATE"]=series.iat[0,14]
                    case_outputdict["ACTION TAKEN"]=series.iat[0,15]
                    case_outputdict["DAYS REDUCED"]=series.iat[0,16]
                    case_outputdict["YEARS REDUCED"]=series.iat[0,17]
                    case_outputdict["COST SAVINGS"]=series.iat[0,18]
                    case_outputdict["NOTES"]=series.iat[0,19]
                    case_outputdict["COMPLETION DATE"]=series.iat[0,20]
                    case_outputdict["POST RELEASE"]=series.iat[0,21]
                    case_outputdict["ISL DSL"]=series.iat[0,22]
                    case_outputdict["PAROLE ELIGIBILITY DATE"]=series.iat[0,23]
                    
                    if(not RandE_entry.empty):
                        case_outputdict["RACE"] = RandE_entry.iloc[0,2]
                        case_outputdict["ETHNICITY"] = RandE_entry.iloc[0,3]
                    
                    jsonarray.append(case_outputdict)
                    print(f"Added metadata entry for case number: {case_num}")
        except:
            print("Could not find related tags in the letter writing.  logging...")
            missedentry.write(json.dumps(outputdict,indent=3,default=str))

    tagjsonobject=json.dumps(jsonarray,indent=3,default=str)#writes to the jsonfile
    tagsjson.write(tagjsonobject)
    missedentry.close()
    tagsjson.close()

if __name__ == "__main__":
    input_folder = "./OCRextractions"  # Folder containing text files
    output_file = "./Jsontags/outputarrays.json"  # JSON output file
    extract_metadata_from_text_files(input_folder, output_file)
