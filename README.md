# Resentencing Project

A Flask-based web application for processing and analyzing resentencing documents with AI-powered database queries.

## Features

- **PDF Processing**: Upload and process PDF documents with OCR
- **Database Integration**: Store and query case metadata (when running on PythonAnywhere)
- **AI-Powered Queries**: Natural language database queries using OpenAI
- **File Management**: Upload, process, and manage documents
- **Secure Authentication**: Password-protected access

## Prerequisites

- Python 3.8 or higher
- PythonAnywhere account (paid plan for SSH access)
- OpenAI API key
- MySQL database (hosted on PythonAnywhere)

## Installation

### Quick Team Setup

For new team members, run these commands:

```bash
git clone <repository-url>
cd ResentencingProject
pip install -r requirements.txt
cp env.template .env
# Edit .env with your credentials
python mysite/OCRWebApp.py  # Backend
python frontend/flask_app.py # Frontend
```

### Detailed Installation

1. **Clone the repository**
   ```bash
   git clone <repository-url>
   cd ResentencingProject
   ```

2. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

3. **Set up environment variables**
   ```bash
   cp env.template .env
   ```
   
   Edit `.env` file with your credentials:
   ```env
   # PythonAnywhere Database Configuration
   PYTHONANYWHERE_USERNAME=your_username
   PYTHONANYWHERE_PASSWORD=your_website_password
   PYTHONANYWHERE_DB_PASSWORD=your_mysql_password
   PYTHONANYWHERE_DB_NAME=your_username$your_database_name
   
   # OpenAI Configuration
   OPENAI_API_KEY=your_openai_api_key
   
   # Flask Configuration
   FLASK_SECRET_KEY=your_flask_secret_key
   FLASK_DEBUG=True
   ```

## Configuration

### PythonAnywhere Setup

1. **Database Configuration**
   - Go to PythonAnywhere → Databases
   - Note your database hostname, username, and password
   - Ensure you have a paid plan for SSH access

2. **SSH Access**
   - Required for local development
   - Use your PythonAnywhere website login password for SSH
   - Database password is different from website password

### OpenAI Setup

1. **Get API Key**
   - Visit [OpenAI Platform](https://platform.openai.com/api-keys)
   - Create a new API key
   - Add to your `.env` file

## Usage

### Running the Application

1. **Start the backend server**
   ```bash
   python mysite/OCRWebApp.py
   ```

2. **Start the frontend server**
   ```bash
   python frontend/flask_app.py
   ```

3. **Access the application**
   - Backend: http://127.0.0.1:5000
   - Frontend: http://127.0.0.1:5001 (or as configured)
   - Login password: `password` (default)

### Database Access

**Current Status**: Database connection from local machine is being troubleshooted.

**Working Options**:
- ✅ **PythonAnywhere**: Full database access when running on PythonAnywhere servers
- ❌ **Local Development**: SSH tunnel connection needs troubleshooting

**To test database connection locally**:
```bash
python mysite/dbconnector_ssh.py
```

**Note**: If local database connection fails, you can still:
- Test all other features (file upload, OCR, etc.)
- Run the full application on PythonAnywhere where database works
- Use the AI features with sample data

### File Structure

```
ResentencingProject/
├── mysite/                 # Backend Flask application
│   ├── OCRWebApp.py       # Main Flask app
│   ├── dbconnector.py     # Database connector (PythonAnywhere)
│   ├── dbconnector_ssh.py # SSH tunnel connector (local) - IN DEVELOPMENT
│   └── templates/         # HTML templates
├── frontend/              # Frontend Flask application
│   ├── flask_app.py      # Frontend Flask app
│   └── templates/        # Frontend templates
├── shared/               # Shared resources
│   └── archive_directory/ # PDF archive
├── uploads/              # Upload directory
├── processed/            # Processed files
├── .env                  # Environment variables (create from template)
├── env.template          # Environment template
├── requirements.txt      # Python dependencies
└── README.md            # This file
```

## Database Schema

### Tables

1. **pdfs**: PDF file references
   - `id` (int, Primary Key, auto_increment)
   - `filename` (varchar(255), NOT NULL, UNIQUE)
   - `file_path` (varchar(500), NOT NULL)

2. **metadata**: Case information and resentencing data
   - `id` (int, Primary Key, auto_increment)
   - `pdf_id` (int, NOT NULL, Foreign Key to pdfs)
   - `date_stamped` (varchar(50))
   - `judge` (varchar(255))
   - `county` (varchar(255))
   - `address` (text)
   - `_______` (varchar(255))
   - `cdcr_number` (varchar(50))
   - `case_number` (varchar(50))
   - `sentence_date` (varchar(50))
   - `cohort` (varchar(255))
   - `pid_no` (varchar(50))
   - `institution` (varchar(255))
   - `old_release_date` (varchar(50))
   - `documents_printed_date` (varchar(50))
   - `letter_creation_date` (varchar(50))
   - `secretary_send_date` (varchar(50))
   - `sec_decision` (varchar(255))
   - `court_mail_date` (varchar(50))
   - `court_response_date` (varchar(50))
   - `resentencing_hearing_date` (varchar(50))
   - `action_taken` (varchar(255))
   - `days_reduced` (int)
   - `years_reduced` (int)
   - `cost_savings` (decimal(10,2))
   - `notes` (text)
   - `completion_date` (varchar(50))
   - `post_release` (varchar(255))
   - `isl_dsl` (varchar(50))
   - `parole_eligibility_date` (varchar(50))
   - `race` (varchar(100))
   - `ethnicity` (varchar(100))

3. **text_files**: Extracted text file references
   - `id` (int, Primary Key, auto_increment)
   - `pdf_id` (int, NOT NULL, Foreign Key to pdfs)
   - `text_file_path` (varchar(500), NOT NULL)

### Relationships
- `metadata.pdf_id` → `pdfs.id`
- `text_files.pdf_id` → `pdfs.id`

## AI Query Examples

The application supports natural language queries like:
- "How many cases are in the database?"
- "Show me all judges"
- "What counties are represented?"
- "How many cases were processed in 2023?"

**Note**: AI queries require database connection to work properly.

## Troubleshooting

### Common Issues

1. **Database Connection Failed**
   - Verify PythonAnywhere credentials in `.env`
   - Ensure you have a paid PythonAnywhere plan
   - SSH tunnel connection is being troubleshooted
   - **Workaround**: Run application on PythonAnywhere

2. **OpenAI API Errors**
   - Verify API key in `.env`
   - Check API key permissions and billing

3. **File Upload Issues**
   - Ensure upload directories exist
   - Check file permissions

### SSH Tunnel Issues (Currently Being Troubleshooted)

If SSH tunnel connection fails:
1. Verify PythonAnywhere username and password
2. Ensure paid account for SSH access
3. Check firewall settings
4. Try different local ports if 3306 is in use
5. **Current Issue**: MySQL user permissions for external connections

### Development Workflow

**For full functionality**:
1. Develop locally (file upload, OCR, etc.)
2. Deploy to PythonAnywhere for database testing
3. SSH tunnel connection being resolved

## Security Notes

- Never commit `.env` file to version control
- Use strong passwords for all services
- Regularly rotate API keys
- Keep dependencies updated

## Support

For issues related to:
- **PythonAnywhere**: Check their documentation
- **OpenAI API**: Visit OpenAI platform
- **Application**: Check logs and error messages
- **Database Connection**: Team is troubleshooting SSH tunnel access

## License

[Add your license information here] 
