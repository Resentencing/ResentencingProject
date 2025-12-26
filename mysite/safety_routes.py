#!/usr/bin/env python3
"""
Safety Routes for RSCAP Data Management

This module provides Flask routes for monitoring and managing the upload safety system.
"""

from flask import Blueprint, render_template, jsonify, request, session
from upload_safety import UploadSafetyManager
from enhanced_upload_route import get_upload_safety_status, cleanup_failed_uploads
import os
import json

# Create blueprint for safety routes
safety_bp = Blueprint('safety', __name__, url_prefix='/safety')

@safety_bp.route('/status')
def safety_status():
    """
    Get current status of the upload safety system.
    """
    if not session.get('logged_in'):
        return jsonify({"error": "User not logged in"}), 401
    
    try:
        status = get_upload_safety_status()
        return jsonify(status)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@safety_bp.route('/report')
def safety_report():
    """
    Generate and return a comprehensive safety report.
    """
    if not session.get('logged_in'):
        return jsonify({"error": "User not logged in"}), 401
    
    try:
        safety_manager = UploadSafetyManager()
        report = safety_manager.generate_safety_report()
        return jsonify(report)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@safety_bp.route('/failed_uploads')
def failed_uploads():
    """
    Get list of failed uploads.
    """
    if not session.get('logged_in'):
        return jsonify({"error": "User not logged in"}), 401
    
    try:
        safety_manager = UploadSafetyManager()
        failed_uploads = safety_manager.get_failed_uploads()
        return jsonify({
            "failed_uploads": failed_uploads,
            "count": len(failed_uploads)
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@safety_bp.route('/shadow_copies')
def shadow_copies():
    """
    Get information about shadow copies.
    """
    if not session.get('logged_in'):
        return jsonify({"error": "User not logged in"}), 401
    
    try:
        safety_manager = UploadSafetyManager()
        shadow_dir = safety_manager.shadow_dir
        
        shadow_files = []
        if os.path.exists(shadow_dir):
            for filename in os.listdir(shadow_dir):
                file_path = os.path.join(shadow_dir, filename)
                if os.path.isfile(file_path):
                    stat = os.stat(file_path)
                    shadow_files.append({
                        "filename": filename,
                        "size": stat.st_size,
                        "created": stat.st_ctime,
                        "modified": stat.st_mtime
                    })
        
        return jsonify({
            "shadow_copies": shadow_files,
            "count": len(shadow_files),
            "directory": shadow_dir
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@safety_bp.route('/cleanup', methods=['POST'])
def cleanup_system():
    """
    Clean up old shadow copies and failed uploads.
    """
    if not session.get('logged_in'):
        return jsonify({"error": "User not logged in"}), 401
    
    try:
        safety_manager = UploadSafetyManager()
        
        # Clean up old shadow copies
        safety_manager.cleanup_old_shadow_copies(max_age_hours=48)
        
        # Clean up failed uploads
        cleanup_results = cleanup_failed_uploads()
        
        return jsonify({
            "success": True,
            "message": "Cleanup completed successfully",
            "cleanup_results": cleanup_results
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@safety_bp.route('/logs')
def safety_logs():
    """
    Get recent safety logs.
    """
    if not session.get('logged_in'):
        return jsonify({"error": "User not logged in"}), 401
    
    try:
        safety_manager = UploadSafetyManager()
        log_file = safety_manager.safety_log_file
        
        logs = []
        if os.path.exists(log_file):
            with open(log_file, 'r') as f:
                lines = f.readlines()
                # Return last 100 lines
                logs = lines[-100:] if len(lines) > 100 else lines
        
        return jsonify({
            "logs": logs,
            "count": len(logs)
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@safety_bp.route('/errors')
def error_logs():
    """
    Get error logs from the safety system.
    """
    if not session.get('logged_in'):
        return jsonify({"error": "User not logged in"}), 401
    
    try:
        safety_manager = UploadSafetyManager()
        error_file = safety_manager.error_log_file
        
        errors = []
        if os.path.exists(error_file):
            with open(error_file, 'r') as f:
                errors = json.load(f)
        
        return jsonify({
            "errors": errors,
            "count": len(errors)
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@safety_bp.route('/dashboard')
def safety_dashboard():
    """
    Render the safety dashboard page.
    """
    if not session.get('logged_in'):
        return jsonify({"error": "User not logged in"}), 401
    
    return render_template('safety_dashboard.html')

# Function to integrate safety routes into main app
def register_safety_routes(app):
    """
    Register safety routes with the main Flask application.
    
    Args:
        app: Flask application instance
    """
    app.register_blueprint(safety_bp)
    return app
