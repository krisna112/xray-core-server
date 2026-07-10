import { useState, useEffect } from 'react';
import { Row, Col, Card, Statistic, Progress, Table, Tag, Button, Typography, Space, message } from 'antd';
import {
  SafetyOutlined,
  WarningOutlined,
  DownloadOutlined,
  ClockCircleOutlined,
  ReloadOutlined
} from '@ant-design/icons';
import { request } from '../../api/http';

const { Title, Text } = Typography;

interface ServerStatus {
  cpu: number;
  mem: { current: number; total: number };
  uptime: number;
  xray: { state: string; version: string };
  appVersion: string;
}

interface Client {
  email: string;
  enable: boolean;
  totalGB: number;
  expiryTime: number;
  traffic: { up: number; down: number; usage: number; total: number };
}

export default function IndexPage() {
  const [status, setStatus] = useState<ServerStatus | null>(null);
  const [clients, setClients] = useState<Client[]>([]);
  const [loading, setLoading] = useState(true);
  const [applying, setApplying] = useState(false);

  const fetchData = async () => {
    try {
      const [statusRes, clientsRes] = await Promise.all([
        request('/panel/api/server/status'),
        request('/panel/api/clients/list'),
      ]);

      if (statusRes.success) setStatus(statusRes.obj);
      if (clientsRes.success) setClients(clientsRes.obj || []);
    } catch (err) {
      console.error('Failed to fetch dashboard data:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 5000);
    return () => clearInterval(interval);
  }, []);

  const handleApply = async () => {
    setApplying(true);
    try {
      const res = await request('/panel/api/apply', { method: 'POST' });
      if (res.success) {
        message.success(res.msg || 'Konfigurasi berhasil diterapkan & Xray direstart');
        fetchData();
      } else {
        message.error(res.msg || 'Gagal menerapkan konfigurasi');
      }
    } catch (err: any) {
      message.error(err.message || 'Koneksi gagal');
    } finally {
      setApplying(false);
    }
  };

  const formatBytes = (bytes: number) => {
    if (!bytes) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
  };

  const getDaysLeft = (expiryTime: number) => {
    if (!expiryTime) return { text: '∞', color: 'blue' };
    if (expiryTime < 0) return { text: 'Belum Aktif', color: 'orange' };
    const left = expiryTime - Date.now();
    const days = Math.ceil(left / (1000 * 60 * 60 * 24));
    if (days <= 0) return { text: 'Expired', color: 'red' };
    if (days <= 3) return { text: `${days} hari`, color: 'volcano' };
    return { text: `${days} hari`, color: 'green' };
  };

  // Filter clients expiring within 7 days
  const soonExpiring = clients
    .map(c => {
      const left = c.expiryTime > 0 ? c.expiryTime - Date.now() : Infinity;
      const days = Math.ceil(left / (1000 * 60 * 60 * 24));
      return { ...c, daysLeft: days };
    })
    .filter(c => c.expiryTime < 0 || (c.expiryTime > 0 && c.daysLeft <= 7))
    .sort((a, b) => a.daysLeft - b.daysLeft)
    .slice(0, 8);

  const columns = [
    {
      title: 'Email',
      dataIndex: 'email',
      key: 'email',
      render: (text: string) => <strong>{text}</strong>,
    },
    {
      title: 'Sisa Waktu',
      dataIndex: 'expiryTime',
      key: 'expiryTime',
      render: (time: number) => {
        const res = getDaysLeft(time);
        return <Tag color={res.color}>{res.text}</Tag>;
      },
    },
    {
      title: 'Kuota',
      key: 'traffic',
      render: (_: any, record: Client) => {
        const usage = record.traffic.usage || 0;
        const total = record.totalGB || 0;
        return <span>{formatBytes(usage)} / {total ? formatBytes(total) : '∞'}</span>;
      },
    },
    {
      title: 'Status',
      dataIndex: 'enable',
      key: 'enable',
      render: (enable: boolean) => (
        <Tag color={enable ? 'success' : 'error'}>
          {enable ? 'Aktif' : 'Nonaktif'}
        </Tag>
      ),
    },
  ];

  const memPct = status?.mem?.total ? Math.round((status.mem.current / status.mem.total) * 100) : 0;
  const cpuPct = status?.cpu ? Math.min(100, Math.round(status.cpu * 100)) : 0;
  const uptimeDays = status?.uptime ? (status.uptime / 86400).toFixed(1) : '—';

  return (
    <Space direction="vertical" size="large" style={{ width: '100%' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 16 }}>
        <div>
          <Title level={2} style={{ margin: 0, fontWeight: 800 }}>Dashboard</Title>
          <Text type="secondary">Monitor server dan status Xray-core</Text>
        </div>
        <Button
          type="primary"
          icon={<ReloadOutlined />}
          loading={applying}
          onClick={handleApply}
          style={{ fontWeight: 700 }}
        >
          Terapkan & Restart Xray
        </Button>
      </div>

      {/* Stats Grid */}
      <Row gutter={[16, 16]}>
        <Col xs={24} sm={12} lg={6}>
          <Card style={{ borderRadius: 12 }}>
            <Statistic
              title="Status Xray"
              value={status?.xray?.state === 'running' ? 'Aktif' : 'Mati'}
              prefix={status?.xray?.state === 'running' ? <SafetyOutlined style={{ color: 'var(--ant-color-success)' }} /> : <WarningOutlined style={{ color: 'var(--ant-color-error)' }} />}
              valueStyle={{ color: status?.xray?.state === 'running' ? 'var(--ant-color-success)' : 'var(--ant-color-error)', fontWeight: 800 }}
            />
            <div style={{ marginTop: 8, fontSize: 12, color: 'var(--ant-color-text-secondary)' }}>
              xray-core {status?.xray?.version || '—'}
            </div>
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card>
            <Statistic
              title="Total Inbound"
              value={clients.length > 0 ? Array.from(new Set(clients.map(c => c.email))).length : 0} // Approximate placeholder or display client totals
              prefix={<DownloadOutlined />}
              valueStyle={{ fontWeight: 800 }}
            />
            <div style={{ marginTop: 8, fontSize: 12, color: 'var(--ant-color-text-secondary)' }}>
              Total client terdaftar
            </div>
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card>
            <Text type="secondary" style={{ fontSize: 14 }}>RAM Usage ({memPct}%)</Text>
            <div style={{ margin: '8px 0' }}>
              <Progress percent={memPct} strokeColor="var(--ant-color-primary)" showInfo={false} />
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, color: 'var(--ant-color-text-secondary)' }}>
              <span>{formatBytes(status?.mem?.current || 0)}</span>
              <span>{formatBytes(status?.mem?.total || 0)}</span>
            </div>
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card>
            <Text type="secondary" style={{ fontSize: 14 }}>CPU Load ({cpuPct}%)</Text>
            <div style={{ margin: '8px 0' }}>
              <Progress percent={cpuPct} strokeColor="var(--ant-color-primary)" showInfo={false} />
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, color: 'var(--ant-color-text-secondary)' }}>
              <span>Uptime: {uptimeDays} hari</span>
            </div>
          </Card>
        </Col>
      </Row>

      {/* Expiring Clients */}
      <Card title={<Space><ClockCircleOutlined /><span>Client Segera Berakhir</span></Space>} style={{ borderRadius: 12 }}>
        <Table
          columns={columns}
          dataSource={soonExpiring}
          rowKey="email"
          pagination={false}
          loading={loading}
          locale={{ emptyText: 'Tidak ada client yang akan berakhir dalam 7 hari.' }}
        />
      </Card>
    </Space>
  );
}
