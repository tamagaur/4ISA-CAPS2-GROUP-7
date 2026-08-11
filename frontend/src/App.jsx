import React from 'react';
import { Routes, Route } from 'react-router-dom';
import Login from './Login';
import DashboardLayout from './components/DashboardLayout';
import Dashboard from './components/Dashboard';
import SKUManagement from './components/SKUManagement';
import ABCClassification from './components/ABCClassification';
import SKUForecast from './components/SKUForecast';
import ReorderRecommendations from './components/ReorderRecommendations';
import WarehouseMovement from './components/WarehouseMovement';
import BadOrders from './components/BadOrders';
import DataUpload from './components/DataUpload';
import './App.css';

function App() {
  return (
    <div className="App">
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/" element={<DashboardLayout />}>
          <Route index element={<Dashboard />} />
          <Route path="sku-management" element={<SKUManagement />} />
          <Route path="abc" element={<ABCClassification />} />
          <Route path="forecast" element={<SKUForecast />} />
          <Route path="reorder" element={<ReorderRecommendations />} />
          <Route path="warehouse" element={<WarehouseMovement />} />
          <Route path="bad-orders" element={<BadOrders />} />
          <Route path="upload" element={<DataUpload />} />
        </Route>
      </Routes>
    </div>
  );
}

export default App;
