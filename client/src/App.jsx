import { useEffect } from 'react';
import { Routes, Route, Navigate } from 'react-router-dom';
import Layout from './components/Layout.jsx';
import Catalog from './pages/Catalog.jsx';
import ProductDetail from './pages/ProductDetail.jsx';
import ProtectedRoute from './components/ProtectedRoute.jsx';
import Login from './pages/admin/Login.jsx';
import AdminLayout from './pages/admin/AdminLayout.jsx';
import Dashboard from './pages/admin/Dashboard.jsx';
import ProductsList from './pages/admin/ProductsList.jsx';
import ProductForm from './pages/admin/ProductForm.jsx';
import PlatformsList from './pages/admin/PlatformsList.jsx';
import BadgesList from './pages/admin/BadgesList.jsx';
import CategoriesList from './pages/admin/CategoriesList.jsx';
import Settings from './pages/admin/Settings.jsx';
import Users from './pages/admin/Users.jsx';
import SocialLinks from './pages/admin/SocialLinks.jsx';
import Analytics from './pages/admin/Analytics.jsx';
import { useSite } from './context/SiteContext.jsx';

export default function App() {
  const { settings } = useSite();
  const logoUrl = settings?.site_logo_url;

  useEffect(() => {
    if (!logoUrl) return;
    let link = document.querySelector("link[rel~='icon']");
    if (!link) {
      link = document.createElement('link');
      link.rel = 'icon';
      document.head.appendChild(link);
    }
    link.href = logoUrl;
  }, [logoUrl]);

  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Catalog />} />
        <Route path="product/:id" element={<ProductDetail />} />
      </Route>

      <Route path="admin/login" element={<Login />} />

      <Route
        path="admin"
        element={
          <ProtectedRoute>
            <AdminLayout />
          </ProtectedRoute>
        }
      >
        <Route index element={<Dashboard />} />
        <Route path="analytics" element={<Analytics />} />
        <Route path="products" element={<ProductsList />} />
        <Route path="products/new" element={<ProductForm />} />
        <Route path="products/:id/edit" element={<ProductForm />} />
        <Route path="badges" element={<BadgesList />} />
        <Route path="categories" element={<CategoriesList />} />
        <Route path="platforms" element={<PlatformsList />} />
        <Route path="social-links" element={<SocialLinks />} />
        <Route path="settings" element={<Settings />} />
        <Route path="users" element={<Users />} />
      </Route>

      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
