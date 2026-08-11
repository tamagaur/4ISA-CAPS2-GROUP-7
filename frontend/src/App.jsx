import React, { useEffect } from 'react';
import { Routes, Route, useLocation } from 'react-router-dom';
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

const routeTitles = {
  '/login': 'SAN2 | Login',
  '/': 'SAN2 | Dashboard',
  '/sku-management': 'SAN2 | SKU Management',
  '/abc': 'SAN2 | ABC Classification',
  '/forecast': 'SAN2 | SKU Forecast',
  '/reorder': 'SAN2 | Reorder Recommendations',
  '/warehouse': 'SAN2 | Warehouse Movement',
  '/bad-orders': 'SAN2 | Bad Orders',
  '/upload': 'SAN2 | Data Upload',
};

function DynamicTitle() {
  const location = useLocation();

  useEffect(() => {
    document.title = routeTitles[location.pathname] || 'SAN2 | Inventory DSS';
  }, [location]);

  return null;
}

function App() {
  return (
    <div className="App">
      <DynamicTitle />
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
