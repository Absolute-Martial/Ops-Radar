import { useEffect, useMemo, useState } from 'react';
import { Shield, Plus, Save, Lock, UserCog, Trash2, Link2 } from 'lucide-react';
import { opRoleAssignments, projects, systemSettings, users } from '@/api/client';
import type { OpRoleAssignment, OpsRadarRoleBlueprint, Project, User } from '@/types';
import PageHeader from '@/components/common/PageHeader';
import LoadingSpinner from '@/components/common/LoadingSpinner';
import Modal from '@/components/common/Modal';
import { useAuthStore, useUIStore } from '@/store';

const defaultDraft: OpsRadarRoleBlueprint = {
  id: '',
  name: '',
  description: '',
  role_type: 'custom',
  permissions: [],
  scopes: {},
  allowed_request_types: [],
  allowed_resources: [],
  approval_authority: [],
  audit_visibility: 'assigned',
  is_system: false,
  disabled: false,
};

const permissionOptions = [
  'manage_users',
  'manage_roles',
  'manage_sources',
  'manage_workflow_templates',
  'submit_request',
  'view_own_requests',
  'view_team_requests',
  'view_all_requests',
  'view_assigned_approvals',
  'approve_request',
  'reject_request',
  'request_more_info',
  'escalate_request',
  'execute_access_grant',
  'view_audit_logs',
  'export_audit_logs',
  'manage_policy_rules',
  'view_policy_decisions',
];

function parseCommaList(value: string): string[] {
  return value
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean);
}

export default function RoleBuilderPage() {
  const user = useAuthStore((s) => s.user);
  const addNotification = useUIStore((s) => s.addNotification);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [roles, setRoles] = useState<OpsRadarRoleBlueprint[]>([]);
  const [draft, setDraft] = useState<OpsRadarRoleBlueprint>(defaultDraft);
  const [editorOpen, setEditorOpen] = useState(false);
  const [workspaces, setWorkspaces] = useState<Project[]>([]);
  const [workspaceUsers, setWorkspaceUsers] = useState<User[]>([]);
  const [selectedWorkspaceId, setSelectedWorkspaceId] = useState('');
  const [assignments, setAssignments] = useState<OpRoleAssignment[]>([]);
  const [assignmentRoleKey, setAssignmentRoleKey] = useState('manager');
  const [assignmentUserId, setAssignmentUserId] = useState('');

  const canEdit = user?.role === 'admin';

  useEffect(() => {
    const load = async () => {
      setLoading(true);
      try {
        const [res, projectList, userList] = await Promise.all([
          systemSettings.getOpsRadarRoles(),
          projects.list(),
          canEdit ? users.list() : Promise.resolve([]),
        ]);
        setRoles(res.roles);
        setWorkspaces(projectList);
        setWorkspaceUsers(userList);
        setSelectedWorkspaceId(projectList[0]?.id ?? '');
        setAssignmentUserId(userList[0]?.id ?? '');
      } catch (err) {
        addNotification({
          type: 'error',
          title: 'Failed to load role blueprints',
          message: err instanceof Error ? err.message : 'Unknown error',
        });
      } finally {
        setLoading(false);
      }
    };
    void load();
  }, [addNotification, canEdit]);

  useEffect(() => {
    if (!canEdit || !selectedWorkspaceId) {
      setAssignments([]);
      return;
    }
    const loadAssignments = async () => {
      try {
        const rows = await opRoleAssignments.list(selectedWorkspaceId);
        setAssignments(rows);
      } catch (err) {
        addNotification({
          type: 'error',
          title: 'Failed to load role assignments',
          message: err instanceof Error ? err.message : 'Unknown error',
        });
      }
    };
    void loadAssignments();
  }, [addNotification, canEdit, selectedWorkspaceId]);

  const customRoles = useMemo(() => roles.filter((role) => !role.is_system), [roles]);
  const assignableRoles = useMemo(
    () => roles.filter((role) => !role.disabled && role.permissions.includes('approve_request')),
    [roles],
  );

  const openNew = () => {
    setDraft({
      ...defaultDraft,
      id: `custom_${Date.now()}`,
    });
    setEditorOpen(true);
  };

  const openEdit = (role: OpsRadarRoleBlueprint) => {
    setDraft(role);
    setEditorOpen(true);
  };

  const persist = async (nextRoles: OpsRadarRoleBlueprint[]) => {
    if (!canEdit) return;
    setSaving(true);
    try {
      const res = await systemSettings.updateOpsRadarRoles(nextRoles);
      setRoles(res.roles);
      addNotification({ type: 'success', title: 'Role blueprints saved' });
    } catch (err) {
      addNotification({
        type: 'error',
        title: 'Failed to save role blueprints',
        message: err instanceof Error ? err.message : 'Unknown error',
      });
    } finally {
      setSaving(false);
    }
  };

  const saveDraft = async () => {
    const next = roles.some((role) => role.id === draft.id)
      ? roles.map((role) => (role.id === draft.id ? draft : role))
      : [...roles, draft];
    await persist(next);
    setEditorOpen(false);
  };

  const removeRole = async (roleId: string) => {
    await persist(roles.filter((role) => role.id !== roleId));
  };

  const createAssignment = async () => {
    if (!selectedWorkspaceId || !assignmentUserId || !assignmentRoleKey || !canEdit) {
      return;
    }
    try {
      await opRoleAssignments.create({
        workspace_id: selectedWorkspaceId,
        user_id: assignmentUserId,
        role_key: assignmentRoleKey,
      });
      setAssignments(await opRoleAssignments.list(selectedWorkspaceId));
      addNotification({ type: 'success', title: 'Role assignment saved' });
    } catch (err) {
      addNotification({
        type: 'error',
        title: 'Failed to save role assignment',
        message: err instanceof Error ? err.message : 'Unknown error',
      });
    }
  };

  const removeAssignment = async (assignmentId: string) => {
    if (!canEdit) return;
    try {
      await opRoleAssignments.delete(assignmentId);
      setAssignments((prev) => prev.filter((item) => item.id !== assignmentId));
      addNotification({ type: 'success', title: 'Role assignment removed' });
    } catch (err) {
      addNotification({
        type: 'error',
        title: 'Failed to remove role assignment',
        message: err instanceof Error ? err.message : 'Unknown error',
      });
    }
  };

  if (loading) {
    return <LoadingSpinner size="lg" text="Loading role builder…" fullPage />;
  }

  return (
    <div>
      <PageHeader
        title="Role Builder"
        icon={Shield}
        description="Define OpsRadar approval-role blueprints, permission bundles, and request scopes."
        actions={
          canEdit ? (
            <button onClick={openNew} className="btn-primary">
              <Plus size={15} />
              New custom role
            </button>
          ) : undefined
        }
      />

      <div className="mt-6 grid gap-4 xl:grid-cols-[1.2fr_0.8fr]">
        <div className="space-y-4">
          {roles.map((role) => (
            <div key={role.id} className="card p-5">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <div className="flex items-center gap-2">
                    <h3 className="text-[14px] font-semibold text-fg">{role.name}</h3>
                    <span className={role.is_system ? 'badge badge-slate' : 'badge badge-accent'}>
                      {role.is_system ? 'System' : 'Custom'}
                    </span>
                  </div>
                  <p className="mt-1 text-[12px] text-fg-muted">{role.description}</p>
                </div>
                <div className="flex gap-2">
                  <button onClick={() => openEdit(role)} className="btn-secondary">
                    <UserCog size={14} />
                    Edit
                  </button>
                  {!role.is_system && canEdit && (
                    <button onClick={() => removeRole(role.id)} className="btn-secondary text-danger">
                      <Trash2 size={14} />
                    </button>
                  )}
                </div>
              </div>
              <div className="mt-4 grid gap-4 md:grid-cols-3">
                <RoleField label="Permissions" value={`${role.permissions.length} assigned`} />
                <RoleField label="Request types" value={role.allowed_request_types.join(', ') || 'Unrestricted'} />
                <RoleField label="Audit visibility" value={role.audit_visibility} />
              </div>
            </div>
          ))}
        </div>

        <div className="space-y-4">
          <div className="card p-5">
          <div className="flex items-center gap-2 text-[13px] font-semibold text-fg">
            <Lock size={15} className="text-accent" />
            System access model
          </div>
          <p className="mt-2 text-[12px] leading-relaxed text-fg-muted">
            OpsRadar keeps the platform access roles from the current app auth layer
            (`admin`, `analyst`, `viewer`) and uses these role blueprints to model
            request approvals, scope restrictions, and audit visibility inside the product.
          </p>
          <div className="mt-4 rounded-xl border border-line bg-surface-2 p-4 text-[12px] text-fg-muted">
            <p>{roles.filter((role) => role.is_system).length} system blueprints loaded</p>
            <p className="mt-1">{customRoles.length} custom blueprints configured</p>
            <p className="mt-1">{saving ? 'Saving changes…' : 'Ready for additional custom roles'}</p>
          </div>
        </div>

          <div className="card p-5">
            <div className="flex items-center gap-2 text-[13px] font-semibold text-fg">
              <Link2 size={15} className="text-accent" />
              Workspace role assignments
            </div>
            <p className="mt-2 text-[12px] leading-relaxed text-fg-muted">
              Assign approver roles to real users per workspace. These assignments now drive request routing in the approval inbox.
            </p>

            <div className="mt-4 space-y-3">
              <div>
                <label className="mb-1 block text-[12px] font-medium text-fg-muted">Workspace</label>
                <select
                  className="input w-full"
                  value={selectedWorkspaceId}
                  onChange={(e) => setSelectedWorkspaceId(e.target.value)}
                >
                  {workspaces.map((workspace) => (
                    <option key={workspace.id} value={workspace.id}>
                      {workspace.name}
                    </option>
                  ))}
                </select>
              </div>

              {canEdit && (
                <>
                  <div>
                    <label className="mb-1 block text-[12px] font-medium text-fg-muted">User</label>
                    <select
                      className="input w-full"
                      value={assignmentUserId}
                      onChange={(e) => setAssignmentUserId(e.target.value)}
                    >
                      {workspaceUsers.map((workspaceUser) => (
                        <option key={workspaceUser.id} value={workspaceUser.id}>
                          {workspaceUser.full_name} ({workspaceUser.email})
                        </option>
                      ))}
                    </select>
                  </div>
                  <div>
                    <label className="mb-1 block text-[12px] font-medium text-fg-muted">Approval role</label>
                    <select
                      className="input w-full"
                      value={assignmentRoleKey}
                      onChange={(e) => setAssignmentRoleKey(e.target.value)}
                    >
                      {assignableRoles.map((role) => (
                        <option key={role.id} value={role.id}>
                          {role.name}
                        </option>
                      ))}
                    </select>
                  </div>
                  <button onClick={createAssignment} className="btn-primary w-full">
                    <Plus size={14} />
                    Assign role
                  </button>
                </>
              )}
            </div>

            <div className="mt-4 space-y-2">
              {assignments.length === 0 ? (
                <p className="text-[12px] text-fg-faint">No approval roles assigned for this workspace yet.</p>
              ) : (
                assignments.map((assignment) => (
                  <div key={assignment.id} className="rounded-xl border border-line bg-surface-2 p-3">
                    <div className="flex items-start justify-between gap-3">
                      <div>
                        <div className="text-[12px] font-semibold text-fg">
                          {assignment.user_full_name || assignment.user_email}
                        </div>
                        <div className="mt-1 text-[11px] text-fg-muted">{assignment.user_email}</div>
                        <div className="mt-2 text-[11px] text-fg-secondary">Role: {assignment.role_key}</div>
                      </div>
                      {canEdit && (
                        <button
                          onClick={() => removeAssignment(assignment.id)}
                          className="btn-secondary text-danger"
                        >
                          <Trash2 size={14} />
                        </button>
                      )}
                    </div>
                  </div>
                ))
              )}
            </div>
          </div>
        </div>
      </div>

      <Modal
        isOpen={editorOpen}
        onClose={() => setEditorOpen(false)}
        title={draft.is_system ? 'View system role' : 'Edit custom role'}
        size="xl"
        footer={
          <>
            <button onClick={() => setEditorOpen(false)} className="btn-secondary">
              Close
            </button>
            {!draft.is_system && canEdit && (
              <button onClick={saveDraft} disabled={saving || !draft.name.trim()} className="btn-primary">
                <Save size={14} />
                Save role
              </button>
            )}
          </>
        }
      >
        <div className="grid gap-4 md:grid-cols-2">
          <div>
            <label className="mb-1 block text-[12px] font-medium text-fg-muted">Role name</label>
            <input
              className="input w-full"
              value={draft.name}
              disabled={draft.is_system}
              onChange={(e) => setDraft((prev) => ({ ...prev, name: e.target.value }))}
            />
          </div>
          <div>
            <label className="mb-1 block text-[12px] font-medium text-fg-muted">Audit visibility</label>
            <input
              className="input w-full"
              value={draft.audit_visibility}
              disabled={draft.is_system}
              onChange={(e) => setDraft((prev) => ({ ...prev, audit_visibility: e.target.value }))}
            />
          </div>
          <div className="md:col-span-2">
            <label className="mb-1 block text-[12px] font-medium text-fg-muted">Description</label>
            <textarea
              className="input min-h-[96px] w-full py-2"
              value={draft.description}
              disabled={draft.is_system}
              onChange={(e) => setDraft((prev) => ({ ...prev, description: e.target.value }))}
            />
          </div>
          <div className="md:col-span-2">
            <label className="mb-2 block text-[12px] font-medium text-fg-muted">Permissions</label>
            <div className="flex flex-wrap gap-2">
              {permissionOptions.map((permission) => {
                const active = draft.permissions.includes(permission);
                return (
                  <button
                    key={permission}
                    type="button"
                    disabled={draft.is_system}
                    onClick={() =>
                      setDraft((prev) => ({
                        ...prev,
                        permissions: active
                          ? prev.permissions.filter((item) => item !== permission)
                          : [...prev.permissions, permission],
                      }))
                    }
                    className={active ? 'btn-primary' : 'btn-secondary'}
                  >
                    {permission}
                  </button>
                );
              })}
            </div>
          </div>
          <CommaField
            label="Allowed request types"
            value={draft.allowed_request_types.join(', ')}
            disabled={draft.is_system}
            onChange={(value) => setDraft((prev) => ({ ...prev, allowed_request_types: parseCommaList(value) }))}
          />
          <CommaField
            label="Allowed resources"
            value={draft.allowed_resources.join(', ')}
            disabled={draft.is_system}
            onChange={(value) => setDraft((prev) => ({ ...prev, allowed_resources: parseCommaList(value) }))}
          />
          <CommaField
            label="Approval authority"
            value={draft.approval_authority.join(', ')}
            disabled={draft.is_system}
            onChange={(value) => setDraft((prev) => ({ ...prev, approval_authority: parseCommaList(value) }))}
          />
          <CommaField
            label="Scope rules"
            value={Object.entries(draft.scopes).map(([key, value]) => `${key}:${Array.isArray(value) ? value.join('|') : String(value)}`).join(', ')}
            disabled={draft.is_system}
            onChange={(value) =>
              setDraft((prev) => ({
                ...prev,
                scopes: Object.fromEntries(
                  parseCommaList(value).map((entry) => {
                    const [key, raw] = entry.split(':');
                    return [key.trim(), raw ? raw.split('|').map((item) => item.trim()).filter(Boolean) : []];
                  }),
                ),
              }))
            }
          />
        </div>
      </Modal>
    </div>
  );
}

function RoleField({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-line bg-surface-2 p-3">
      <div className="text-[11px] font-semibold uppercase tracking-wider text-fg-faint">{label}</div>
      <div className="mt-1 text-[12px] text-fg-secondary">{value}</div>
    </div>
  );
}

function CommaField({
  label,
  value,
  disabled,
  onChange,
}: {
  label: string;
  value: string;
  disabled: boolean;
  onChange: (value: string) => void;
}) {
  return (
    <div>
      <label className="mb-1 block text-[12px] font-medium text-fg-muted">{label}</label>
      <input
        className="input w-full"
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value)}
      />
    </div>
  );
}
