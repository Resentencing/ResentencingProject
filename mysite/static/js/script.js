document.addEventListener('DOMContentLoaded', function () {
    let selectedFiles = []; // Array to hold selected files
    let selectedExcelFiles = []; // For Excel uploads
    let processingInterval = null; // Declare globally

    const fileInput = document.getElementById('fileInput');
    const fileList = document.getElementById('fileList');
    const loadingIndicator = document.getElementById('loadingIndicator');
    const progressBar = document.getElementById('progressBar');

    const excelFileInput = document.getElementById('excelFileInput');
    const excelFileList = document.getElementById('excelFileList');

    // Append files to the list and prevent duplicates
    fileInput?.addEventListener('change', () => {
        fileList.innerHTML = '';
        Array.from(fileInput.files).forEach(file => {
            if (!selectedFiles.map(f => f.name).includes(file.name)) {
                selectedFiles.push(file);
                const li = document.createElement('li');
                li.textContent = file.name;
                fileList.appendChild(li);
            }
        });
    });

    excelFileInput?.addEventListener('change', () => {
        excelFileList.innerHTML = '';
        Array.from(excelFileInput.files).forEach(file => {
            if (!selectedExcelFiles.map(f => f.name).includes(file.name)) {
                selectedExcelFiles.push(file);
                const li = document.createElement('li');
                li.textContent = file.name;
                excelFileList.appendChild(li);
            }
        });
    });

    // Process PDF files
    document.getElementById('processButton').addEventListener('click', () => {
        if (selectedFiles.length === 0) {
            alert("Please select files first.");
            return;
        }
        loadingIndicator.style.visibility = 'visible';
        progressBar.value = 0;

        const formData = new FormData();
        selectedFiles.forEach(file => {
            formData.append('files[]', file);
        });

        fetch('/upload_and_process', {
            method: 'POST',
            body: formData,
        }).then(response => response.json())
        .then(data => {
            alert(data.message);
            if (data.status === 'success') {
                progressBar.value = 100;
                document.getElementById('successSound').play(); // Play sound on success
            }
            loadingIndicator.style.visibility = 'hidden';
            selectedFiles = [];
            fileList.innerHTML = '';

        })
        .catch(error => {
            console.error('Error processing files:', error);
            alert('Error processing files: ' + error.message);
            loadingIndicator.style.visibility = 'hidden';
        });
    });

    // Download processed files
    document.getElementById('downloadButton')?.addEventListener('click', () => {
        fetch('/download_files')
            .then(response => {
                if (!response.ok) {
                    throw new Error('No files to download.');
                }
                return response.blob();
            })
            .then(blob => {
                const url = window.URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.style.display = 'none';
                a.href = url;
                a.download = 'Corrected_Files.zip';
                document.body.appendChild(a);
                a.click();
                window.URL.revokeObjectURL(url);
            })
            .catch(error => {
                console.error('Download error:', error);
                alert(error.message);
            });
    });

    // Clear files from server
    document.getElementById('clearButton')?.addEventListener('click', () => {
        fetch('/clear_files', { method: 'POST' })
            .then(response => response.json())
            .then(data => {
                alert(data.message);
                fileList.innerHTML = '';
            })
            .catch(error => {
                console.error('Error clearing files:', error);
                alert('Error clearing files: ' + error.message);
            });
    });

    document.getElementById('clearExcelButton')?.addEventListener('click', () => {
        fetch('/clear_excel', { method: 'POST' })
            .then(response => response.json())
            .then(data => {
                alert(data.message);
                // Optionally clear out the excelFileList in the UI
                document.getElementById('excelFileList').innerHTML = '';
            })
            .catch(error => {
                console.error('Error clearing Excel files:', error);
                alert('Error clearing Excel files: ' + error.message);
            });
    });

    // Upload corrected files to database
    document.getElementById('uploadDatabaseButton')?.addEventListener('click', () => {
        console.log("Uploading to database...");

        fetch('/upload_to_database', {
            method: 'POST',
        })
        .then(response => {
            console.log(`Server response status: ${response.status}`);
            return response.json();
        })
        .then(data => {
            if (data.error) {
                console.error(`Error from server: ${data.error}`);
                alert(`Error uploading to database: ${data.error}`);
            } else {
                alert(data.message);
            }
        })
        .catch(error => {
            console.error('Error uploading to database:', error);
            alert(`Error uploading to database: ${error.message}`);
        });
    });

    document.getElementById('uploadExcelButton')?.addEventListener('click', () => {
        if (selectedExcelFiles.length === 0) {
            alert("Please select Excel files first.");
            return;
        }

        const formData = new FormData();
        selectedExcelFiles.forEach(file => {
            formData.append('excel_files[]', file);
        });

        fetch('/upload_excel', {
            method: 'POST',
            body: formData,
        })
        .then(response => response.json())
        .then(data => {
            if (data.status === 'success') {
                alert(data.message);
            } else {
                alert(`Error: ${data.message}`);
            }
            // Clear the file list
            selectedExcelFiles = [];
            excelFileList.innerHTML = '';
        })
        .catch(error => {
            console.error('Error uploading Excel files:', error);
            alert('Error uploading Excel files: ' + error.message);
        });
    });

    // Handle AI query submission
    document.getElementById('sendQueryButton')?.addEventListener('click', () => {
        const userQuery = document.getElementById('userQuery').value.trim();
        if (!userQuery) {
            alert("Please enter a query.");
            return;
        }

        const aiResponseDiv = document.getElementById('aiResponse');
        aiResponseDiv.innerHTML = '<p>Loading...</p>'; // Show loading indicator

        fetch('/query_ai', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ query: userQuery }),
        })
            .then(response => response.json())
            .then(data => {
                if (data.response) {
                    aiResponseDiv.innerHTML = `<p>${data.response}</p>`;
                } else {
                    aiResponseDiv.innerHTML = `<p>Error: ${data.error}</p>`;
                }
            })
            .catch(error => {
                console.error('Error querying AI:', error);
                aiResponseDiv.innerHTML = `<p>An error occurred: ${error.message}</p>`;
            });
    });
});
