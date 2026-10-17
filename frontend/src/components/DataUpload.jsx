import React, { useState, useRef } from 'react';
import SectionLede from './ui/SectionLede';
import { Upload, FileText, AlertTriangle } from 'lucide-react';
import PageHeader from './ui/PageHeader';
import './DataUpload.css';

const DataUpload = () => {
  const [uploads, setUploads] = useState([]);
  const [dragActive, setDragActive] = useState(false);
  const fileInputRef = useRef(null);

  // Trigger file dialog
  const onButtonClick = () => {
    fileInputRef.current.click();
  };

  // Convert bytes to human readable size
  const formatSize = (bytes) => {
    if (bytes === 0) return '0 Bytes';
    const k = 1024;
    const sizes = ['Bytes', 'KB', 'MB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
  };

  // Records the files the user picked. It does NOT upload them: there is no
  // ingestion endpoint on the backend yet (no route in backend/routers/, no
  // UploadFile handler anywhere), so nothing can receive them.
  //
  // This used to run a setInterval that ticked a fake progress bar to 100%,
  // marked the file "Completed" and wrote an audit-log entry reading
  // "Uploaded file: <name>" — none of which had happened. That combination
  // was actively harmful: a user would believe their master data was
  // ingested, and the audit trail would corroborate it. Until the endpoint
  // exists, files are listed as staged and the banner in the page body says
  // plainly that ingestion isn't connected.
  const handleFiles = (selectedFiles) => {
    const newUploads = Array.from(selectedFiles).map((file, index) => ({
      id: Date.now() + '-' + index,
      name: file.name,
      size: formatSize(file.size),
      progress: 0,
      status: 'Staged',
    }));

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
        <PageHeader
          title="Data"
          accent="management"
          subtitle="The sales and stock files the system runs on. Excel (.xlsx, .xls) and CSV (.csv)."
        />

        {/* Honest status. There is no ingestion endpoint on the backend yet,
            so this page cannot actually send a file anywhere — saying so
            plainly is the only correct behavior until one exists. */}
        <p className="ui-note is-warning" role="note">
          <AlertTriangle size={16} aria-hidden="true" />
          <span>
            <strong>Ingestion is not connected yet.</strong> You can select files here to check
            names and sizes, but nothing is sent to the server and no data is imported. Loading
            data into Supabase currently runs through the ETL scripts.
          </span>
        </p>

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
        <SectionLede className="is-standalone">Where the data comes from</SectionLede>
        <div className="du-cards-grid">
          <div className="du-file-card">
            <div className="du-card-header">
              <span className="du-blue-dot"></span>
              <span className="du-card-label">File 01</span>
            </div>
            <h3 className="du-card-title">Sales Data</h3>
            <p className="du-card-desc">Daily or monthly transactions</p>
            <span className="badge badge-neutral">Loaded through the ETL scripts</span>
          </div>

          <div className="du-file-card">
            <div className="du-card-header">
              <span className="du-blue-dot"></span>
              <span className="du-card-label">File 02</span>
            </div>
            <h3 className="du-card-title">Inventory Log</h3>
            <p className="du-card-desc">Stock-in and stock-out records</p>
            <span className="badge badge-neutral">Loaded through the ETL scripts</span>
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
          <button type="button" className="btn btn-secondary" onClick={(e) => { e.stopPropagation(); onButtonClick(); }}>
            Select files
          </button>
        </div>

        {/* Upload Status list */}
        {uploads.length > 0 && (
          <div className="du-upload-section">
            <span className="du-section-label">Staged Files</span>
            <SectionLede className="is-standalone">What's ready to load</SectionLede>
            <div className="du-upload-list">
              {uploads.map((file) => (
                <div className="du-upload-item" key={file.id}>
                  <div className="du-item-left">
                    <FileText className="du-item-icon" size={20} />
                    <div className="du-item-details">
                      <span className="du-item-name">{file.name}</span>
                      <span className="du-item-size">{file.size}</span>
                    </div>
                  </div>
                  <div className="du-item-progress-container">
                    <span className="du-item-status du-status-staged" title="Selected in the browser only — not sent to the server">
                      Not uploaded
                    </span>
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
