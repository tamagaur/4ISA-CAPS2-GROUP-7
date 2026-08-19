import React, { useState, useRef } from 'react';
import { Upload, FileText, CheckCircle } from 'lucide-react';
import { logAction } from '../utils/auditLogger';
import './DataUpload.css';

const DataUpload = () => {
  const [uploads, setUploads] = useState([]);
  const [dragActive, setDragActive] = useState(false);
  const fileInputRef = useRef(null);

  // Trigger file dialog
  const onButtonClick = () => {
    fileInputRef.current.click();
  };

  // Process selected files (interactive uploading simulation)
  const handleFiles = (selectedFiles) => {
    const newUploads = Array.from(selectedFiles).map((file, index) => {
      const uploadId = Date.now() + '-' + index;
      
      // Simulate progressive upload
      let progress = 0;
      const interval = setInterval(() => {
        setUploads((prev) =>
          prev.map((item) => {
            if (item.id === uploadId) {
              if (progress >= 100) {
                clearInterval(interval);
                logAction('Data Upload', `Uploaded file: ${file.name}`);
                return { ...item, progress: 100, status: 'Completed' };
              }
              progress += 10;
              return { ...item, progress };
            }
            return item;
          })
        );
      }, 150);

      // Convert bytes to human readable size
      const formatSize = (bytes) => {
        if (bytes === 0) return '0 Bytes';
        const k = 1024;
        const sizes = ['Bytes', 'KB', 'MB'];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
      };

      return {
        id: uploadId,
        name: file.name,
        size: formatSize(file.size),
        progress: 0,
        status: 'Uploading',
      };
    });

    setUploads((prev) => [...newUploads, ...prev]);
  };

  const handleFileChange = (e) => {
    if (e.target.files && e.target.files.length > 0) {
      handleFiles(e.target.files);
    }
  };

  // Drag and drop handlers
  const handleDrag = (e) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.type === 'dragenter' || e.type === 'dragover') {
      setDragActive(true);
    } else if (e.type === 'dragleave') {
      setDragActive(false);
    }
  };

  const handleDrop = (e) => {
    e.preventDefault();
    e.stopPropagation();
    setDragActive(false);
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      handleFiles(e.dataTransfer.files);
    }
  };

  return (
    <div className="du-page">
      <div className="du-content">
        {/* Page Header */}
        <div className="du-page-header">
          <h2 className="du-page-title">Data Upload</h2>
          <p className="du-page-subtitle">
            Upload sales, inventory, and bad order files to feed the SSM engine. Supported formats: Excel (.xlsx, .xls) and CSV (.csv). Clean, consistent data improves forecast accuracy and optimization results.
          </p>
        </div>

        {/* Accepted Formats */}
        <div className="du-formats-section">
          <span className="du-section-label">Accepted Formats</span>
          <div className="du-badges-row">
            <span className="du-badge">.xlsx</span>
            <span className="du-badge">.xls</span>
            <span className="du-badge">.csv</span>
          </div>
        </div>

        {/* Target Files Cards */}
        <div className="du-cards-grid">
          <div className="du-file-card">
            <div className="du-card-header">
              <span className="du-blue-dot"></span>
              <span className="du-card-label">File 01</span>
            </div>
            <h3 className="du-card-title">Sales Data</h3>
            <p className="du-card-desc">Daily or monthly transactions</p>
          </div>

          <div className="du-file-card">
            <div className="du-card-header">
              <span className="du-blue-dot"></span>
              <span className="du-card-label">File 02</span>
            </div>
            <h3 className="du-card-title">Inventory Log</h3>
            <p className="du-card-desc">Stock-in and stock-out records</p>
          </div>

          <div className="du-file-card">
            <div className="du-card-header">
              <span className="du-blue-dot"></span>
              <span className="du-card-label">File 03</span>
            </div>
            <h3 className="du-card-title">Bad Order Log</h3>
            <p className="du-card-desc">Damaged or expired stock</p>
          </div>
        </div>

        {/* File Dropzone Area */}
        <div 
          className={`du-dropzone ${dragActive ? 'drag-active' : ''}`}
          onDragEnter={handleDrag}
          onDragOver={handleDrag}
          onDragLeave={handleDrag}
          onDrop={handleDrop}
          onClick={onButtonClick}
        >
          <input
            ref={fileInputRef}
            type="file"
            multiple
            accept=".xlsx,.xls,.csv"
            onChange={handleFileChange}
            style={{ display: 'none' }}
          />
          <div className="du-icon-wrapper">
            <Upload size={24} />
          </div>
          <h4 className="du-dropzone-text">Drop files, or click to browse</h4>
          <p className="du-dropzone-subtext">Supported formats: .xlsx, .xls, .csv</p>
          <button type="button" className="du-select-btn" onClick={(e) => { e.stopPropagation(); onButtonClick(); }}>
            Select Files
          </button>
        </div>

        {/* Upload Status list */}
        {uploads.length > 0 && (
          <div className="du-upload-section">
            <span className="du-section-label">Uploaded Files</span>
            <div className="du-upload-list">
              {uploads.map((file) => (
                <div className="du-upload-item" key={file.id}>
                  <div className="du-item-left">
                    {file.status === 'Completed' ? (
                      <CheckCircle className="du-item-icon" style={{ color: '#38a169' }} size={20} />
                    ) : (
                      <FileText className="du-item-icon" size={20} />
                    )}
                    <div className="du-item-details">
                      <span className="du-item-name">{file.name}</span>
                      <span className="du-item-size">{file.size}</span>
                    </div>
                  </div>
                  <div className="du-item-progress-container">
                    {file.status === 'Uploading' ? (
                      <>
                        <div className="du-progress-bar">
                          <div className="du-progress-fill" style={{ width: `${file.progress}%` }}></div>
                        </div>
                        <span className="du-item-status status-loading">{file.progress}%</span>
                      </>
                    ) : (
                      <span className="du-item-status">{file.status}</span>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

export default DataUpload;
