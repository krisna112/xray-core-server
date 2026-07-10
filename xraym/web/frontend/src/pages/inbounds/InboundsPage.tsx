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
  Tabs,
  Row,
  Col
} from 'antd';
import {
  PlusOutlined,
  EditOutlined,
  DeleteOutlined,
  ReloadOutlined
} from '@ant-design/icons';
import dayjs from 'dayjs';
import { request } from '../../api/http';

const { Title, Text } = Typography;
const { Option } = Select;

interface Inbound {
  id: number;
  up: number;
  down: number;
  total: number;
  remark: string;
  enable: boolean;
  expiryTime: number;
  listen: string;
  port: number;
  protocol: string;
  settings: string; // JSON string
  streamSettings: string; // JSON string
  sniffing: string; // JSON string
  tag: string;
}

interface Dropdowns {
  protocols: string[];
  networks: string[];
  securities: string[];
  methods: string[];
  fingerprints: string[];
  alpns: string[];
  flows: string[];
}

export default function InboundsPage() {
  const [inbounds, setInbounds] = useState<Inbound[]>([]);
  const [dropdowns, setDropdowns] = useState<Dropdowns | null>(null);
  const [loading, setLoading] = useState(true);
  const [modalOpen, setModalOpen] = useState(false);
  const [editingInbound, setEditingInbound] = useState<Inbound | null>(null);
  const [form] = Form.useForm();
  const [rawJsonMode, setRawJsonMode] = useState(false);

  const fetchData = async () => {
    setLoading(true);
    try {
      const res = await request('/panel/api/inbounds/list');
      if (res.success) {
        setInbounds(res.obj || []);
      }
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  const fetchSettings = async () => {
    try {
      const res = await request('/panel/api/settings');
      if (res.success) {
        setDropdowns(res.obj);
      }
    } catch (err) {
      console.error(err);
    }
  };

  useEffect(() => {
    fetchData();
    fetchSettings();
  }, []);

  const handleOpenAdd = () => {
    setEditingInbound(null);
    form.resetFields();
    form.setFieldsValue({
      port: Math.floor(Math.random() * 50000) + 10000,
      protocol: 'vless',
      network: 'tcp',
      security: 'none',
      enable: true,
      total: 0,
    });
    setRawJsonMode(false);
    setModalOpen(true);
  };

  const handleOpenEdit = (inbound: Inbound) => {
    setEditingInbound(inbound);
    form.resetFields();
    form.setFieldsValue({
      remark: inbound.remark,
      port: inbound.port,
      protocol: inbound.protocol,
      listen: inbound.listen,
      enable: inbound.enable,
      total: inbound.total ? Math.round(inbound.total / (1024 * 1024 * 1024)) : 0, // GB conversion
      expiryTime: inbound.expiryTime > 0 ? dayjs(inbound.expiryTime) : null,
      rawConfig: JSON.stringify(
        {
          port: inbound.port,
          listen: inbound.listen,
          protocol: inbound.protocol,
          settings: JSON.parse(inbound.settings || '{}'),
          streamSettings: JSON.parse(inbound.streamSettings || '{}'),
          sniffing: JSON.parse(inbound.sniffing || '{}'),
        },
        null,
        2
      ),
    });
    setRawJsonMode(false);
    setModalOpen(true);
  };

  const handleSave = async () => {
    try {
      const values = await form.validateFields();
      const isEdit = !!editingInbound;

      let payload: any;
      if (rawJsonMode) {
        try {
          payload = JSON.parse(values.rawConfig);
          payload.remark = values.remark || payload.remark || 'Raw Config';
          payload.enable = values.enable ?? true;
        } catch (e) {
          message.error('Format JSON salah!');
          return;
        }
      } else {
        // Build simple template payload
        payload = {
          remark: values.remark,
          port: values.port,
          protocol: values.protocol,
          listen: values.listen || '',
          enable: values.enable,
          total: values.total ? values.total * 1024 * 1024 * 1024 : 0, // GB to Bytes
          expiryTime: values.expiryTime ? values.expiryTime.valueOf() : 0,
          network: values.network,
          security: values.security,
        };
      }

      const url = isEdit
        ? `/panel/api/inbounds/update/${editingInbound.id}`
        : '/panel/api/inbounds/add';

      const res = await request(url, {
        method: 'POST',
        body: payload as any,
      });

      if (res.success) {
        message.success(isEdit ? 'Inbound diperbarui' : 'Inbound dibuat');
        setModalOpen(false);
        fetchData();
      } else {
        message.error(res.msg || 'Gagal menyimpan inbound');
      }
    } catch (err: any) {
      message.error(err.message || 'Harap periksa isian form');
    }
  };

  const handleDelete = async (id: number) => {
    try {
      const res = await request(`/panel/api/inbounds/del/${id}`, { method: 'POST' });
      if (res.success) {
        message.success('Inbound dihapus');
        fetchData();
      } else {
        message.error(res.msg);
      }
    } catch (err: any) {
      message.error(err.message);
    }
  };

  const handleToggle = async (inbound: Inbound) => {
    try {
      const res = await request(`/panel/api/inbounds/update/${inbound.id}`, {
        method: 'POST',
        body: {
          ...inbound,
          enable: !inbound.enable,
          settings: JSON.parse(inbound.settings || '{}'),
          streamSettings: JSON.parse(inbound.streamSettings || '{}'),
          sniffing: JSON.parse(inbound.sniffing || '{}'),
        } as any,
      });
      if (res.success) {
        message.success(inbound.enable ? 'Inbound dinonaktifkan' : 'Inbound diaktifkan');
        fetchData();
      } else {
        message.error(res.msg);
      }
    } catch (err: any) {
      message.error(err.message);
    }
  };

  const handleResetTraffic = async (id: number) => {
    try {
      const res = await request(`/panel/api/inbounds/resetTraffic/${id}`, { method: 'POST' });
      if (res.success) {
        message.success('Trafik inbound di-reset');
        fetchData();
      } else {
        message.error(res.msg);
      }
    } catch (err: any) {
      message.error(err.message);
    }
  };

  const formatBytes = (bytes: number) => {
    if (!bytes) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
  };

  const columns = [
    {
      title: 'Remark / Tag',
      key: 'remark',
      render: (_: any, record: Inbound) => (
        <div>
          <strong>{record.remark || 'N/A'}</strong>
          <div style={{ fontSize: 11, color: 'var(--ant-color-text-secondary)' }}>{record.tag}</div>
        </div>
      ),
    },
    {
      title: 'Protokol',
      dataIndex: 'protocol',
      key: 'protocol',
      render: (protocol: string) => {
        const colors: Record<string, string> = {
          vless: 'green',
          vmess: 'blue',
          trojan: 'orange',
          shadowsocks: 'purple',
          hysteria: 'magenta',
        };
        return <Tag color={colors[protocol] || 'cyan'}>{protocol.toUpperCase()}</Tag>;
      },
    },
    {
      title: 'Port / Listen',
      key: 'port',
      render: (_: any, record: Inbound) => (
        <div>
          <span>{record.port}</span>
          {record.listen && (
            <div style={{ fontSize: 11, color: 'var(--ant-color-text-secondary)' }}>{record.listen}</div>
          )}
        </div>
      ),
    },
    {
      title: 'Trafik',
      key: 'traffic',
      render: (_: any, record: Inbound) => {
        const total = record.total || 0;
        return (
          <div>
            <div>↑ {formatBytes(record.up)} | ↓ {formatBytes(record.down)}</div>
            <div style={{ fontSize: 11, color: 'var(--ant-color-text-secondary)' }}>
              Total: {formatBytes(record.up + record.down)} / {total ? formatBytes(total) : '∞'}
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
        if (!time) return <Tag>Selamanya</Tag>;
        const left = time - Date.now();
        const days = Math.ceil(left / (1000 * 60 * 60 * 24));
        return (
          <Tag color={days <= 0 ? 'red' : days <= 7 ? 'volcano' : 'green'}>
            {days <= 0 ? 'Expired' : `${days} hari`}
          </Tag>
        );
      },
    },
    {
      title: 'Aksi',
      key: 'actions',
      render: (_: any, record: Inbound) => (
        <Space>
          <Switch
            checked={record.enable}
            onChange={() => handleToggle(record)}
            size="small"
          />
          <Button
            type="text"
            icon={<EditOutlined />}
            onClick={() => handleOpenEdit(record)}
          />
          <Popconfirm
            title="Reset trafik inbound ini?"
            onConfirm={() => handleResetTraffic(record.id)}
            okText="Ya"
            cancelText="Batal"
          >
            <Button type="text" icon={<ReloadOutlined />} />
          </Popconfirm>
          <Popconfirm
            title="Hapus inbound ini?"
            onConfirm={() => handleDelete(record.id)}
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
          <Title level={2} style={{ margin: 0, fontWeight: 800 }}>Inbounds</Title>
          <Text type="secondary">Kelola listener inbound untuk koneksi VPN</Text>
        </div>
        <Button
          type="primary"
          icon={<PlusOutlined />}
          onClick={handleOpenAdd}
          style={{ fontWeight: 700 }}
        >
          Tambah Inbound
        </Button>
      </div>

      <Card style={{ borderRadius: 12 }}>
        <Table
          columns={columns}
          dataSource={inbounds}
          rowKey="id"
          loading={loading}
          pagination={{ pageSize: 10 }}
        />
      </Card>

      {/* Add / Edit Modal */}
      <Modal
        title={editingInbound ? 'Edit Inbound' : 'Tambah Inbound baru'}
        open={modalOpen}
        onOk={handleSave}
        onCancel={() => setModalOpen(false)}
        width={600}
        destroyOnClose
      >
        <Tabs
          activeKey={rawJsonMode ? 'json' : 'form'}
          onChange={(key) => setRawJsonMode(key === 'json')}
          style={{ marginBottom: 16 }}
        >
          <Tabs.TabPane tab="Form Input" key="form" />
          <Tabs.TabPane tab="JSON Config (Advanced)" key="json" />
        </Tabs>

        <Form form={form} layout="vertical">
          <Form.Item name="enable" valuePropName="checked" hidden>
            <Switch />
          </Form.Item>

          <Form.Item
            name="remark"
            label="Remark / Label"
            rules={[{ required: true, message: 'Masukkan remark' }]}
          >
            <Input placeholder="Contoh: VMESS-TCP-TLS" />
          </Form.Item>

          {!rawJsonMode ? (
            <>
              <Row gutter={16}>
                <Col span={12}>
                  <Form.Item
                    name="protocol"
                    label="Protokol"
                    rules={[{ required: true }]}
                  >
                    <Select>
                      {dropdowns?.protocols?.map((p) => (
                        <Option key={p} value={p}>
                          {p.toUpperCase()}
                        </Option>
                      ))}
                    </Select>
                  </Form.Item>
                </Col>
                <Col span={12}>
                  <Form.Item
                    name="port"
                    label="Port"
                    rules={[{ required: true, message: 'Masukkan port' }]}
                  >
                    <InputNumber min={1} max={65535} style={{ width: '100%' }} />
                  </Form.Item>
                </Col>
              </Row>

              <Row gutter={16}>
                <Col span={12}>
                  <Form.Item name="network" label="Transport Network" rules={[{ required: true }]}>
                    <Select>
                      {dropdowns?.networks?.map((n) => (
                        <Option key={n} value={n}>
                          {n}
                        </Option>
                      ))}
                    </Select>
                  </Form.Item>
                </Col>
                <Col span={12}>
                  <Form.Item name="security" label="Keamanan / TLS" rules={[{ required: true }]}>
                    <Select>
                      {dropdowns?.securities?.map((s) => (
                        <Option key={s} value={s}>
                          {s}
                        </Option>
                      ))}
                    </Select>
                  </Form.Item>
                </Col>
              </Row>

              <Row gutter={16}>
                <Col span={12}>
                  <Form.Item name="total" label="Batasan Kuota (GB, 0=∞)">
                    <InputNumber min={0} style={{ width: '100%' }} />
                  </Form.Item>
                </Col>
                <Col span={12}>
                  <Form.Item name="expiryTime" label="Masa Aktif Inbound">
                    <DatePicker style={{ width: '100%' }} format="YYYY-MM-DD HH:mm:ss" showTime />
                  </Form.Item>
                </Col>
              </Row>

              <Form.Item name="listen" label="Alamat Listen IP (Opsional)">
                <Input placeholder="Contoh: 0.0.0.0" />
              </Form.Item>
            </>
          ) : (
            <Form.Item
              name="rawConfig"
              label="JSON Inbound Configuration"
              rules={[{ required: true, message: 'Masukkan konfigurasi JSON' }]}
            >
              <Input.TextArea
                rows={12}
                style={{ fontFamily: 'monospace', fontSize: 12 }}
                placeholder={`{\n  "port": 443,\n  "protocol": "vless",\n  "settings": {\n    "clients": []\n  },\n  "streamSettings": {\n    "network": "tcp",\n    "security": "reality"\n  }\n}`}
              />
            </Form.Item>
          )}
        </Form>
      </Modal>
    </Space>
  );
}
