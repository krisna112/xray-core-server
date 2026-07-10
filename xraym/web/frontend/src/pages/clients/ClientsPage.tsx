import { useState, useEffect } from 'react';
import {
  Table,
  Button,
  Card,
  Tag,
  Space,
  Modal,
  Form,
  Input,
  InputNumber,
  Select,
  DatePicker,
  Popconfirm,
  message,
  Typography,
  Switch,
  Row,
  Col
} from 'antd';
import {
  PlusOutlined,
  EditOutlined,
  DeleteOutlined,
  ReloadOutlined,
  ShareAltOutlined,
  CopyOutlined
} from '@ant-design/icons';
import dayjs from 'dayjs';
import { request } from '../../api/http';

const { Title, Text } = Typography;
const { Option } = Select;

interface Client {
  email: string;
  enable: boolean;
  flow: string;
  limitIp: number;
  totalGB: number; // Bytes despite the name
  expiryTime: number;
  inboundIds: number[];
  online: boolean;
  id: string; // uuid or password
  traffic: { up: number; down: number; usage: number; total: number };
}

interface Inbound {
  id: number;
  remark: string;
  protocol: string;
  port: number;
}

export default function ClientsPage() {
  const [clients, setClients] = useState<Client[]>([]);
  const [inbounds, setInbounds] = useState<Inbound[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [modalOpen, setModalOpen] = useState(false);
  const [editingClient, setEditingClient] = useState<Client | null>(null);
  const [shareModalOpen, setShareModalOpen] = useState(false);
  const [shareLink, setShareLink] = useState('');
  const [shareQr, setShareQr] = useState('');
  const [form] = Form.useForm();
  const [expiryType, setExpiryType] = useState<'none' | 'date' | 'countdown'>('none');

  const fetchData = async () => {
    setLoading(true);
    try {
      const [clientsRes, inboundsRes] = await Promise.all([
        request('/panel/api/clients/list'),
        request('/panel/api/inbounds/list'),
      ]);

      if (clientsRes.success) setClients(clientsRes.obj || []);
      if (inboundsRes.success) setInbounds(inboundsRes.obj || []);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
  }, []);

  const handleOpenAdd = () => {
    setEditingClient(null);
    setExpiryType('none');
    form.resetFields();
    form.setFieldsValue({
      enable: true,
      limitIp: 0,
      totalGB: 0,
    });
    setModalOpen(true);
  };

  const handleOpenEdit = (client: Client) => {
    setEditingClient(client);
    form.resetFields();

    let initialExpiryType: 'none' | 'date' | 'countdown' = 'none';
    let countdownDays = 30;
    let specificDate = null;

    if (client.expiryTime > 0) {
      initialExpiryType = 'date';
      specificDate = dayjs(client.expiryTime);
    } else if (client.expiryTime < 0) {
      initialExpiryType = 'countdown';
      countdownDays = Math.round(Math.abs(client.expiryTime) / (1000 * 60 * 60 * 24));
    }

    setExpiryType(initialExpiryType);

    form.setFieldsValue({
      email: client.email,
      id: client.id,
      flow: client.flow,
      limitIp: client.limitIp,
      totalGB: client.totalGB ? Math.round(client.totalGB / (1024 * 1024 * 1024)) : 0, // GB conversion
      enable: client.enable,
      inboundId: client.inboundIds?.[0],
      expiryType: initialExpiryType,
      countdownDays,
      specificDate,
    });
    setModalOpen(true);
  };

  const handleSave = async () => {
    try {
      const values = await form.validateFields();
      const isEdit = !!editingClient;

      // Compute expiryTime
      let expiryTime = 0;
      if (values.expiryType === 'date' && values.specificDate) {
        expiryTime = values.specificDate.valueOf();
      } else if (values.expiryType === 'countdown' && values.countdownDays) {
        expiryTime = -1 * values.countdownDays * 24 * 60 * 60 * 1000; // Negative ms
      }

      const clientData = {
        email: values.email,
        id: values.id || '', // Auto-generate if blank
        flow: values.flow || '',
        limitIp: values.limitIp || 0,
        totalGB: values.totalGB ? values.totalGB * 1024 * 1024 * 1024 : 0, // GB to Bytes
        expiryTime,
        enable: values.enable,
      };

      const payload = isEdit
        ? clientData
        : {
            client: clientData,
            inboundIds: values.inboundId ? [values.inboundId] : [],
          };

      const url = isEdit
        ? `/panel/api/clients/update/${editingClient.email}`
        : '/panel/api/clients/add';

      const res = await request(url, {
        method: 'POST',
        body: payload as any,
      });

      if (res.success) {
        message.success(isEdit ? 'Client diperbarui' : 'Client dibuat');
        setModalOpen(false);
        fetchData();
      } else {
        message.error(res.msg || 'Gagal menyimpan client');
      }
    } catch (err: any) {
      message.error(err.message || 'Harap periksa isian form');
    }
  };

  const handleDelete = async (email: string) => {
    try {
      const res = await request(`/panel/api/clients/del/${email}`, { method: 'POST' });
      if (res.success) {
        message.success('Client dihapus');
        fetchData();
      } else {
        message.error(res.msg);
      }
    } catch (err: any) {
      message.error(err.message);
    }
  };

  const handleToggle = async (client: Client) => {
    try {
      const res = await request(`/panel/api/clients/update/${client.email}`, {
        method: 'POST',
        body: {
          ...client,
          enable: !client.enable,
        } as any,
      });
      if (res.success) {
        message.success(client.enable ? 'Client dinonaktifkan' : 'Client diaktifkan');
        fetchData();
      } else {
        message.error(res.msg);
      }
    } catch (err: any) {
      message.error(err.message);
    }
  };

  const handleResetTraffic = async (email: string) => {
    try {
      const res = await request(`/panel/api/clients/resetTraffic/${email}`, { method: 'POST' });
      if (res.success) {
        message.success('Trafik client di-reset');
        fetchData();
      } else {
        message.error(res.msg);
      }
    } catch (err: any) {
      message.error(err.message);
    }
  };

  const handleShare = async (email: string) => {
    try {
      const [linkRes, qrRes] = await Promise.all([
        request(`/panel/api/clients/link/${email}`),
        request(`/panel/api/clients/qr/${email}`),
      ]);

      if (linkRes.success && qrRes.success) {
        setShareLink(linkRes.obj);
        setShareQr(qrRes.obj); // Contains SVG raw string
        setShareModalOpen(true);
      } else {
        message.error('Gagal mengambil share link');
      }
    } catch (err: any) {
      message.error(err.message);
    }
  };

  const copyToClipboard = (text: string) => {
    navigator.clipboard.writeText(text);
    message.success('Tautan berhasil disalin ke clipboard!');
  };

  const formatBytes = (bytes: number) => {
    if (!bytes) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
  };

  const getDaysLeft = (expiryTime: number) => {
    if (!expiryTime) return { text: 'Selamanya', color: 'blue' };
    if (expiryTime < 0) {
      const days = Math.round(Math.abs(expiryTime) / (1000 * 60 * 60 * 24));
      return { text: `${days} hari (mulai saat dipakai)`, color: 'orange' };
    }
    const left = expiryTime - Date.now();
    const days = Math.ceil(left / (1000 * 60 * 60 * 24));
    if (days <= 0) return { text: 'Expired', color: 'red' };
    return { text: `${days} hari`, color: 'green' };
  };

  const filteredClients = clients.filter(c =>
    c.email.toLowerCase().includes(search.toLowerCase()) ||
    c.id.toLowerCase().includes(search.toLowerCase())
  );

  const columns = [
    {
      title: 'Email / ID',
      key: 'email',
      render: (_: any, record: Client) => (
        <div>
          <Space>
            <strong>{record.email}</strong>
            {record.online && <Tag color="success">Online</Tag>}
          </Space>
          <div style={{ fontSize: 11, color: 'var(--ant-color-text-secondary)', fontFamily: 'monospace' }}>
            {record.id}
          </div>
        </div>
      ),
    },
    {
      title: 'Inbound',
      dataIndex: 'inboundIds',
      key: 'inbound',
      render: (ids: number[]) => {
        const ib = inbounds.find(i => i.id === ids?.[0]);
        if (!ib) return <Tag>N/A</Tag>;
        return (
          <Space>
            <Tag color="purple">{ib.protocol.toUpperCase()}</Tag>
            <span style={{ fontSize: 12 }}>{ib.remark} ({ib.port})</span>
          </Space>
        );
      },
    },
    {
      title: 'Pemakaian Kuota',
      key: 'traffic',
      render: (_: any, record: Client) => {
        const usage = record.traffic.usage || 0;
        const total = record.totalGB || 0;
        return (
          <div>
            <div>↑ {formatBytes(record.traffic.up)} | ↓ {formatBytes(record.traffic.down)}</div>
            <div style={{ fontSize: 11, color: 'var(--ant-color-text-secondary)' }}>
              Total: {formatBytes(usage)} / {total ? formatBytes(total) : '∞'}
            </div>
          </div>
        );
      },
    },
    {
      title: 'Masa Aktif',
      dataIndex: 'expiryTime',
      key: 'expiryTime',
      render: (time: number) => {
        const res = getDaysLeft(time);
        return <Tag color={res.color}>{res.text}</Tag>;
      },
    },
    {
      title: 'Limit IP',
      dataIndex: 'limitIp',
      key: 'limitIp',
      render: (limit: number) => (limit ? `${limit} IP` : <Tag>∞</Tag>),
    },
    {
      title: 'Aksi',
      key: 'actions',
      render: (_: any, record: Client) => (
        <Space>
          <Switch
            checked={record.enable}
            onChange={() => handleToggle(record)}
            size="small"
          />
          <Button
            type="text"
            icon={<ShareAltOutlined style={{ color: 'var(--ant-color-primary)' }} />}
            onClick={() => handleShare(record.email)}
            title="Bagikan Tautan/QR"
          />
          <Button
            type="text"
            icon={<EditOutlined />}
            onClick={() => handleOpenEdit(record)}
          />
          <Popconfirm
            title="Reset trafik client ini?"
            onConfirm={() => handleResetTraffic(record.email)}
            okText="Ya"
            cancelText="Batal"
          >
            <Button type="text" icon={<ReloadOutlined />} />
          </Popconfirm>
          <Popconfirm
            title="Hapus client ini?"
            onConfirm={() => handleDelete(record.email)}
            okText="Hapus"
            okButtonProps={{ danger: true }}
            cancelText="Batal"
          >
            <Button type="text" danger icon={<DeleteOutlined />} />
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <Space direction="vertical" size="large" style={{ width: '100%' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 16 }}>
        <div>
          <Title level={2} style={{ margin: 0, fontWeight: 800 }}>Clients</Title>
          <Text type="secondary">Kelola client VPN, kuota, limit IP, dan masa aktif</Text>
        </div>
        <Space>
          <Input.Search
            placeholder="Cari email / UUID..."
            allowClear
            onChange={(e) => setSearch(e.target.value)}
            style={{ width: 220 }}
          />
          <Button
            type="primary"
            icon={<PlusOutlined />}
            onClick={handleOpenAdd}
            style={{ fontWeight: 700 }}
          >
            Tambah Client
          </Button>
        </Space>
      </div>

      <Card style={{ borderRadius: 12 }}>
        <Table
          columns={columns}
          dataSource={filteredClients}
          rowKey="email"
          loading={loading}
          pagination={{ pageSize: 10 }}
        />
      </Card>

      {/* Add / Edit Client Modal */}
      <Modal
        title={editingClient ? 'Edit Client' : 'Tambah Client Baru'}
        open={modalOpen}
        onOk={handleSave}
        onCancel={() => setModalOpen(false)}
        width={550}
        destroyOnClose
      >
        <Form form={form} layout="vertical" initialValues={{ expiryType: 'none', countdownDays: 30 }}>
          <Form.Item name="enable" valuePropName="checked" hidden>
            <Switch />
          </Form.Item>

          <Row gutter={16}>
            <Col span={12}>
              <Form.Item
                name="email"
                label="Email / Label Client"
                rules={[{ required: true, message: 'Masukkan email/label client' }]}
              >
                <Input placeholder="Contoh: member_krisna" disabled={!!editingClient} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="inboundId" label="Inbound (Listener)" rules={[{ required: !editingClient, message: 'Pilih Inbound' }]} hidden={!!editingClient}>
                <Select placeholder="Pilih listener">
                  {inbounds.map(ib => (
                    <Option key={ib.id} value={ib.id}>
                      {ib.remark} ({ib.protocol.toUpperCase()} - {ib.port})
                    </Option>
                  ))}
                </Select>
              </Form.Item>
            </Col>
          </Row>

          <Form.Item name="id" label="UUID / Password (Kosongkan untuk acak)">
            <Input placeholder="Contoh: b4a18-d56..." />
          </Form.Item>

          <Row gutter={16}>
            <Col span={12}>
              <Form.Item name="totalGB" label="Batasan Kuota (GB, 0=∞)">
                <InputNumber min={0} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="limitIp" label="Batasan Jumlah IP (0=∞)">
                <InputNumber min={0} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
          </Row>

          <Row gutter={16}>
            <Col span={12}>
              <Form.Item name="expiryType" label="Tipe Masa Aktif">
                <Select onChange={(val) => setExpiryType(val)}>
                  <Option value="none">Selamanya / Tidak Ada</Option>
                  <Option value="date">Tanggal Tertentu</Option>
                  <Option value="countdown">Countdown Saat Pertama Dipakai</Option>
                </Select>
              </Form.Item>
            </Col>
            <Col span={12}>
              {expiryType === 'date' && (
                <Form.Item name="specificDate" label="Pilih Tanggal Berakhir" rules={[{ required: true, message: 'Pilih tanggal' }]}>
                  <DatePicker showTime format="YYYY-MM-DD HH:mm:ss" style={{ width: '100%' }} />
                </Form.Item>
              )}
              {expiryType === 'countdown' && (
                <Form.Item name="countdownDays" label="Jumlah Hari Aktif" rules={[{ required: true, message: 'Masukkan jumlah hari' }]}>
                  <InputNumber min={1} style={{ width: '100%' }} addonAfter="Hari" />
                </Form.Item>
              )}
            </Col>
          </Row>

          {editingClient && (
            <Form.Item name="flow" label="Flow (Khusus VLESS TCP XTLS)">
              <Select placeholder="Pilih flow (opsional)">
                <Option value="">none</Option>
                <Option value="xtls-rprx-vision">xtls-rprx-vision</Option>
                <Option value="xtls-rprx-vision-udp443">xtls-rprx-vision-udp443</Option>
              </Select>
            </Form.Item>
          )}
        </Form>
      </Modal>

      {/* Share / QR Modal */}
      <Modal
        title="Bagikan Konfigurasi Client"
        open={shareModalOpen}
        onCancel={() => setShareModalOpen(false)}
        footer={[
          <Button key="close" onClick={() => setShareModalOpen(false)}>Tutup</Button>
        ]}
        width={500}
      >
        <Space direction="vertical" align="center" style={{ width: '100%', textAlign: 'center', padding: '16px 0' }}>
          <div
            dangerouslySetInnerHTML={{ __html: shareQr }}
            style={{
              padding: 16,
              background: '#fff',
              borderRadius: 12,
              boxShadow: '0 4px 12px rgba(0,0,0,0.08)',
              display: 'inline-block'
            }}
          />
          <Text type="secondary" style={{ fontSize: 12 }}>Pindai QR ini pada aplikasi Xray Client (V2rayNG, Shadowrocket, dll.)</Text>

          <Input.TextArea
            value={shareLink}
            rows={4}
            readOnly
            style={{ width: '100%', marginTop: 16, fontFamily: 'monospace', fontSize: 11 }}
          />
          <Button
            type="primary"
            icon={<CopyOutlined />}
            onClick={() => copyToClipboard(shareLink)}
            style={{ fontWeight: 700 }}
          >
            Salin Tautan Konfigurasi
          </Button>
        </Space>
      </Modal>
    </Space>
  );
}
