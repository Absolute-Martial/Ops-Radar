import { useEffect, useMemo, useState } from 'react';
import {
  Inbox,
  CheckCircle2,
  Search,
  X,
  ClipboardCheck,
  ShieldAlert,
  TimerReset,
  MessageSquare,
  Check,
  Ban,
  Clock3,
} from 'lucide-react';
import { formatDistanceToNow } from 'date-fns';
import clsx from 'clsx';
import { opApprovals, opRequests, projects as projectsApi } from '@/api/client';
import { useUIStore } from '@/store';
import type { OpApprovalInboxItem, OpApprovalStatus, OpRequestEvent, Project } from '@/types';
import PageHeader from '@/components/common/PageHeader';
import LoadingSpinner from '@/components/common/LoadingSpinner';
import EmptyState from '@/components/common/EmptyState';

const STATUS_TABS: Array<{
  value: OpApprovalStatus | 'all';
  label: string;
  icon: typeof Inbox;
}> = [
  { value: 'all', label: 'All', icon: Inbox },
  { value: 'pending', label: 'Pending', icon: Clock3 },
  { value: 'approved', label: 'Approved', icon: CheckCircle2 },
  { value: 'rejected', label: 'Rejected', icon: Ban },
  { value: 'escalated', label: 'Escalated', icon: ShieldAlert },
  { value: 'expired', label: 'Expired', icon: TimerReset },
];

const statusTone: Record<OpApprovalStatus, string> = {
  pending: 'bg-warning/10 text-warning',
  approved: 'bg-success/10 text-success',
  rejected: 'bg-danger/10 text-danger',
  escalated: 'bg-accent/10 text-accent',
  expired: 'bg-tint text-fg-muted',
};

const urgencyTone: Record<string, string> = {
  low: 'bg-tint text-fg-muted',
  medium: 'bg-accent/10 text-accent',
  high: 'bg-warning/10 text-warning',
  urgent: 'bg-danger/10 text-danger',
};

const inboxStatuses: OpApprovalStatus[] = ['pending', 'approved', 'rejected', 'escalated', 'expired'];

export default function InboxPage() {
  const addNotification = useUIStore((s) => s.addNotification);

  const [projects, setProjects] = useState<Project[]>([]);
  const [approvals, setApprovals] = useState<OpApprovalInboxItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [tab, setTab] = useState<OpApprovalStatus | 'all'>('pending');
  const [search, setSearch] = useState('');
  const [selected, setSelected] = useState<OpApprovalInboxItem | null>(null);
  const [timeline, setTimeline] = useState<OpRequestEvent[]>([]);
  const [comment, setComment] = useState('');
  const [deciding, setDeciding] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const [projectList, ...approvalGroups] = await Promise.all([
        projectsApi.list(),
        ...inboxStatuses.map((status) => opApprovals.inbox({ status })),
      ]);
      const deduped = new Map<string, OpApprovalInboxItem>();
      approvalGroups.flat().forEach((item) => {
        deduped.set(item.id, item);
      });
      const items = Array.from(deduped.values()).sort(
        (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime(),
      );
      setProjects(projectList);
      setApprovals(items);
      if (items.length > 0) {
        setSelected((current) => items.find((item) => item.id === current?.id) ?? items[0]);
      } else {
        setSelected(null);
      }
    } catch (err) {
      addNotification({
        type: 'error',
        title: 'Failed to load approval inbox',
        message: err instanceof Error ? err.message : 'Unknown error',
      });
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!selected) {
      setTimeline([]);
      setComment('');
      return;
    }
    setComment(selected.decision_comment ?? '');
    const loadTimeline = async () => {
      try {
        const events = await opRequests.events(selected.request_id);
        setTimeline(events);
      } catch (err) {
        addNotification({
          type: 'error',
          title: 'Failed to load request timeline',
          message: err instanceof Error ? err.message : 'Unknown error',
        });
      }
    };
    void loadTimeline();
  }, [selected, addNotification]);

  const projectById = useMemo(
    () => Object.fromEntries(projects.map((project) => [project.id, project])),
    [projects],
  );

  const filtered = useMemo(() => {
    const query = search.trim().toLowerCase();
    return approvals.filter((item) => {
      const statusMatch = tab === 'all' || item.status === tab;
      const textMatch =
        !query ||
        [
          item.request_title,
          item.request_type,
          item.requester_email,
          item.resource_name,
          item.access_level,
          projectById[item.workspace_id]?.name,
        ]
          .filter(Boolean)
          .join(' ')
          .toLowerCase()
          .includes(query);
      return statusMatch && textMatch;
    });
  }, [approvals, tab, search, projectById]);

  const counts = useMemo(() => {
    const tally: Record<OpApprovalStatus, number> = {
      pending: 0,
      approved: 0,
      rejected: 0,
      escalated: 0,
      expired: 0,
    };
    approvals.forEach((item) => {
      tally[item.status] += 1;
    });
    return tally;
  }, [approvals]);

  const decide = async (decision: 'approve' | 'reject') => {
    if (!selected || selected.status !== 'pending') {
      return;
    }
    setDeciding(true);
    try {
      if (decision === 'approve') {
        await opApprovals.approve(selected.id, comment.trim() || undefined);
      } else {
        await opApprovals.reject(selected.id, comment.trim() || undefined);
      }
      await load();
      addNotification({
        type: 'success',
        title: decision === 'approve' ? 'Approval recorded' : 'Request rejected',
        message: decision === 'approve'
          ? 'The request advanced in the OpsRadar lifecycle.'
          : 'The request was moved into a rejected state.',
      });
    } catch (err) {
      addNotification({
        type: 'error',
        title: `Failed to ${decision} request`,
        message: err instanceof Error ? err.message : 'Unknown error',
      });
    } finally {
      setDeciding(false);
    }
  };

  if (loading && approvals.length === 0) {
    return <LoadingSpinner size="lg" text="Loading approval inbox..." fullPage />;
  }

  const pendingCount = counts.pending;
  const urgentCount = approvals.filter((item) => item.status === 'pending' && item.urgency === 'urgent').length;
  const rejectedCount = counts.rejected;
  const highRiskCount = approvals.filter((item) => item.risk_level === 'high').length;

  return (
    <div>
      <PageHeader
        title="Approval Inbox"
        icon={Inbox}
        description="Review live OpsRadar approvals, capture decision comments, and inspect the request timeline before moving work forward."
      />

      <div className="mt-6 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <SummaryCard
          label="Pending approvals"
          value={pendingCount}
          hint="Items waiting on action"
          icon={ClipboardCheck}
        />
        <SummaryCard
          label="High-risk requests"
          value={highRiskCount}
          hint="Requests marked high risk"
          icon={ShieldAlert}
        />
        <SummaryCard
          label="Urgent in queue"
          value={urgentCount}
          hint="Pending and marked urgent"
          icon={TimerReset}
        />
        <SummaryCard
          label="Rejected requests"
          value={rejectedCount}
          hint="Closed out by approvers"
          icon={Ban}
        />
      </div>

      <div className="mt-6 flex flex-wrap items-center gap-2 border-b border-line pb-3">
        {STATUS_TABS.map((item) => {
          const active = tab === item.value;
          const Icon = item.icon;
          const count = item.value === 'all'
            ? approvals.length
            : counts[item.value];
          return (
            <button
              key={item.value}
              onClick={() => setTab(item.value)}
              className={clsx(
                'flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-[12px] font-semibold transition-colors',
                active
                  ? 'bg-accent/10 text-accent'
                  : 'text-fg-muted hover:bg-surface-3 hover:text-fg',
              )}
            >
              <Icon size={13} />
              {item.label}
              <span
                className={clsx(
                  'rounded-full px-1.5 py-0.5 text-[10px] font-bold tabular-nums',
                  active ? 'bg-accent/15' : 'bg-tint',
                )}
              >
                {count}
              </span>
            </button>
          );
        })}
        <div className="ml-auto relative">
          <Search size={12} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-fg-faint" />
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search approvals..."
            className="input w-56 py-1.5 pl-7 pr-7 text-[12px]"
          />
          {search && (
            <button
              onClick={() => setSearch('')}
              className="absolute right-2 top-1/2 -translate-y-1/2 text-fg-faint hover:text-fg"
            >
              <X size={12} />
            </button>
          )}
        </div>
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-[1fr_400px]">
        <div className="space-y-2">
          {filtered.length === 0 ? (
            <EmptyState
              icon={Inbox}
              title={
                search
                  ? `No approvals match "${search}"`
                  : tab === 'all'
                    ? 'The approval inbox is empty'
                    : `No ${tab} approvals`
              }
              description="Requests submitted from the catalog or future intake sources will appear here once routing creates approval records."
            />
          ) : (
            filtered.map((item) => (
              <button
                key={item.id}
                onClick={() => setSelected(item)}
                className={clsx(
                  'card w-full p-4 text-left transition-colors',
                  selected?.id === item.id && 'border-accent/40 bg-accent/5',
                )}
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <h3 className="truncate text-[13px] font-semibold text-fg">{item.request_title}</h3>
                      <StatusBadge status={item.status} />
                      <span
                        className={clsx(
                          'rounded-full px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-wider',
                          urgencyTone[item.urgency] ?? urgencyTone.medium,
                        )}
                      >
                        {item.urgency}
                      </span>
                    </div>
                    <p className="mt-1 line-clamp-1 text-[11px] text-fg-muted">
                      {item.resource_name || 'No resource selected'} · {item.requester_email}
                    </p>
                    <div className="mt-2 flex flex-wrap items-center gap-3 text-[11px] text-fg-faint">
                      <span>{projectById[item.workspace_id]?.name ?? 'Unknown workspace'}</span>
                      <span className="uppercase tracking-wide">{item.request_type.replace(/_/g, ' ')}</span>
                      <span>{formatDistanceToNow(new Date(item.created_at), { addSuffix: true })}</span>
                    </div>
                  </div>
                  <div className="text-right text-[10px] text-fg-faint">
                    <div>Risk</div>
                    <div className="mt-1 font-semibold uppercase tracking-wide text-fg-secondary">
                      {item.risk_level}
                    </div>
                  </div>
                </div>
              </button>
            ))
          )}
        </div>

        <div className="lg:sticky lg:top-4">
          {selected ? (
            <ApprovalDetailPane
              approval={selected}
              projectName={projectById[selected.workspace_id]?.name}
              timeline={timeline}
              comment={comment}
              onCommentChange={setComment}
              onApprove={() => void decide('approve')}
              onReject={() => void decide('reject')}
              deciding={deciding}
            />
          ) : (
            <div className="rounded-xl border border-dashed border-line p-8 text-center">
              <Inbox size={22} className="mx-auto text-fg-ghost" />
              <p className="mt-2 text-[12px] text-fg-muted">
                Select an approval item to inspect the request and take action.
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function SummaryCard({
  label,
  value,
  hint,
  icon: Icon,
}: {
  label: string;
  value: number;
  hint: string;
  icon: typeof Inbox;
}) {
  return (
    <div className="card p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-[11px] uppercase tracking-wide text-fg-faint">{label}</p>
          <p className="mt-2 text-[28px] font-semibold text-fg">{value}</p>
          <p className="mt-1 text-[11px] text-fg-muted">{hint}</p>
        </div>
        <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-accent/10 text-accent">
          <Icon size={17} />
        </div>
      </div>
    </div>
  );
}

function StatusBadge({ status }: { status: OpApprovalStatus }) {
  return (
    <span
      className={clsx(
        'shrink-0 rounded-md px-2 py-0.5 text-[10px] font-semibold capitalize',
        statusTone[status],
      )}
    >
      {status.replace('_', ' ')}
    </span>
  );
}

function ApprovalDetailPane({
  approval,
  projectName,
  timeline,
  comment,
  onCommentChange,
  onApprove,
  onReject,
  deciding,
}: {
  approval: OpApprovalInboxItem;
  projectName?: string;
  timeline: OpRequestEvent[];
  comment: string;
  onCommentChange: (value: string) => void;
  onApprove: () => void;
  onReject: () => void;
  deciding: boolean;
}) {
  const canDecide = approval.status === 'pending';

  return (
    <div className="card p-5">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="text-[14px] font-semibold text-fg">{approval.request_title}</h2>
            <StatusBadge status={approval.status} />
          </div>
          <p className="mt-1 text-[11px] text-fg-muted">
            {projectName || 'Unknown workspace'} · {approval.request_type.replace(/_/g, ' ')}
          </p>
        </div>
        <div className="rounded-lg bg-surface-2 px-2.5 py-1 text-[10px] font-semibold uppercase tracking-wide text-fg-secondary">
          {approval.risk_level} risk
        </div>
      </div>

      <div className="mt-4 grid gap-3 sm:grid-cols-2">
        <DetailField label="Requester" value={approval.requester_email} />
        <DetailField label="Approver role" value={approval.approver_role_key} />
        <DetailField label="Resource" value={approval.resource_name || 'Not set'} />
        <DetailField label="Access level" value={approval.access_level || 'Not set'} />
        <DetailField label="Urgency" value={approval.urgency} />
        <DetailField
          label="Created"
          value={formatDistanceToNow(new Date(approval.created_at), { addSuffix: true })}
        />
      </div>

      <div className="mt-5">
        <div className="flex items-center gap-2 text-[12px] font-semibold text-fg">
          <MessageSquare size={14} className="text-accent" />
          Decision comment
        </div>
        <textarea
          value={comment}
          onChange={(e) => onCommentChange(e.target.value)}
          rows={4}
          className="input mt-2 w-full resize-none"
          disabled={!canDecide || deciding}
          placeholder="Explain the approval or rejection decision..."
        />
      </div>

      <div className="mt-5">
        <div className="text-[12px] font-semibold text-fg">Lifecycle timeline</div>
        <div className="mt-3 space-y-2">
          {timeline.length === 0 ? (
            <p className="text-[11px] text-fg-faint">No lifecycle events recorded yet.</p>
          ) : (
            timeline.map((event) => (
              <div key={event.id} className="rounded-lg bg-surface-2 px-3 py-2">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <div className="text-[11px] font-semibold text-fg">{event.message}</div>
                    <div className="mt-1 text-[10px] uppercase tracking-wide text-fg-faint">
                      {event.event_type.replace(/_/g, ' ')}
                    </div>
                  </div>
                  <div className="text-right text-[10px] text-fg-faint">
                    <div>{formatDistanceToNow(new Date(event.created_at), { addSuffix: true })}</div>
                    {event.actor_email && <div className="mt-1">{event.actor_email}</div>}
                  </div>
                </div>
              </div>
            ))
          )}
        </div>
      </div>

      {canDecide && (
        <div className="mt-5 flex items-center gap-2">
          <button onClick={onApprove} className="btn-primary" disabled={deciding}>
            <Check size={14} />
            {deciding ? 'Saving...' : 'Approve'}
          </button>
          <button onClick={onReject} className="btn-secondary" disabled={deciding}>
            <Ban size={14} />
            Reject
          </button>
        </div>
      )}
    </div>
  );
}

function DetailField({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg bg-surface-2 px-3 py-2">
      <div className="text-[10px] uppercase tracking-wide text-fg-faint">{label}</div>
      <div className="mt-1 text-[12px] text-fg-secondary">{value}</div>
    </div>
  );
}
