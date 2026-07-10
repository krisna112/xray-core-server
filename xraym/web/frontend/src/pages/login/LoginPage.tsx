import { useState } from 'react';
import { Card, Form, Input, Button, Select, Typography, Alert, Layout } from 'antd';
import { UserOutlined, LockOutlined, GlobalOutlined } from '@ant-design/icons';
import { useTranslation } from 'react-i18next';
import { request, getUrl } from '../../api/http';
import { SUPPORTED_LANGUAGES } from '../../i18n';

const { Title } = Typography;

export default function LoginPage() {
  const { t, i18n } = useTranslation();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [shake, setShake] = useState(false);

  const onFinish = async (values: any) => {
    setLoading(true);
    setError(null);
    try {
      const res = await request('/login', {
        method: 'POST',
        body: values,
      });

      if (res.success) {
        // Redirect to main panel index
        window.location.href = getUrl('/');
      } else {
        setError(res.msg || 'Login gagal');
        setShake(true);
        setTimeout(() => setShake(false), 500);
      }
    } catch (err: any) {
      setError(err?.message || 'Koneksi gagal');
    } finally {
      setLoading(false);
    }
  };

  const handleLangChange = (code: string) => {
    localStorage.setItem('lang', code);
    i18n.changeLanguage(code);
  };

  return (
    <Layout style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'var(--ant-color-bg-container-secondary)' }}>
      <div style={{ position: 'absolute', top: 16, right: 16 }}>
        <Select
          defaultValue={i18n.language}
          style={{ width: 180 }}
          onChange={handleLangChange}
          options={SUPPORTED_LANGUAGES.map(lang => ({ value: lang.code, label: lang.label }))}
          suffixIcon={<GlobalOutlined />}
        />
      </div>

      <Card
        className={shake ? 'shake' : ''}
        style={{
          width: '100%',
          maxWidth: 400,
          borderRadius: 16,
          boxShadow: '0 8px 24px rgba(0,0,0,0.12)',
        }}
      >
        <div style={{ textAlign: 'center', marginBottom: 24 }}>
          <Title level={2} style={{ margin: 0, fontWeight: 800, color: 'var(--ant-color-primary)' }}>
            OceanShark
          </Title>
          <Typography.Text type="secondary">Xray Core Manager</Typography.Text>
        </div>

        {error && (
          <Alert
            message={error}
            type="error"
            showIcon
            style={{ marginBottom: 16 }}
            closable
            onClose={() => setError(null)}
          />
        )}

        <Form name="login" onFinish={onFinish} layout="vertical" size="large">
          <Form.Item
            name="username"
            rules={[{ required: true, message: t('login.username_required', 'Username tidak boleh kosong') }]}
          >
            <Input prefix={<UserOutlined style={{ color: 'var(--ant-color-text-description)' }} />} placeholder={t('login.username', 'Username')} />
          </Form.Item>

          <Form.Item
            name="password"
            rules={[{ required: true, message: t('login.password_required', 'Password tidak boleh kosong') }]}
          >
            <Input.Password prefix={<LockOutlined style={{ color: 'var(--ant-color-text-description)' }} />} placeholder={t('login.password', 'Password')} />
          </Form.Item>

          <Form.Item>
            <Button type="primary" htmlType="submit" block loading={loading} style={{ fontWeight: 700 }}>
              {t('login.login', 'Masuk')}
            </Button>
          </Form.Item>
        </Form>
      </Card>
    </Layout>
  );
}
