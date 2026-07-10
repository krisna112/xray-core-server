import { createHashRouter } from 'react-router-dom';
import PanelLayout from './layouts/PanelLayout';
import IndexPage from './pages/index/IndexPage';
import InboundsPage from './pages/inbounds/InboundsPage';
import ClientsPage from './pages/clients/ClientsPage';
import SettingsPage from './pages/settings/SettingsPage';
import LoginPage from './pages/login/LoginPage';

export const router = createHashRouter([
  {
    path: '/login',
    element: <LoginPage />,
  },
  {
    path: '/',
    element: <PanelLayout />,
    children: [
      { index: true, element: <IndexPage /> },
      { path: 'inbounds', element: <InboundsPage /> },
      { path: 'clients', element: <ClientsPage /> },
      { path: 'settings', element: <SettingsPage /> },
    ],
  },
]);
