import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  PlayCircle,
  Search,
  FolderKanban,
  ArrowRight,
  Target,
  AlertTriangle,
  BookTemplate,
} from 'lucide-react';
import { opRequests, projects as projectsApi, templates as templatesApi } from '@/api/client';
import type { OpRequest, ProcessTemplate, Project } from '@/types';
import { useUIStore } from '@/store';
import PageHeader from '@/components/common/PageHeader';
import EmptyState from '@/components/common/EmptyState';
import LoadingSpinner from '@/components/common/LoadingSpinner';
import Modal from '@/components/common/Modal';

const urgencyStyles: Record<string, string> = {
  low: 'badge-slate',
  medium: 'badge-accent',
  high: 'badge-amber',
  urgent: 'badge-rose',
};

const resourceTypeByCategory: Record<string, string> = {
  Access: 'software',
  IT: 'system',
  Security: 'system',
  Finance: 'financial',
  Vendor: 'vendor',
};

export default function RequestCatalogPage() {
  const navigate = useNavigate();
  const addNotification = useUIStore((s) => s.addNotification);

  const [templates, setTemplates] = useState<ProcessTemplate[]>([]);
  const [projects, setProjects] = useState<Project[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [search, setSearch] = useState('');
  const [category, setCategory] = useState('All');
  const [selected, setSelected] = useState<ProcessTemplate | null>(null);
  const [projectId, setProjectId] = useState('');
  const [title, setTitle] = useState('');
  const [reason, setReason] = useState('');
  const [resourceName, setResourceName] = useState('');
  const [accessLevel, setAccessLevel] = useState('editor');
  const [urgency, setUrgency] = useState('medium');
  const [durationDays, setDurationDays] = useState('30');
  const [duplicateMatches, setDuplicateMatches] = useState<OpRequest[]>([]);

  useEffect(() => {
    const load = async () => {
      setLoading(true);
      try {
        const [templateList, projectList] = await Promise.all([
          templatesApi.list(),
          projectsApi.list(),
        ]);
        setTemplates(templateList);
        setProjects(projectList);
      } catch (err) {
        addNotification({
          type: 'error',
          title: 'Failed to load request catalog',
          message: err instanceof Error ? err.message : 'Unknown error',
        });
      } finally {
        setLoading(false);
      }
    };

    void load();
  }, [addNotification]);

  const categories = useMemo(
    () => ['All', ...Array.from(new Set(templates.map((template) => template.category || 'Uncategorized')))],
    [templates],
  );

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return templates.filter((template) => {
      const categoryMatch = category === 'All' || (template.category || 'Uncategorized') === category;
      const textMatch =
        !q ||
        [
          template.name,
          template.category,
          template.description,
          template.expected_activities.join(' '),
          template.anti_patterns.map((item) => item.description).join(' '),
        ]
          .join(' ')
          .toLowerCase()
          .includes(q);
      return categoryMatch && textMatch;
    });
  }, [templates, search, category]);

  const openLaunch = (template: ProcessTemplate) => {
    setSelected(template);
    setProjectId(projects[0]?.id ?? '');
    setTitle(template.name);
    setReason(template.description ?? '');
    setResourceName(template.category === 'Access' ? 'Figma' : template.name);
    setAccessLevel(template.category === 'Access' ? 'editor' : 'standard');
    setUrgency('medium');
    setDurationDays('30');
  };

  const handleLaunch = async () => {
    if (!selected || !projectId || !title.trim()) {
      addNotification({
        type: 'error',
        title: 'Missing request details',
        message: 'Pick a workspace and enter a request title before starting.',
      });
      return;
    }

    setSaving(true);
    try {
      const created = await opRequests.create({
        workspace_id: projectId,
        template_id: selected.id,
        title: title.trim(),
        resource_key: resourceName.trim().toLowerCase().replace(/\s+/g, '_') || null,
        resource_name: resourceName.trim() || null,
        access_level: accessLevel.trim() || null,
        reason: reason.trim() || selected.description || null,
        urgency,
        duration_days: durationDays ? Number(durationDays) : null,
        source_type: 'catalog',
      });
      await opRequests.submit(created.id);
      setSaving(false);
      setSelected(null);
      addNotification({
        type: 'success',
        title: 'Request submitted',
        message: 'The request was created, policy-checked, and routed into the approval inbox.',
      });
      navigate('/inbox');
    } catch (err) {
      setSaving(false);
      addNotification({
        type: 'error',
        title: 'Failed to start request',
        message: err instanceof Error ? err.message : 'Unknown error',
      });
    }
  };

  useEffect(() => {
    if (!selected || !projectId || !resourceName.trim()) {
      setDuplicateMatches([]);
      return;
    }
    const handle = window.setTimeout(() => {
      opRequests
        .search({ q: resourceName.trim(), workspace_id: projectId })
        .then((matches) => {
          const normalized = resourceName.trim().toLowerCase();
          setDuplicateMatches(
            matches.filter((item) => (item.resource_name || '').toLowerCase().includes(normalized)),
          );
        })
        .catch(() => setDuplicateMatches([]));
    }, 250);
    return () => window.clearTimeout(handle);
  }, [selected, projectId, resourceName]);

  if (loading) {
    return <LoadingSpinner size="lg" text="Loading request catalog..." fullPage />;
  }

  return (
    <div>
      <PageHeader
        title="Request Catalog"
        icon={PlayCircle}
        description="Start a structured OpsRadar request from a workflow template. Each launch now creates a real request record, policy evaluation event, and approval path."
      />

      <div className="mt-6 flex flex-col gap-3 rounded-2xl border border-line bg-surface-1 p-4 lg:flex-row lg:items-center">
        <div className="relative flex-1">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-fg-faint" />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search templates, categories, or activities..."
            className="input w-full pl-9"
          />
        </div>
        <div className="flex flex-wrap gap-2">
          {categories.map((item) => (
            <button
              key={item}
              onClick={() => setCategory(item)}
              className={`rounded-lg px-3 py-1.5 text-[12px] font-medium transition-colors ${
                category === item
                  ? 'bg-accent/10 text-accent'
                  : 'bg-surface-2 text-fg-muted hover:text-fg'
              }`}
            >
              {item}
            </button>
          ))}
        </div>
      </div>

      {filtered.length === 0 ? (
        <div className="mt-6">
          <EmptyState
            icon={BookTemplate}
            title="No templates match this filter"
            description="Adjust the search or category filter, or add more workflow templates first."
          />
        </div>
      ) : (
        <div className="mt-6 grid gap-4 xl:grid-cols-2">
          {filtered.map((template) => (
            <section key={template.id} className="card p-5">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <div className="flex items-center gap-2">
                    <h2 className="text-[16px] font-semibold text-fg">{template.name}</h2>
                    {template.is_builtin && <span className="badge badge-accent">Built-in</span>}
                  </div>
                  <p className="mt-2 text-[12px] leading-relaxed text-fg-muted">
                    {template.description}
                  </p>
                </div>
                <span className="badge badge-slate">{template.category}</span>
              </div>

              <div className="mt-4 grid gap-3 md:grid-cols-3">
                <div className="rounded-xl bg-surface-2 p-3">
                  <p className="text-[11px] uppercase tracking-wide text-fg-faint">Activities</p>
                  <p className="mt-1 text-[20px] font-semibold text-fg">
                    {template.expected_activities.length}
                  </p>
                </div>
                <div className="rounded-xl bg-surface-2 p-3">
                  <p className="text-[11px] uppercase tracking-wide text-fg-faint">KPI targets</p>
                  <p className="mt-1 text-[20px] font-semibold text-fg">{template.kpis.length}</p>
                </div>
                <div className="rounded-xl bg-surface-2 p-3">
                  <p className="text-[11px] uppercase tracking-wide text-fg-faint">Watchouts</p>
                  <p className="mt-1 text-[20px] font-semibold text-fg">
                    {template.anti_patterns.length}
                  </p>
                </div>
              </div>

              <div className="mt-4">
                <p className="text-[12px] font-medium text-fg">Expected flow</p>
                <div className="mt-2 flex flex-wrap items-center gap-2">
                  {template.expected_activities.slice(0, 5).map((activity, index) => (
                    <div key={`${template.id}-${activity}`} className="flex items-center gap-2">
                      <span className="rounded-md bg-tint px-2.5 py-1 text-[11px] text-fg-secondary">
                        {activity}
                      </span>
                      {index < Math.min(template.expected_activities.length, 5) - 1 && (
                        <ArrowRight size={12} className="text-fg-faint" />
                      )}
                    </div>
                  ))}
                  {template.expected_activities.length > 5 && (
                    <span className="text-[11px] text-fg-faint">
                      +{template.expected_activities.length - 5} more
                    </span>
                  )}
                </div>
              </div>

              <div className="mt-4 flex items-center justify-between">
                <div className="text-[11px] text-fg-faint">
                  Launch creates a real request, event trail, and approval work item.
                </div>
                <button onClick={() => openLaunch(template)} className="btn-primary">
                  <PlayCircle size={15} />
                  Start Request
                </button>
              </div>
            </section>
          ))}
        </div>
      )}

      <Modal
        isOpen={selected !== null}
        onClose={() => setSelected(null)}
        title={selected ? `Start request from ${selected.name}` : 'Start request'}
        size="lg"
        footer={
          <div className="flex items-center gap-2">
            <button onClick={() => setSelected(null)} className="btn-secondary" disabled={saving}>
              Cancel
            </button>
            <button onClick={handleLaunch} className="btn-primary" disabled={saving}>
              {saving ? 'Submitting...' : 'Create Request'}
            </button>
          </div>
        }
      >
        {selected && (
          <div className="space-y-5">
            <div className="rounded-xl border border-line bg-surface-2 p-4">
              <div className="flex flex-wrap items-center gap-2">
                <span className="badge badge-slate">{selected.category}</span>
                <span className={`badge ${urgencyStyles[urgency]}`}>Urgency: {urgency}</span>
              </div>
              <p className="mt-2 text-[12px] leading-relaxed text-fg-muted">{selected.description}</p>
              <div className="mt-3 flex flex-wrap gap-2">
                {selected.expected_activities.map((activity) => (
                  <span key={activity} className="rounded-md bg-surface-1 px-2.5 py-1 text-[11px] text-fg-secondary">
                    {activity}
                  </span>
                ))}
              </div>
            </div>

            {projects.length === 0 ? (
              <EmptyState
                icon={FolderKanban}
                title="No workspaces available"
                description="Create a workspace before starting a templated request."
                action={
                  <button onClick={() => navigate('/projects')} className="btn-primary">
                    Go to Workspaces
                  </button>
                }
                compact
              />
            ) : (
              <div className="grid gap-4 md:grid-cols-2">
                <div className="md:col-span-2">
                  <label className="mb-1.5 block text-[12px] font-medium text-fg-muted">Workspace</label>
                  <select
                    value={projectId}
                    onChange={(e) => setProjectId(e.target.value)}
                    className="input w-full"
                  >
                    {projects.map((project) => (
                      <option key={project.id} value={project.id}>
                        {project.name}
                      </option>
                    ))}
                  </select>
                </div>

                <div className="md:col-span-2">
                  <label className="mb-1.5 block text-[12px] font-medium text-fg-muted">Request title</label>
                  <input
                    value={title}
                    onChange={(e) => setTitle(e.target.value)}
                    className="input w-full"
                    placeholder="Request Figma editor access"
                  />
                </div>

                <div>
                  <label className="mb-1.5 block text-[12px] font-medium text-fg-muted">Resource</label>
                  <input
                    value={resourceName}
                    onChange={(e) => setResourceName(e.target.value)}
                    className="input w-full"
                    placeholder="Figma"
                  />
                  {duplicateMatches.length > 0 && (
                    <div className="mt-2 rounded-xl border border-warning/30 bg-warning/10 px-3 py-2 text-[12px] text-warning">
                      There is already an open request for this resource in the selected workspace. OpsRadar is flagging it before you create duplicate work.
                    </div>
                  )}
                </div>

                <div>
                  <label className="mb-1.5 block text-[12px] font-medium text-fg-muted">Access level</label>
                  <select
                    value={accessLevel}
                    onChange={(e) => setAccessLevel(e.target.value)}
                    className="input w-full"
                  >
                    <option value="viewer">Viewer</option>
                    <option value="editor">Editor</option>
                    <option value="admin">Admin</option>
                    <option value="standard">Standard</option>
                  </select>
                </div>

                <div>
                  <label className="mb-1.5 block text-[12px] font-medium text-fg-muted">Urgency</label>
                  <select
                    value={urgency}
                    onChange={(e) => setUrgency(e.target.value)}
                    className="input w-full"
                  >
                    <option value="low">Low</option>
                    <option value="medium">Medium</option>
                    <option value="high">High</option>
                    <option value="urgent">Urgent</option>
                  </select>
                </div>

                <div>
                  <label className="mb-1.5 block text-[12px] font-medium text-fg-muted">Duration (days)</label>
                  <input
                    value={durationDays}
                    onChange={(e) => setDurationDays(e.target.value)}
                    className="input w-full"
                    inputMode="numeric"
                    placeholder="30"
                  />
                </div>

                <div className="rounded-xl border border-warning/30 bg-warning/10 p-3 md:col-span-2">
                  <div className="flex items-center gap-2 text-[12px] font-semibold text-warning">
                    <AlertTriangle size={14} />
                    Anti-pattern watch
                  </div>
                  <p className="mt-1 text-[11px] text-warning/80">
                    {selected.anti_patterns[0]?.description || 'No anti-patterns captured for this template.'}
                  </p>
                </div>

                <div className="md:col-span-2">
                  <label className="mb-1.5 block text-[12px] font-medium text-fg-muted">Business reason</label>
                  <textarea
                    value={reason}
                    onChange={(e) => setReason(e.target.value)}
                    rows={4}
                    className="input w-full resize-none"
                    placeholder="Explain why the request is needed and what work it unlocks..."
                  />
                </div>

                <div className="rounded-xl border border-line p-4 md:col-span-2">
                  <div className="flex items-center gap-2 text-[12px] font-semibold text-fg">
                    <Target size={14} className="text-accent" />
                    OpsRadar routing guidance
                  </div>
                  <div className="mt-3 grid gap-2 md:grid-cols-2">
                    <div className="rounded-lg bg-surface-2 px-3 py-2">
                      <span className="text-[11px] text-fg-faint">Resource family</span>
                      <p className="mt-1 text-[12px] text-fg-secondary">
                        {resourceTypeByCategory[selected.category || ''] || 'general'}
                      </p>
                    </div>
                    <div className="rounded-lg bg-surface-2 px-3 py-2">
                      <span className="text-[11px] text-fg-faint">Seeded KPI targets</span>
                      <p className="mt-1 text-[12px] text-fg-secondary">
                        {selected.kpis.length > 0 ? `${selected.kpis.length} metrics included` : 'No KPI targets yet'}
                      </p>
                    </div>
                  </div>
                </div>
              </div>
            )}
          </div>
        )}
      </Modal>
    </div>
  );
}
