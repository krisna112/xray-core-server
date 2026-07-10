import { useState, useEffect } from 'react';
import {
  Tabs,
  Form,
  Input,
  InputNumber,
  Button,
  Switch,
  Card,
  Table,
  Space,
  Modal,
  Popconfirm,
  message,
  Typography,
  Tag,
  Row,
  Col
} from 'antd';
import {
  SettingOutlined,
  CloudServerOutlined,
  SafetyOutlined,
  ThunderboltOutlined,
  PlusOutlined,
  DeleteOutlined,
  EditOutlined,
  CheckCircleOutlined,
  SyncOutlined,
  WarningOutlined
} from '@ant-design/icons';
import dayjs from 'dayjs';
import { request } from '../../api/http';

const { Title, Text } = Typography;

export default function SettingsPage() {
  const [activeTab, setActiveTab] = useState('panel');
  const [loading, setLoading] = useState(false);
  const [outbounds, setOutbounds] = useState<any[]>([]);
  const [routingRules, setRoutingRules] = useState<any[]>([]);
  const [balancers, setBalancers] = useState<any[]>([]);
  const [certs, setCerts] = useState<any[]>([]);
  const [warpStatus, setWarpStatus] = useState<any>(null);
  
  const [form] = Form.useForm();
  const [modalOpen, setModalOpen] = useState(false);
  const [modalType, setModalType] = useState<'outbound' | 'routing' | 'balancer' | null>(null);
  const [editingItem, setEditingItem] = useState<any>(null);
  const [modalForm] = Form.useForm();

  const fetchPanelSettings = async () => {
    setLoading(true);
    try {
      const res = await request('/panel/api/settings');
      if (res.success) {
        form.setFieldsValue(res.obj);
      }
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  const fetchOutbounds = async () => {
    const res = await request('/panel/api/outbounds/list');
    if (res.success) setOutbounds(res.obj || []);
  };

  const fetchRouting = async () => {
    const res = await request('/panel/api/routing/list');
    if (res.success) setRoutingRules(res.obj || []);
  };

  const fetchBalancers = async () => {
    const res = await request('/panel/api/balancers/list');
    if (res.success) setBalancers(res.obj || []);
  };

  const fetchCerts = async () => {
    const res = await request('/panel/api/certs');
    if (res.success) setCerts(res.obj || []);
  };

  const fetchWarp = async () => {
    const res = await request('/panel/api/warp/status');
    if (res.success) setWarpStatus(res.obj);
  };

  useEffect(() => {
    if (activeTab === 'panel') fetchPanelSettings();
    if (activeTab === 'outbounds') fetchOutbounds();
    if (activeTab === 'routing') fetchRouting();
    if (activeTab === 'balancers') fetchBalancers();
    if (activeTab === 'certs') {
      fetchCerts();
      fetchWarp();
    }
  }, [activeTab]);

  const handleUpdateSettings = async () => {
    try {
      const values = await form.validateFields();
      const res = await request('/panel/api/settings/update', {
        method: 'POST',
        body: values as any,
      });
      if (res.success) {
        message.success(res.msg || 'Pengaturan berhasil diperbarui!');
        fetchPanelSettings();
      } else {
        message.error(res.msg || 'Gagal memperbarui pengaturan');
      }
    } catch (err: any) {
      message.error(err.message || 'Harap periksa isian form');
    }
  };

  const handleTestTelegram = async () => {
    try {
      const values = await form.validateFields(['tg_bot_token', 'tg_chat_id']);
      const res = await request('/panel/api/settings/test-telegram', {
        method: 'POST',
        body: {
          tg_bot_token: values.tg_bot_token,
          tg_chat_id: values.tg_chat_id,
        } as any,
      });
      if (res.success) {
        message.success('Pesan tes berhasil dikirim ke Telegram!');
      } else {
        message.error(res.msg || 'Gagal mengirim pesan Telegram');
      }
    } catch (err: any) {
      message.error('Token bot & chat ID wajib diisi untuk tes');
    }
  };

  // Outbound / Routing / Balancer CRUD Operations
  const handleOpenAddModal = (type: 'outbound' | 'routing' | 'balancer') => {
    setModalType(type);
    setEditingItem(null);
    modalForm.resetFields();
    if (type === 'outbound') {
      modalForm.setFieldsValue({ enable: true });
    }
    setModalOpen(true);
  };

  const handleOpenEditModal = (type: 'outbound' | 'routing' | 'balancer', item: any) => {
    setModalType(type);
    setEditingItem(item);
    modalForm.resetFields();
    if (type === 'outbound') {
      modalForm.setFieldsValue({
        tag: item.tag,
        config: typeof item.config === 'string' ? item.config : JSON.stringify(item.config, null, 2),
        enable: item.enable,
      });
    } else if (type === 'routing') {
      modalForm.setFieldsValue({
        remark: item.remark,
        rule: typeof item.rule === 'string' ? item.rule : JSON.stringify(item.rule, null, 2),
        enable: item.enable,
        sort: item.sort,
      });
    }
    setModalOpen(true);
  };

  const handleSaveItem = async () => {
    try {
      const values = await modalForm.validateFields();
      let url = '';
      let payload: any = {};

      if (modalType === 'outbound') {
        payload = {
          tag: values.tag,
          config: JSON.parse(values.config),
          enable: values.enable,
        };
        url = editingItem
          ? `/panel/api/outbounds/update/${editingItem.id}`
          : '/panel/api/outbounds/add';
      } else if (modalType === 'routing') {
        payload = {
          remark: values.remark,
          rule: JSON.parse(values.rule),
          enable: values.enable,
          sort: values.sort || 0,
        };
        url = editingItem
          ? `/panel/api/routing/update/${editingItem.id}`
          : '/panel/api/routing/add';
      } else if (modalType === 'balancer') {
        payload = {
          config: JSON.parse(values.config),
        };
        url = '/panel/api/balancers/add';
      }

      const res = await request(url, {
        method: 'POST',
        body: payload as any,
      });

      if (res.success) {
        message.success('Berhasil disimpan');
        setModalOpen(false);
        if (modalType === 'outbound') fetchOutbounds();
        if (modalType === 'routing') fetchRouting();
        if (modalType === 'balancer') fetchBalancers();
      } else {
        message.error(res.msg);
      }
    } catch (e: any) {
      message.error(e.message || 'Pastikan isian valid dan format JSON benar');
    }
  };

  const handleDeleteItem = async (type: 'outbound' | 'routing' | 'balancer', id: number) => {
    const url = `/panel/api/${type === 'routing' ? 'routing' : type + 's'}/del/${id}`;
    const res = await request(url, { method: 'POST' });
    if (res.success) {
      message.success('Berhasil dihapus');
      if (type === 'outbound') fetchOutbounds();
      if (type === 'routing') fetchRouting();
      if (type === 'balancer') fetchBalancers();
    } else {
      message.error(res.msg);
    }
  };

  const handleToggleOutbound = async (ob: any) => {
    const url = `/panel/api/outbounds/${ob.enable ? 'off' : 'on'}/${ob.id}`;
    const res = await request(url, { method: 'POST' });
    if (res.success) {
      message.success(ob.enable ? 'Outbound dinonaktifkan' : 'Outbound diaktifkan');
      fetchOutbounds();
    } else {
      message.error(res.msg);
    }
  };

  const handleRenewCerts = async () => {
    message.loading({ content: 'Sedang memperbarui sertifikat...', key: 'renew' });
    try {
      const res = await request('/panel/api/certs/renew', { method: 'POST' });
      if (res.success) {
        message.success({ content: 'Sertifikat berhasil diperbarui!', key: 'renew' });
        fetchCerts();
      } else {
        message.error({ content: res.msg || 'Gagal memperbarui sertifikat', key: 'renew' });
      }
    } catch (err: any) {
      message.error({ content: err.message, key: 'renew' });
    }
  };

  const handleRegisterWarp = async () => {
    message.loading({ content: 'Mendaftarkan Cloudflare WARP...', key: 'warp' });
    try {
      const res = await request('/panel/api/warp/register', { method: 'POST' });
      if (res.success) {
        message.success({ content: 'WARP berhasil terdaftar! WireGuard outbound telah ditambahkan.', key: 'warp' });
        fetchWarp();
      } else {
        message.error({ content: res.msg || 'Gagal mendaftarkan WARP', key: 'warp' });
      }
    } catch (err: any) {
      message.error({ content: err.message, key: 'warp' });
    }
  };

  return (
    <Space direction="vertical" size="large" style={{ width: '100%' }}>
      <div>
        <Title level={2} style={{ margin: 0, fontWeight: 800 }}>Pengaturan</Title>
        <Text type="secondary">Konfigurasi manajer panel dan integrasi Xray-core</Text>
      </div>

      <Card style={{ borderRadius: 12 }}>
        <Tabs activeKey={activeTab} onChange={setActiveTab}>
          {/* Panel Settings */}
          <Tabs.TabPane tab={<Space><SettingOutlined /><span>Panel</span></Space>} key="panel">
            <Form form={form} layout="vertical" onFinish={handleUpdateSettings} style={{ maxWidth: 800, marginTop: 16 }}>
              <Title level={4}>Pengaturan Umum</Title>
              <Row gutter={16}>
                <Col span={12}>
                  <Form.Item name="domain" label="Domain / IP Publik VPS">
                    <Input placeholder="Contoh: vpn.ceanshark.net" />
                  </Form.Item>
                </Col>
                <Col span={12}>
                  <Form.Item name="timezone" label="Timezone">
                    <Input placeholder="Contoh: Asia/Jakarta" />
                  </Form.Item>
                </Col>
              </Row>
              <Row gutter={16}>
                <Col span={8}>
                  <Form.Item name="listen" label="Listen IP" rules={[{ required: true }]}>
                    <Input />
                  </Form.Item>
                </Col>
                <Col span={8}>
                  <Form.Item name="port" label="Port Panel" rules={[{ required: true }]}>
                    <InputNumber style={{ width: '100%' }} />
                  </Form.Item>
                </Col>
                <Col span={8}>
                  <Form.Item name="session_hours" label="Session Expiry (Jam)" rules={[{ required: true }]}>
                    <InputNumber style={{ width: '100%' }} />
                  </Form.Item>
                </Col>
              </Row>
              <Row gutter={16}>
                <Col span={12}>
                  <Form.Item name="base_path" label="Base Path (Sub-URL)">
                    <Input placeholder="Kosongkan jika di root, contoh: /panelku" />
                  </Form.Item>
                </Col>
                <Col span={12} style={{ display: 'flex', alignItems: 'center', paddingTop: 24 }}>
                  <Form.Item name="realtime" valuePropName="checked" label="Mode Realtime (Voice/Video Call Optimized)">
                    <Switch />
                  </Form.Item>
                </Col>
              </Row>

              <Title level={4} style={{ marginTop: 24 }}>Telegram Bot Notifikasi</Title>
              <Row gutter={16}>
                <Col span={6} style={{ display: 'flex', alignItems: 'center', paddingTop: 24 }}>
                  <Form.Item name="tg_enable" valuePropName="checked" label="Aktifkan Telegram Bot">
                    <Switch />
                  </Form.Item>
                </Col>
                <Col span={9}>
                  <Form.Item name="tg_bot_token" label="Telegram Bot Token">
                    <Input.Password placeholder="Token dari BotFather" />
                  </Form.Item>
                </Col>
                <Col span={9}>
                  <Form.Item name="tg_chat_id" label="Telegram Chat ID">
                    <Input placeholder="Chat ID penerima notifikasi" />
                  </Form.Item>
                </Col>
              </Row>
              <Button type="dashed" onClick={handleTestTelegram} style={{ marginBottom: 24 }}>
                Tes Pesan Telegram
              </Button>

              <Title level={4}>Webhook API Sync</Title>
              <Row gutter={16}>
                <Col span={12}>
                  <Form.Item name="webhook_url" label="Webhook Target URL">
                    <Input placeholder="URL untuk sinkronisasi billing" />
                  </Form.Item>
                </Col>
                <Col span={8}>
                  <Form.Item name="webhook_api_key" label="Webhook API Key">
                    <Input.Password />
                  </Form.Item>
                </Col>
                <Col span={4}>
                  <Form.Item name="sync_push_interval" label="Interval Push (Detik)">
                    <InputNumber style={{ width: '100%' }} />
                  </Form.Item>
                </Col>
              </Row>

              <Form.Item style={{ marginTop: 24 }}>
                <Button type="primary" htmlType="submit" size="large" loading={loading} style={{ fontWeight: 700 }}>
                  Simpan Pengaturan
                </Button>
              </Form.Item>
            </Form>
          </Tabs.TabPane>

          {/* Outbounds */}
          <Tabs.TabPane tab={<Space><CloudServerOutlined /><span>Outbounds</span></Space>} key="outbounds">
            <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 16 }}>
              <Button type="primary" icon={<PlusOutlined />} onClick={() => handleOpenAddModal('outbound')}>
                Tambah Outbound
              </Button>
            </div>
            <Table
              dataSource={outbounds}
              rowKey="id"
              columns={[
                { title: 'Tag', dataIndex: 'tag', key: 'tag', render: (t) => <strong>{t}</strong> },
                {
                  title: 'Protokol',
                  key: 'protocol',
                  render: (_, ob) => {
                    try {
                      const cfg = typeof ob.config === 'string' ? JSON.parse(ob.config) : ob.config;
                      return <Tag color="blue">{(cfg.protocol || 'direct').toUpperCase()}</Tag>;
                    } catch (e) {
                      return <Tag color="red">UNKNOWN</Tag>;
                    }
                  },
                },
                {
                  title: 'Status',
                  dataIndex: 'enable',
                  key: 'enable',
                  render: (enable: boolean) => (
                    <Tag color={enable ? 'success' : 'error'}>{enable ? 'Aktif' : 'Mati'}</Tag>
                  ),
                },
                {
                  title: 'Aksi',
                  key: 'actions',
                  render: (_, ob) => (
                    <Space>
                      <Switch checked={ob.enable} onChange={() => handleToggleOutbound(ob)} size="small" />
                      <Button type="text" icon={<EditOutlined />} onClick={() => handleOpenEditModal('outbound', ob)} />
                      <Popconfirm
                        title="Hapus outbound ini?"
                        onConfirm={() => handleDeleteItem('outbound', ob.id)}
                        okText="Hapus"
                        okButtonProps={{ danger: true }}
                        cancelText="Batal"
                      >
                        <Button type="text" danger icon={<DeleteOutlined />} />
                      </Popconfirm>
                    </Space>
                  ),
                },
              ]}
            />
          </Tabs.TabPane>

          {/* Routing Rules */}
          <Tabs.TabPane tab={<Space><ThunderboltOutlined /><span>Routing Rules</span></Space>} key="routing">
            <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 16 }}>
              <Button type="primary" icon={<PlusOutlined />} onClick={() => handleOpenAddModal('routing')}>
                Tambah Rule
              </Button>
            </div>
            <Table
              dataSource={routingRules}
              rowKey="id"
              columns={[
                { title: 'Urutan', dataIndex: 'sort', key: 'sort', sorter: (a, b) => a.sort - b.sort },
                { title: 'Remark / Nama', dataIndex: 'remark', key: 'remark', render: (r) => <strong>{r}</strong> },
                {
                  title: 'Status',
                  dataIndex: 'enable',
                  key: 'enable',
                  render: (enable: boolean) => (
                    <Tag color={enable ? 'success' : 'error'}>{enable ? 'Aktif' : 'Mati'}</Tag>
                  ),
                },
                {
                  title: 'Aksi',
                  key: 'actions',
                  render: (_, r) => (
                    <Space>
                      <Button type="text" icon={<EditOutlined />} onClick={() => handleOpenEditModal('routing', r)} />
                      <Popconfirm
                        title="Hapus routing rule ini?"
                        onConfirm={() => handleDeleteItem('routing', r.id)}
                        okText="Hapus"
                        okButtonProps={{ danger: true }}
                        cancelText="Batal"
                      >
                        <Button type="text" danger icon={<DeleteOutlined />} />
                      </Popconfirm>
                    </Space>
                  ),
                },
              ]}
            />
          </Tabs.TabPane>

          {/* Balancers */}
          <Tabs.TabPane tab={<Space><CloudServerOutlined /><span>Balancers</span></Space>} key="balancers">
            <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 16 }}>
              <Button type="primary" icon={<PlusOutlined />} onClick={() => handleOpenAddModal('balancer')}>
                Tambah Balancer
              </Button>
            </div>
            <Table
              dataSource={balancers}
              rowKey="id"
              columns={[
                { title: 'ID', dataIndex: 'id', key: 'id' },
                {
                  title: 'Config Balancer',
                  dataIndex: 'config',
                  key: 'config',
                  render: (cfg) => (
                    <pre style={{ margin: 0, fontSize: 11, fontFamily: 'monospace' }}>
                      {typeof cfg === 'string' ? cfg : JSON.stringify(cfg, null, 2)}
                    </pre>
                  ),
                },
                {
                  title: 'Aksi',
                  key: 'actions',
                  render: (_, b) => (
                    <Popconfirm
                      title="Hapus balancer ini?"
                      onConfirm={() => handleDeleteItem('balancer', b.id)}
                      okText="Hapus"
                      okButtonProps={{ danger: true }}
                      cancelText="Batal"
                    >
                      <Button type="text" danger icon={<DeleteOutlined />} />
                    </Popconfirm>
                  ),
                },
              ]}
            />
          </Tabs.TabPane>

          {/* Certificates & WARP */}
          <Tabs.TabPane tab={<Space><SafetyOutlined /><span>Certs & WARP</span></Space>} key="certs">
            <Row gutter={[16, 16]}>
              <Col xs={24} lg={12}>
                <Card title="Sertifikat TLS (acme.sh)" extra={
                  <Button type="primary" icon={<SyncOutlined />} onClick={handleRenewCerts}>
                    Perbarui Certs
                  </Button>
                }>
                  <Table
                    dataSource={certs}
                    rowKey="domain"
                    pagination={false}
                    columns={[
                      { title: 'Domain', dataIndex: 'domain', key: 'domain', render: (d) => <strong>{d}</strong> },
                      {
                        title: 'Expired',
                        dataIndex: 'expire_time',
                        key: 'expire_time',
                        render: (t) => t ? dayjs(t).format('YYYY-MM-DD') : '—',
                      },
                      {
                        title: 'Status',
                        key: 'status',
                        render: (_, record) => {
                          const isExp = record.expire_time && record.expire_time < Date.now();
                          return <Tag color={isExp ? 'error' : 'success'}>{isExp ? 'Expired' : 'Valid'}</Tag>;
                        },
                      },
                    ]}
                  />
                </Card>
              </Col>
              
              <Col xs={24} lg={12}>
                <Card title="Cloudflare WARP (WireGuard)">
                  {warpStatus?.enabled ? (
                    <div style={{ textAlign: 'center', padding: '24px 0' }}>
                      <CheckCircleOutlined style={{ fontSize: 48, color: 'var(--ant-color-success)', marginBottom: 16 }} />
                      <Title level={4}>WARP Berhasil Aktif</Title>
                      <Text type="secondary">Semua routing ke outbound WireGuard WARP akan terhubung otomatis.</Text>
                    </div>
                  ) : (
                    <div style={{ textAlign: 'center', padding: '24px 0' }}>
                      <WarningOutlined style={{ fontSize: 48, color: 'var(--ant-color-warning)', marginBottom: 16 }} />
                      <Title level={4}>WARP Belum Terdaftar</Title>
                      <Text type="secondary" style={{ display: 'block', marginBottom: 24 }}>
                        Daftarkan VPS ini ke Cloudflare WARP secara gratis untuk membuka IP WireGuard lokal.
                      </Text>
                      <Button type="primary" size="large" onClick={handleRegisterWarp} style={{ fontWeight: 700 }}>
                        Auto-Register WARP
                      </Button>
                    </div>
                  )}
                </Card>
              </Col>
            </Row>
          </Tabs.TabPane>
        </Tabs>
      </Card>

      {/* CRUD Modal for Outbound / Routing / Balancer */}
      <Modal
        title={
          modalType === 'outbound'
            ? (editingItem ? 'Edit Outbound' : 'Tambah Outbound')
            : modalType === 'routing'
            ? (editingItem ? 'Edit Routing Rule' : 'Tambah Routing Rule')
            : 'Tambah Balancer'
        }
        open={modalOpen}
        onOk={handleSaveItem}
        onCancel={() => setModalOpen(false)}
        width={600}
        destroyOnClose
      >
        <Form form={modalForm} layout="vertical">
          {modalType === 'outbound' && (
            <>
              <Form.Item name="enable" valuePropName="checked" hidden>
                <Switch />
              </Form.Item>
              <Form.Item name="tag" label="Outbound Tag" rules={[{ required: true }]}>
                <Input placeholder="Contoh: warp_proxy, nordvpn" disabled={!!editingItem} />
              </Form.Item>
              <Form.Item name="config" label="JSON Config Outbound" rules={[{ required: true }]}>
                <Input.TextArea
                  rows={10}
                  style={{ fontFamily: 'monospace', fontSize: 12 }}
                  placeholder={`{\n  "protocol": "freedom",\n  "settings": {}\n}`}
                />
              </Form.Item>
            </>
          )}

          {modalType === 'routing' && (
            <>
              <Form.Item name="enable" valuePropName="checked" hidden>
                <Switch />
              </Form.Item>
              <Row gutter={16}>
                <Col span={18}>
                  <Form.Item name="remark" label="Nama Rule / Remark" rules={[{ required: true }]}>
                    <Input placeholder="Contoh: Blokir Iklan, Bypass Indo" />
                  </Form.Item>
                </Col>
                <Col span={6}>
                  <Form.Item name="sort" label="Urutan Sort">
                    <InputNumber style={{ width: '100%' }} />
                  </Form.Item>
                </Col>
              </Row>
              <Form.Item name="rule" label="JSON Config Routing Rule" rules={[{ required: true }]}>
                <Input.TextArea
                  rows={10}
                  style={{ fontFamily: 'monospace', fontSize: 12 }}
                  placeholder={`{\n  "type": "field",\n  "outboundTag": "block",\n  "domain": [\n    "geosite:category-ads-all"\n  ]\n}`}
                />
              </Form.Item>
            </>
          )}

          {modalType === 'balancer' && (
            <Form.Item name="config" label="JSON Config Balancer" rules={[{ required: true }]}>
              <Input.TextArea
                rows={10}
                style={{ fontFamily: 'monospace', fontSize: 12 }}
                placeholder={`{\n  "tag": "balancer_proxy",\n  "selector": [\n    "node1",\n    "node2"\n  ]\n}`}
              />
            </Form.Item>
          )}
        </Form>
      </Modal>
    </Space>
  );
}
