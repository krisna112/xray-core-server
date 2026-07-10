import { useState } from 'react';
import { Layout, Menu, Button, Drawer } from 'antd';
import { useNavigate, useLocation } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import {
  DashboardOutlined,
  DownloadOutlined,
  UserOutlined,
  SettingOutlined,
  LogoutOutlined,
  MenuOutlined,
  BulbOutlined,
  BulbFilled
} from '@ant-design/icons';
import { useTheme } from '../hooks/useTheme';
import { request } from '../api/http';

const { Sider } = Layout;

export default function AppSidebar() {
  const { themeName, toggleTheme } = useTheme();
  const { t } = useTranslation();
  const navigate = useNavigate();
  const location = useLocation();
  const [mobileOpen, setMobileOpen] = useState(false);

  const menuItems = [
    {
      key: '/',
      icon: <DashboardOutlined />,
      label: t('menu.dashboard', 'Dashboard'),
    },
    {
      key: '/inbounds',
      icon: <DownloadOutlined />,
      label: t('menu.inbounds', 'Inbounds'),
    },
    {
      key: '/clients',
      icon: <UserOutlined />,
      label: t('menu.clients', 'Clients'),
    },
    {
      key: '/settings',
      icon: <SettingOutlined />,
      label: t('menu.settings', 'Settings'),
    },
  ];

  const handleLogout = async () => {
    await request('/logout');
    window.location.reload();
  };

  const getSelectedKey = () => {
    const path = location.pathname;
    if (path === '/') return '/';
    if (path.startsWith('/inbounds')) return '/inbounds';
    if (path.startsWith('/clients')) return '/clients';
    if (path.startsWith('/settings')) return '/settings';
    return '/';
  };

  const sidebarContent = (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      <div style={{ height: 64, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '0 16px', borderBottom: '1px solid var(--ant-color-border-secondary)' }}>
        <h2 style={{ margin: 0, fontSize: 18, color: 'var(--ant-color-primary)', fontWeight: 800 }}>OceanShark</h2>
      </div>
      <Menu
        theme={themeName}
        mode="inline"
        selectedKeys={[getSelectedKey()]}
        onClick={({ key }) => {
          navigate(key);
          setMobileOpen(false);
        }}
        items={menuItems}
        style={{ flex: 1, borderRight: 0, paddingTop: 16 }}
      />
      <div style={{ padding: 16, borderTop: '1px solid var(--ant-color-border-secondary)', display: 'flex', flexDirection: 'column', gap: 10 }}>
        <Button
          block
          icon={themeName === 'dark' ? <BulbFilled /> : <BulbOutlined />}
          onClick={toggleTheme}
        >
          {themeName === 'dark' ? 'Light Mode' : 'Dark Mode'}
        </Button>
        <Button block danger icon={<LogoutOutlined />} onClick={handleLogout}>
          Keluar
        </Button>
      </div>
    </div>
  );

  return (
    <>
      {/* Mobile Toggle Button */}
      <Button
        className="mobile-toggle-btn"
        icon={<MenuOutlined />}
        onClick={() => setMobileOpen(true)}
        style={{
          position: 'fixed',
          top: 16,
          left: 16,
          zIndex: 99,
          display: 'none', // Override in CSS Media Query
        }}
      />

      {/* Desktop Sidebar */}
      <Sider
        theme={themeName}
        breakpoint="lg"
        collapsedWidth="0"
        onBreakpoint={(broken) => {
          const btn = document.querySelector('.mobile-toggle-btn') as HTMLElement;
          if (btn) btn.style.display = broken ? 'block' : 'none';
        }}
        style={{
          height: '100vh',
          position: 'fixed',
          left: 0,
          top: 0,
          bottom: 0,
          zIndex: 90,
          borderRight: '1px solid var(--ant-color-border-secondary)',
        }}
      >
        {sidebarContent}
      </Sider>

      {/* Mobile Drawer */}
      <Drawer
        placement="left"
        closable={false}
        onClose={() => setMobileOpen(false)}
        open={mobileOpen}
        bodyStyle={{ padding: 0 }}
        width={240}
      >
        {sidebarContent}
      </Drawer>
    </>
  );
}
