import React from 'react';
import { createRoot } from 'react-dom/client';
import { ThemeProvider } from '../hooks/useTheme';
import { readyI18n } from '../i18n';
import LoginPage from '../pages/login/LoginPage';
import '../styles/global.css';

readyI18n().then(() => {
  const root = document.getElementById('app');
  if (root) {
    createRoot(root).render(
      <React.StrictMode>
        <ThemeProvider>
          <LoginPage />
        </ThemeProvider>
      </React.StrictMode>
    );
  }
});
