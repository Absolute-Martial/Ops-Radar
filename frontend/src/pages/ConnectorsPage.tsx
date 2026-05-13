import { useEffect, useState } from 'react';
import {
  Plus,
  Plug,
  Database,
  FileText,
  Globe,
  Github,
  RefreshCw,
  Trash2,
  Play,
  Clock,
  CheckCircle2,
  XCircle,
  AlertCircle,
  FolderSync,
  CalendarClock,
  Workflow,
  MessageSquare,
} from 'lucide-react';
import { format } from 'date-fns';
import clsx from 'clsx';
import { connectors as connectorsApi, opIntakeSources, projects as projectsApi } from '@/api/client';
import type { Connector, OpIntakeSource, Project } from '@/types';
import LoadingSpinner from '@/components/common/LoadingSpinner';
import Modal from '@/components/common/Modal';
import PageHeader from '@/components/common/PageHeader';
import ConnectorForm from '@/components/Connectors/ConnectorForm';
import { useUIStore } from '@/store';

const typeIcons: Record<string, React.ElementType> = {
  postgresql: Database,
  mysql: Database,
  sqlserver: Database,
  csv_watch: FileText,
  api_endpoint: Globe,
  jira: Globe,
  github: Github,
  odoo: Database,
  zendesk: Globe,
};

const typeLabels: Record<string, string> = {
  postgresql: 'PostgreSQL',
  mysql: 'MySQL',
  sqlserver: 'SQL Server',
  csv_watch: 'CSV Watch',
  api_endpoint: 'REST API',
  jira: 'Jira',
  github: 'GitHub',
  odoo: 'Odoo',
  zendesk: 'Zendesk',
};

const statusConfig = {
  active: {
    label: 'Active',
    color: 'badge-emerald',
    icon: CheckCircle2,
  },
  inactive: {
    label: 'Inactive',
    color: 'badge-slate',
    icon: AlertCircle,
  },
  error: {
    label: 'Error',
    color: 'badge-rose',
    icon: XCircle,
  },
};

export default function ConnectorsPage() {
  const addNotification = useUIStore((s) => s.addNotification);

  const [connectorList, setConnectorList] = useState<Connector[]>([]);
  const [intakeSources, setIntakeSources] = useState<OpIntakeSource[]>([]);
  const [projects, setProjects] = useState<Project[]>([]);
  const [loading, setLoading] = useState(true);
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [showSlackModal, setShowSlackModal] = useState(false);
  const [slackWorkspaceId, setSlackWorkspaceId] = useState('');
  const [slackName, setSlackName] = useState('Slack Access Intake');
  const [slackChannel, setSlackChannel] = useState('');
  const [slackThreshold, setSlackThreshold] = useState('1');
  const [slackNeedsReview, setSlackNeedsReview] = useState(false);

  useEffect(() => {
    loadConnectors();
  }, []);

  const loadConnectors = async () => {
    setLoading(true);
    try {
      const [list, projectList] = await Promise.all([
        connectorsApi.list(),
        projectsApi.list(),
      ]);
      setConnectorList(list);
      setProjects(projectList);
      setSlackWorkspaceId((current) => current || projectList[0]?.id || '');
      opIntakeSources.list().then(setIntakeSources).catch(() => setIntakeSources([]));
    } catch {
      addNotification({
        type: 'error',
        title: 'Failed to load connectors',
      });
    } finally {
      setLoading(false);
    }
  };

  const handleSync = async (id: string) => {
    try {
      const result = await connectorsApi.sync(id);
      addNotification({
        type: result.success ? 'success' : 'error',
        title: result.success ? 'Sync started' : 'Sync failed',
        message: result.message,
      });
    } catch {
      addNotification({ type: 'error', title: 'Sync failed' });
    }
  };

  const handleTest = async (id: string) => {
    try {
      const result = await connectorsApi.test(id);
      addNotification({
        type: result.success ? 'success' : 'error',
        title: result.success ? 'Connection successful' : 'Connection failed',
        message: result.message,
      });
    } catch {
      addNotification({ type: 'error', title: 'Connection test failed' });
    }
  };

  const handleDelete = async (id: string, name: string) => {
    if (!window.confirm(`Delete connector "${name}"?`)) return;
    try {
      await connectorsApi.delete(id);
      setConnectorList((prev) => prev.filter((c) => c.id !== id));
      addNotification({ type: 'success', title: 'Connector deleted' });
    } catch {
      addNotification({
        type: 'error',
        title: 'Failed to delete connector',
      });
    }
  };

  const handleCreateConnector = async (data: any) => {
    try {
      await connectorsApi.create({
        name: data.name,
        connector_type: data.type,
        config: data.config,
        schedule: data.schedule,
      });
      await loadConnectors();
      setShowCreateModal(false);
      addNotification({
        type: 'success',
        title: 'Connector created',
        message: `Connector "${data.name}" has been created successfully.`,
      });
    } catch {
      addNotification({
        type: 'error',
        title: 'Failed to create connector',
      });
    }
  };

  const handleTestNewConnector = async (_data: any) => {
    addNotification({
      type: 'info',
      title: 'Testing connection...',
      message: 'Save the connector first, then use the test button to validate connectivity.',
    });
  };

  const handleCreateSlackIntake = async () => {
    if (!slackWorkspaceId || !slackName.trim()) {
      addNotification({
        type: 'error',
        title: 'Missing Slack intake details',
        message: 'Choose a workspace and give the Slack intake rule a name.',
      });
      return;
    }
    try {
      await opIntakeSources.create({
        workspace_id: slackWorkspaceId,
        name: slackName.trim(),
        source_type: 'slack',
        enabled: true,
        allowed_project_or_channel: slackChannel.trim() || null,
        confidence_threshold: Number(slackThreshold || '1'),
        requires_human_confirmation: slackNeedsReview,
        metadata_json: {
          mode: 'structured_slash_command',
          command: '/opsradar',
        },
      });
      await loadConnectors();
      setShowSlackModal(false);
      addNotification({
        type: 'success',
        title: 'Slack intake source created',
        message: 'OpsRadar can now accept structured Slack requests for this workspace.',
      });
    } catch (err) {
      addNotification({
        type: 'error',
        title: 'Failed to create Slack intake source',
        message: err instanceof Error ? err.message : 'Unknown error',
      });
    }
  };

  if (loading) {
    return <LoadingSpinner size="lg" text="Loading connectors..." fullPage />;
  }

  const activeCount =
    connectorList.filter((connector) => connector.status === 'active').length +
    intakeSources.filter((source) => source.enabled).length;
  const scheduledCount = connectorList.filter((connector) => Boolean(connector.schedule)).length;
  const errorCount = connectorList.filter((connector) => connector.status === 'error').length;
  const sourceFamilies = new Set([
    ...connectorList.map((connector) => connector.connector_type),
    ...intakeSources.map((source) => source.source_type),
  ]).size;

  return (
    <div>
      <PageHeader
        title="Intake Sources"
        icon={Plug}
        description="Manage the systems that feed OpsRadar. Each intake source controls how approval evidence, process events, and exception signals enter the workspace."
        actions={
          <div className="flex items-center gap-2">
            <button
              className="btn-secondary"
              onClick={() => setShowSlackModal(true)}
            >
              <MessageSquare size={18} />
              Add Slack Intake
            </button>
            <button
              className="btn-primary"
              onClick={() => setShowCreateModal(true)}
            >
              <Plus size={18} />
              Add Source
            </button>
          </div>
        }
      />

      <div className="mt-6 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <MetricCard label="Active sources" value={activeCount} icon={FolderSync} />
        <MetricCard label="Scheduled syncs" value={scheduledCount} icon={CalendarClock} />
        <MetricCard label="Source families" value={sourceFamilies} icon={Workflow} />
        <MetricCard label="Needs attention" value={errorCount} icon={AlertCircle} tone="danger" />
      </div>

      {intakeSources.length > 0 && (
        <div className="mt-6 card overflow-hidden">
          <div className="border-b border-line px-5 py-4">
            <h2 className="text-[14px] font-semibold text-fg">Controlled intake rules</h2>
            <p className="mt-1 text-[12px] text-fg-muted">
              These rules decide which REST, CSV, Jira, Slack, or ticket signals can create OpsRadar requests.
            </p>
          </div>
          <div className="divide-y divide-line/70">
            {intakeSources.map((source) => (
              <div key={source.id} className="flex items-center justify-between px-5 py-3">
                <div>
                  <div className="text-[13px] font-semibold text-fg">{source.name}</div>
                  <div className="mt-1 text-[11px] text-fg-muted">
                    {source.source_type} · threshold {(source.confidence_threshold * 100).toFixed(0)}%
                    {source.allowed_project_or_channel ? ` · scope ${source.allowed_project_or_channel}` : ''}
                  </div>
                </div>
                <span className={clsx('badge', source.enabled ? 'badge-emerald' : 'badge-slate')}>
                  {source.enabled ? 'Enabled' : 'Disabled'}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {connectorList.length === 0 && intakeSources.length === 0 ? (
        <div className="mt-16 flex flex-col items-center">
          <div className="rounded-full bg-tint p-4">
            <Plug size={32} className="text-fg-faint" />
          </div>
          <h3 className="mt-4 text-[13px] font-semibold text-fg">
            No intake sources configured
          </h3>
          <p className="mt-1 max-w-md text-center text-[12px] text-fg-muted">
            Start with a database, watched file drop, or API feed so OpsRadar can ingest event data and keep approvals grounded in current operations.
          </p>
          <button
            className="btn-primary mt-6"
            onClick={() => setShowCreateModal(true)}
          >
            <Plus size={18} />
            Add Source
          </button>
        </div>
      ) : (
        <div className="mt-6 space-y-3">
          {connectorList.map((connector) => {
            const TypeIcon =
              typeIcons[connector.connector_type] ?? Plug;
            const status = statusConfig[connector.status];
            const StatusIcon = status.icon;

            return (
              <div key={connector.id} className="card p-5 transition-all">
                <div className="flex items-start justify-between">
                  <div className="flex items-start gap-4">
                    <div className="rounded-lg bg-tint p-2.5">
                      <TypeIcon size={20} className="text-fg-muted" />
                    </div>
                    <div>
                      <div className="flex items-center gap-2">
                        <h3 className="text-[13px] font-semibold text-fg">
                          {connector.name}
                        </h3>
                        <span className={clsx('badge', status.color)}>
                          <StatusIcon size={12} className="mr-1" />
                          {status.label}
                        </span>
                      </div>
                      <p className="mt-1 text-[12px] text-fg-muted">
                        {typeLabels[connector.connector_type] ??
                          connector.connector_type}
                        {connector.schedule && (
                          <span className="ml-2 text-fg-faint">
                            | Intake cadence: {connector.schedule}
                          </span>
                        )}
                      </p>
                      {connector.error_message && (
                        <p className="mt-1 text-[12px] text-danger">
                          {connector.error_message}
                        </p>
                      )}
                      <div className="mt-2 flex items-center gap-4 text-[11px] text-fg-faint">
                        {connector.last_sync && (
                          <div className="flex items-center gap-1">
                            <Clock size={12} />
                            <span>
                              Last intake:{' '}
                              {format(
                                new Date(connector.last_sync),
                                'MMM d, h:mm a',
                              )}
                            </span>
                          </div>
                        )}
                        <span>
                          Added{' '}
                          {format(
                            new Date(connector.created_at),
                            'MMM d, yyyy',
                          )}
                        </span>
                      </div>
                      <div className="mt-3 flex flex-wrap gap-2 text-[10px] font-medium text-fg-faint">
                        <span className="rounded-full bg-tint px-2 py-1">
                          {connector.schedule ? 'Scheduled source' : 'Manual source'}
                        </span>
                        <span className="rounded-full bg-tint px-2 py-1">
                          {(connector.column_mapping &&
                          Object.keys(connector.column_mapping).length > 0)
                            ? 'Mapped for ingestion'
                            : 'Mapping pending'}
                        </span>
                      </div>
                    </div>
                  </div>

                  <div className="flex items-center gap-1">
                    <button
                      onClick={() => handleTest(connector.id)}
                      className="btn-ghost p-1.5"
                      title="Test source"
                    >
                      <Play size={14} />
                    </button>
                    <button
                      onClick={() => handleSync(connector.id)}
                      className="btn-ghost p-1.5"
                      title="Run intake now"
                    >
                      <RefreshCw size={14} />
                    </button>
                    <button
                      onClick={() =>
                        handleDelete(connector.id, connector.name)
                      }
                      className="btn-ghost p-1.5 text-danger hover:bg-danger/10 hover:text-danger"
                      title="Delete source"
                    >
                      <Trash2 size={14} />
                    </button>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* Create Connector Modal */}
      <Modal
        isOpen={showCreateModal}
        onClose={() => setShowCreateModal(false)}
        size="xl"
      >
        <ConnectorForm
          onSave={handleCreateConnector}
          onCancel={() => setShowCreateModal(false)}
          onTest={handleTestNewConnector}
        />
      </Modal>

      <Modal
        isOpen={showSlackModal}
        onClose={() => setShowSlackModal(false)}
        title="Add Slack Intake Source"
        footer={
          <div className="flex items-center gap-2">
            <button className="btn-secondary" onClick={() => setShowSlackModal(false)}>
              Cancel
            </button>
            <button className="btn-primary" onClick={handleCreateSlackIntake}>
              Save Slack Intake
            </button>
          </div>
        }
      >
        <div className="space-y-4">
          <div className="rounded-xl border border-line bg-surface-2 p-4 text-[12px] text-fg-muted">
            Slack is configured as a structured intake rule, not a free-text parser. After saving this rule, point the Slack slash command or modal workflow at `/api/v1/slack/commands` and set `OPSRADAR_SLACK_SIGNING_SECRET` on the backend.
          </div>
          <div>
            <label className="mb-1.5 block text-[12px] font-medium text-fg-muted">Workspace</label>
            <select value={slackWorkspaceId} onChange={(e) => setSlackWorkspaceId(e.target.value)} className="input w-full">
              {projects.map((project) => (
                <option key={project.id} value={project.id}>
                  {project.name}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="mb-1.5 block text-[12px] font-medium text-fg-muted">Rule name</label>
            <input value={slackName} onChange={(e) => setSlackName(e.target.value)} className="input w-full" />
          </div>
          <div>
            <label className="mb-1.5 block text-[12px] font-medium text-fg-muted">Allowed Slack channel or scope</label>
            <input
              value={slackChannel}
              onChange={(e) => setSlackChannel(e.target.value)}
              className="input w-full"
              placeholder="#access-requests or team-access"
            />
          </div>
          <div className="grid gap-4 md:grid-cols-2">
            <div>
              <label className="mb-1.5 block text-[12px] font-medium text-fg-muted">Confidence threshold</label>
              <input
                value={slackThreshold}
                onChange={(e) => setSlackThreshold(e.target.value)}
                className="input w-full"
                inputMode="decimal"
                placeholder="1"
              />
            </div>
            <label className="mt-7 flex items-center gap-2 text-[12px] text-fg-muted">
              <input
                type="checkbox"
                checked={slackNeedsReview}
                onChange={(e) => setSlackNeedsReview(e.target.checked)}
              />
              Require human confirmation before request creation
            </label>
          </div>
        </div>
      </Modal>
    </div>
  );
}

function MetricCard({
  label,
  value,
  icon: Icon,
  tone = 'default',
}: {
  label: string;
  value: number;
  icon: React.ElementType;
  tone?: 'default' | 'danger';
}) {
  return (
    <div className="rounded-xl border border-line bg-surface-1 p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-[11px] font-semibold uppercase tracking-wider text-fg-faint">
            {label}
          </p>
          <p className="mt-2 text-2xl font-semibold tabular-nums text-fg">{value}</p>
        </div>
        <div
          className={clsx(
            'flex h-9 w-9 items-center justify-center rounded-lg',
            tone === 'danger' ? 'bg-danger/10 text-danger' : 'bg-accent/10 text-accent',
          )}
        >
          <Icon size={16} />
        </div>
      </div>
    </div>
  );
}
