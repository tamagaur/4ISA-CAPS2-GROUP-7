import React, { useState } from 'react';
import { Outlet } from 'react-router-dom';
import Sidebar from './Sidebar';
import Topbar from './Topbar';
import './DashboardLayout.css';

const DashboardLayout = () => {
  const [isSidebarOpen, setIsSidebarOpen] = useState(true);
  const [selectedMonth, setSelectedMonth] = useState('Apr');
  const [selectedYear, setSelectedYear] = useState('2026');

  const toggleSidebar = () => {
    setIsSidebarOpen(!isSidebarOpen);
  };

  return (
    <div className={`dashboard-layout ${isSidebarOpen ? '' : 'sidebar-closed'}`}>
      <Sidebar isOpen={isSidebarOpen} />
      <div className="main-content">
        <Topbar 
          toggleSidebar={toggleSidebar} 
          selectedMonth={selectedMonth} 
          setSelectedMonth={setSelectedMonth}
          selectedYear={selectedYear} 
          setSelectedYear={setSelectedYear}
        />
        <Outlet context={{ selectedMonth, selectedYear }} />
      </div>
    </div>
  );
};

export default DashboardLayout;
