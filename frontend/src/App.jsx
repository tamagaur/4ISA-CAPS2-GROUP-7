import React from 'react';
import { Routes, Route } from 'react-router-dom';
import Login from './Login';
import DashboardLayout from './components/DashboardLayout';
import Dashboard from './components/Dashboard';
import SKUManagement from './components/SKUManagement';
import './App.css';

function App() {
  return (
    <div className="App">
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/" element={<DashboardLayout />}>
          <Route index element={<Dashboard />} />
          <Route path="sku-management" element={<SKUManagement />} />
        </Route>
      </Routes>
    </div>
  );
}

export default App;
