import {
  BookOpen,
  ChartLine,
  ClipboardList,
  Database,
  Layers,
  LayoutDashboard,
  Package,
  RotateCcw,
  TrendingUp,
  Users,
} from 'lucide-react';
import { permissionForPath } from './permissions/keys.js';

export const navSections = [
  {
    label: null,
    items: [
      { name: 'Dashboard', icon: LayoutDashboard, path: '/' },
    ],
  },
  {
    label: 'Inventory Operations',
    items: [
      { name: 'Reorder Recommendations', icon: RotateCcw, path: '/reorder' },
      { name: 'SKU Management', icon: Package, path: '/sku-management' },
      { name: 'ABC Classification', icon: Layers, path: '/abc' },
    ],
  },
  {
    label: 'Analytics & Forecasting',
    items: [
      { name: 'SKU Forecast', icon: TrendingUp, path: '/forecast' },
      { name: 'Category Trends', icon: ChartLine, path: '/category-trends' },
    ],
  },
  {
    label: 'Data & Governance',
    items: [
      { name: 'Reference Guide', icon: BookOpen, path: '/data-dictionary' },
      { name: 'Audit Log', icon: ClipboardList, path: '/audit-log' },
    ],
  },
  {
    label: 'Administration',
    items: [
      { name: 'Data Management', icon: Database, path: '/upload' },
      { name: 'User Management', icon: Users, path: '/users' },
    ],
  },
];

export function nextNavItem(path, canOpen) {
  const items = navSections.flatMap((section) => section.items);
  const currentIndex = items.findIndex((item) => item.path === path);
  if (currentIndex < 0) return null;
  return items.slice(currentIndex + 1)
    .find((item) => canOpen(permissionForPath(item.path))) || null;
}
