import os

file_path='./mysite/logs/Missedentries.json'

print(os.getcwd())
if os.path.exists(file_path):
    os.remove(file_path)
    print(f"File '{file_path}' removed successfully.")
else:
    print(f"File '{file_path}' not found.")
