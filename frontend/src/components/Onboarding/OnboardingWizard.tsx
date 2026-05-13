import { useState } from 'react';
import { Upload, Map, BarChart3, ChevronRight, X, Check, Sparkles } from 'lucide-react';
import clsx from 'clsx';

interface OnboardingWizardProps {
  onDismiss: () => void;
  onNavigate: (path: string) => void;
}

const STEPS = [
  {
    id: 'sample',
    title: 'Start with sample data',
    description:
      'Click below to spin up a sample workspace with request-style trace data. The column mapping is pre-configured so you can jump straight into workflow friction analysis.',
    icon: Sparkles,
    action: 'Create sample workspace',
    path: '/projects?seed=1',
    tip: 'You can also upload your own CSV, XES, Parquet, or Excel from any project — or connect a database / Jira / GitHub.',
  },
  {
    id: 'upload',
    title: 'Or upload your own workflow trace',
    description:
      'Create a workspace, then click Upload. Each row should represent one request step with at least a request ID, step name, and timestamp. OpsRadar auto-detects common column names.',
    icon: Upload,
    action: 'Create workspace',
    path: '/projects?new=1',
    tip: 'Wide tables work too — use the Workflow Trace Builder to turn a table with multiple timestamp columns into a long request-step trace.',
  },
  {
    id: 'discover',
    title: 'Explore the friction map',
    description:
      'OpsRadar builds the friction map automatically. Switch algorithms with the selector (DFG, Alpha, Heuristic, Inductive) and adjust the detail slider to simplify complex workflow paths.',
    icon: Map,
    action: null,
    path: null,
    tip: 'Click any node on the map to see activity statistics. Use the Filter button to drill into specific variants or time windows.',
  },
  {
    id: 'analyze',
    title: 'Run deep analysis',
    description:
      'The analysis tab has specialized cards for delay points, request paths, rework, conformance, social networks, sustainability, agent mining, SQL sandbox, plus an "Ask" card that turns plain-English questions into charts.',
    icon: BarChart3,
    action: null,
    path: null,
    tip: 'Open the Insights panel — it surfaces critical issues, automation opportunities, and root causes in plain language.',
  },
];

export default function OnboardingWizard({ onDismiss, onNavigate }: OnboardingWizardProps) {
  const [currentStep, setCurrentStep] = useState(0);
  const step = STEPS[currentStep];

  return (
    <div className="rounded-lg border border-accent/20 bg-accent/5 p-4">
      {/* Header */}
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <Sparkles size={14} className="text-accent" />
          <span className="text-[12px] font-semibold text-fg">Getting Started with OpsRadar</span>
          <span className="text-[10px] text-fg-faint">Step {currentStep + 1} of {STEPS.length}</span>
        </div>
        <button onClick={onDismiss} className="rounded p-1 text-fg-faint hover:text-fg-muted transition-colors">
          <X size={13} />
        </button>
      </div>

      {/* Progress */}
      <div className="flex gap-1 mb-4">
        {STEPS.map((s, i) => (
          <button
            key={s.id}
            onClick={() => setCurrentStep(i)}
            className={clsx(
              'h-1 flex-1 rounded-full transition-colors',
              i <= currentStep ? 'bg-accent' : 'bg-line',
            )}
          />
        ))}
      </div>

      {/* Step content */}
      <div className="flex gap-4">
        <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-accent/10">
          <step.icon size={20} className="text-accent" />
        </div>
        <div className="flex-1 min-w-0">
          <h3 className="text-[13px] font-semibold text-fg">{step.title}</h3>
          <p className="mt-1 text-[11px] text-fg-muted leading-relaxed">{step.description}</p>
          {step.tip && (
            <p className="mt-2 text-[10px] text-accent/80 bg-accent/5 rounded px-2 py-1.5">
              {step.tip}
            </p>
          )}
        </div>
      </div>

      {/* Actions */}
      <div className="flex items-center justify-between mt-4">
        <div className="flex gap-2">
          {currentStep > 0 && (
            <button
              onClick={() => setCurrentStep(currentStep - 1)}
              className="rounded px-3 py-1.5 text-[11px] font-medium text-fg-muted hover:bg-tint transition-colors"
            >
              Back
            </button>
          )}
        </div>
        <div className="flex gap-2">
          {step.action && step.path && (
            <button
              onClick={() => onNavigate(step.path!)}
              className="flex items-center gap-1.5 rounded-md bg-accent px-3 py-1.5 text-[11px] font-medium text-white hover:bg-accent/90 transition-colors"
            >
              {step.action}
              <ChevronRight size={11} />
            </button>
          )}
          {currentStep < STEPS.length - 1 ? (
            <button
              onClick={() => setCurrentStep(currentStep + 1)}
              className="flex items-center gap-1 rounded px-3 py-1.5 text-[11px] font-medium text-fg-secondary hover:bg-tint transition-colors"
            >
              Next
              <ChevronRight size={11} />
            </button>
          ) : (
            <button
              onClick={onDismiss}
              className="flex items-center gap-1 rounded-md bg-accent px-3 py-1.5 text-[11px] font-medium text-white hover:bg-accent/90 transition-colors"
            >
              <Check size={11} />
              Got it
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
