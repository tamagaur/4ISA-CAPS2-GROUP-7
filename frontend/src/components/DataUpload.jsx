import React, { useEffect, useState } from 'react';
import { Database } from 'lucide-react';
import PageHeader from './ui/PageHeader';
import EmptyState from './ui/EmptyState';
import MonthlyBatchPanel from './MonthlyBatchPanel';
import { getBatchAvailable } from '../api/monthlyBatch';
import './DataUpload.css';

// Data Management is Monthly Data Processing (backend/routers/monthly_batch.py): the one way a month's sales get into the system. Until the server
// answers, nothing is drawn; if it has no database to process, the page says so.
const DataUpload = () => {
  const [batch, setBatch] = useState(undefined);

  useEffect(() => {
    let current = true;
    getBatchAvailable().then((status) => { if (current) setBatch(status); });
    return () => { current = false; };
  }, []);

  return (
    <div className="du-page">
      <div className="du-content">
        <PageHeader
          className="du-header"
          icon={<Database size={24} />}
          title="Data"
          accent="management"
          subtitle="Load a month of sales, check it, and update the forecast and the order plan."
        />
        {batch && <MonthlyBatchPanel initialStatus={batch} />}
        {batch === null && (
          <EmptyState icon={Database} title="Monthly processing is not available">
            This server is not connected to a database it can process a month on. Ask an admin.
          </EmptyState>
        )}
      </div>
    </div>
  );
};

export default DataUpload;
