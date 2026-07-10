import React from 'react';
import { createRoot } from 'react-dom/client';
import { RouterProvider } from 'react-router-dom';
import { ThemeProvider } from './hooks/useTheme';
import { readyI18n } from './i18n';
import { router } from './routes';
import './styles/global.css';

readyI18n().then(() => {
  const root = document.getElementById('app');
  if (root) {
    createRoot(root).render(
      <React.StrictMode>
        <ThemeProvider>
          <RouterProvider router={router} />
        </ThemeProvider>
      </React.StrictMode>
    );
  }
});
